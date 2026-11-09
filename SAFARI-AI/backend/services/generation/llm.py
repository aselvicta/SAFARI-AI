"""OpenAI-compatible chat client (DeepSeek by default) with tool calls and streaming."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from services.common.settings import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""

    def parsed(self) -> dict:
        try:
            value = json.loads(self.arguments or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


@dataclass
class Turn:
    """What the model produced in one round."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> dict:
        message: dict = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments or "{}"}}
                for call in self.tool_calls
            ]
        return message


class LLMError(RuntimeError):
    """A failed LLM call. `kind` says why: rate_limited, server_error, timeout, network, auth, bad_request,
    empty or round_limit. Only the first four are worth retrying."""

    def __init__(self, message: str, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


RETRYABLE = {"rate_limited", "server_error", "timeout", "network"}
RETRIES = 2  # after the first attempt, so three tries in all
BACKOFF_S = (1.0, 3.0)

# The last outcome of an LLM call in this process, for the admin dashboard.
_health_lock = threading.Lock()
_health: dict = {"last_ok_at": None, "last_error_at": None, "last_error": None, "last_error_kind": None, "calls": 0, "errors": 0, "retries": 0}


def health() -> dict:
    with _health_lock:
        return dict(_health)


def _record(ok: bool, error: LLMError | None = None, retried: bool = False) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _health_lock:
        if retried:
            _health["retries"] += 1
            return
        _health["calls"] += 1
        if ok:
            _health["last_ok_at"] = now
        else:
            _health["errors"] += 1
            _health["last_error_at"] = now
            _health["last_error"] = str(error)[:300]
            _health["last_error_kind"] = error.kind if error else "error"


def _status_kind(code: int) -> str:
    if code == 429:
        return "rate_limited"
    if code in (401, 403):
        return "auth"
    if code == 402:
        return "auth"  # DeepSeek: insufficient balance; the key works but can't pay
    if code >= 500:
        return "server_error"
    return "bad_request"


def stream_turn(settings: Settings, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.3, timeout: float = 60.0) -> Iterator[str | Turn]:
    """Yield content deltas (str) as they arrive, then the complete Turn last.

    Rate limits, server errors, timeouts and dropped connections are retried (with backoff) as long as
    nothing has been streamed yet; a call that fails part-way, or for a reason retrying can't fix
    (a rejected key, a bad request), raises LLMError at once."""
    for attempt in range(RETRIES + 1):
        produced = False
        try:
            for piece in _stream_once(settings, messages, tools, temperature, timeout):
                produced = True
                yield piece
            _record(True)
            return
        except LLMError as exc:
            if exc.kind in RETRYABLE and not produced and attempt < RETRIES:
                _record(False, retried=True)
                time.sleep(getattr(exc, "retry_after", None) or BACKOFF_S[attempt])
                continue
            _record(False, exc)
            raise


def _stream_once(settings: Settings, messages: list[dict], tools: list[dict] | None, temperature: float, timeout: float) -> Iterator[str | Turn]:
    base = settings.llm_base_url.rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    body: dict = {"model": settings.llm_model, "temperature": temperature, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    turn = Turn()
    calls: dict[int, ToolCall] = {}
    try:
        with httpx.stream(
            "POST",
            endpoint,
            headers={"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=httpx.Timeout(timeout, connect=10.0),
        ) as response:
            if response.status_code >= 400:
                error = LLMError(f"LLM HTTP {response.status_code}: {response.read()[:300]!r}", _status_kind(response.status_code))
                retry_after = response.headers.get("retry-after", "")
                if retry_after.isdigit():
                    error.retry_after = min(5.0, float(retry_after))
                raise error
            for line in response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        turn.content += text
                        yield text
                    for item in delta.get("tool_calls") or []:
                        index = item.get("index", 0)
                        call = calls.setdefault(index, ToolCall(id=item.get("id") or f"call_{index}", name=""))
                        if item.get("id"):
                            call.id = item["id"]
                        function = item.get("function") or {}
                        if function.get("name"):
                            call.name += function["name"]
                        if function.get("arguments"):
                            call.arguments += function["arguments"]
    except httpx.TimeoutException as exc:
        raise LLMError(f"timed out: {exc}", "timeout") from exc
    except httpx.HTTPError as exc:
        raise LLMError(str(exc) or exc.__class__.__name__, "network") from exc
    turn.tool_calls = [calls[index] for index in sorted(calls) if calls[index].name]
    yield turn
