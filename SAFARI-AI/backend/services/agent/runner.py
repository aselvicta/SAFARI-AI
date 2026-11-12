"""The LLM tool-calling loop, with streaming and a grounding check on the final draft."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from services.agent import attribution
from services.agent.prompts import system_prompt
from services.agent.tools import TOOL_SCHEMAS, Toolbox
from services.common.settings import Settings
from services.common.typography import DashStream, clean_dashes
from services.generation.llm import LLMError, stream_turn

Emit = Callable[[str, dict], None]
MAX_ROUNDS = 5

STATUS = {
    "get_fees": "Checking the TANAPA 2026/27 tariff",
    "estimate_trip_cost": "Working out park fees for your group",
    "get_park": "Reading the official park page",
    "recommend_parks": "Shortlisting parks",
    "check_visa": "Checking the immigration visa list",
    "search_knowledge": "Searching official documents",
}

_NUMBER = re.compile(r"(?<![\w\[])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w\]])")
_CITE = re.compile(r"\[(\d{1,2})\]")
log = logging.getLogger("safari.agent")
_STATUS = re.compile(r"\[\[\s*(answered|not_found|out_of_scope)\s*\]\]", re.IGNORECASE)


class StatusFilter:
    """Passes streamed text through, holding back the trailing [[status]] tag."""

    def __init__(self, emit: Emit) -> None:
        self.emit = emit
        self.buffer = ""
        self.closed = False
        self.dashes = DashStream()  # the house style applies to text as it streams, not only to the final answer

    def _send(self, text: str) -> None:
        text = self.dashes.feed(text)
        if text:
            self.emit("delta", {"text": text})

    def feed(self, text: str) -> None:
        if self.closed:
            return
        self.buffer += text
        if "[[" in self.buffer:
            head = self.buffer.split("[[", 1)[0]
            if head:
                self._send(head)
            tail = self.dashes.flush()
            if tail:
                self.emit("delta", {"text": tail})
            self.buffer = ""
            self.closed = True
            return
        keep = 1 if self.buffer.endswith("[") else 0
        out, self.buffer = self.buffer[: len(self.buffer) - keep], self.buffer[len(self.buffer) - keep :]
        if out:
            self._send(out)

    def flush(self) -> None:
        if self.closed:
            return
        if self.buffer:
            self._send(self.buffer)
        tail = self.dashes.flush()
        if tail:
            self.emit("delta", {"text": tail})
        self.buffer = ""


def split_status(text: str) -> tuple[str, str]:
    match = _STATUS.search(text)
    status = match.group(1).lower() if match else "answered"
    return _STATUS.sub("", text).rstrip(), status


class Ungrounded(RuntimeError):
    """The final draft failed the grounding check twice. `kind`: figures (numbers no tool returned) or
    citations (an answer with no source cited)."""

    def __init__(self, message: str, kind: str = "figures") -> None:
        super().__init__(message)
        self.kind = kind


def run_agent(question: str, history: list[dict], tools: Toolbox, settings: Settings, language: str, emit: Emit) -> tuple[str, str]:
    """Returns (answer, status) where status is answered | not_found | out_of_scope."""
    messages: list[dict] = [{"role": "system", "content": system_prompt(tools.as_of, tools.profile, language)}]
    for turn in history[-8:]:
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:1500]})
    messages.append({"role": "user", "content": question})
    emit("status", {"label": "Thinking"})
    retried = False
    for _round in range(MAX_ROUNDS):
        turn = None
        streamed = False
        stream = StatusFilter(emit)
        for piece in stream_turn(settings, messages, TOOL_SCHEMAS):
            if isinstance(piece, str):
                streamed = True
                stream.feed(piece)
            else:
                turn = piece
        stream.flush()
        if turn is None:
            raise LLMError("empty response", "empty")
        if turn.tool_calls:
            if streamed:
                emit("reset", {})
            messages.append(turn.as_message())
            for call in turn.tool_calls:
                emit("status", {"label": STATUS.get(call.name, "Looking it up")})
                result = tools.call(call.name, call.parsed())
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)[:9000]})
            emit("status", {"label": "Writing your answer"})
            continue
        text, status = split_status(turn.content.strip())
        problems = ungrounded_numbers(text, tools, question)
        # An answer drawn from tool results must cite one. (Small talk or a clarifying question uses no tool, so
        # there is nothing to cite; the figures check still applies to it.)
        uncited = status == "answered" and bool(tools.citations) and not cites_a_source(text, tools)
        # Each cited figure must come from the source cited next to it, not just from some tool result.
        facts = attribution.collect(tools.results)
        miscited = attribution.check(text, facts)
        if (problems or uncited or miscited) and not retried:
            retried = True
            emit("reset", {})
            emit("status", {"label": "Double-checking figures" if problems else "Checking sources"})
            log.info("agent draft rejected: figures=%s uncited=%s miscited=%d", problems, uncited, len(miscited))
            messages.append({"role": "assistant", "content": turn.content})
            issues = []
            if problems:
                issues.append("these figures are not in any tool result: " + ", ".join(problems) + ". Use only numbers that appear in tool results; call a tool if you need a total")
            if uncited:
                issues.append(
                    "the answer cites no source. Every factual sentence needs the [n] cite number of the tool result it comes from; "
                    "call a tool first if you have no result for it, and if the tools don't answer the question, end with [[not_found]]"
                )
            if miscited:
                issues.append(
                    "some cite numbers point to the wrong source: "
                    + attribution.describe(miscited, tools.citations)
                    + ". Put each figure next to the cite number of the tool item it came from; give totals and planning notes no cite"
                )
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Internal check (never mention it to the visitor): "
                        + "; and ".join(issues)
                        + ". Write the complete answer again from the start, as if for the first time. Do not apologise or refer to a correction."
                    ),
                }
            )
            continue
        if problems:
            raise Ungrounded(", ".join(problems), "figures")
        if uncited:
            raise Ungrounded("no source cited", "citations")
        if miscited:
            log.warning("repairing %d miscited segment(s) after the retry", len(miscited))
            text = attribution.repair(text, facts)
        return clean_dashes(clean_citations(text, tools)), status
    raise LLMError("the agent did not finish within the round limit", "round_limit")


def cites_a_source(text: str, tools: Toolbox) -> bool:
    """True when the answer cites at least one source a tool actually returned."""
    known = {citation["n"] for citation in tools.citations}
    return any(int(number) in known for number in _CITE.findall(text))


def ungrounded_numbers(text: str, tools: Toolbox, question: str) -> list[str]:
    allowed = _numbers(" ".join(tools.evidence)) | _numbers(question) | _numbers(json.dumps(tools.profile)) | _numbers(tools.as_of.isoformat())
    body = _CITE.sub(" ", text)
    body = re.sub(r"(?m)^\s*\d+\.\s", " ", body)
    bad = []
    for raw in _NUMBER.findall(body):
        value = _norm(raw)
        if value in allowed:
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        if number <= 15 or _close(number, allowed):
            continue
        bad.append(raw)
    return sorted(set(bad))


def clean_citations(text: str, tools: Toolbox) -> str:
    known = {citation["n"] for citation in tools.citations}
    return _CITE.sub(lambda match: match.group(0) if int(match.group(1)) in known else "", text)


def _numbers(text: str) -> set[str]:
    return {_norm(item) for item in _NUMBER.findall(text or "")} | {_norm(item) for item in re.findall(r"\d+(?:\.\d+)?", text or "")}


def _norm(number: str) -> str:
    number = number.replace(",", "")
    if "." in number:
        whole, frac = number.split(".", 1)
        frac = frac.rstrip("0")
        return (whole.lstrip("0") or "0") + (f".{frac}" if frac else "")
    return number.lstrip("0") or "0"


def _close(number: float, allowed: set[str]) -> bool:
    """A rounded form of an allowed figure (USD 69.99 written as 70) is fine."""
    for item in allowed:
        try:
            value = float(item)
        except ValueError:
            continue
        if value >= 10 and abs(value - number) <= max(0.51, value * 0.002):
            return True
    return False
