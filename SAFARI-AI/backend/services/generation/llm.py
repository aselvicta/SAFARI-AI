"""OpenAI-compatible chat client (DeepSeek by default) with tool calls and streaming."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

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
    pass


def stream_turn(settings: Settings, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.3, timeout: float = 60.0) -> Iterator[str | Turn]:
    """Yield content deltas (str) as they arrive, then the complete Turn last."""
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
                raise LLMError(f"LLM HTTP {response.status_code}: {response.read()[:300]!r}")
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
    except httpx.HTTPError as exc:
        raise LLMError(str(exc)) from exc
    turn.tool_calls = [calls[index] for index in sorted(calls) if calls[index].name]
    yield turn
