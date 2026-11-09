"""The DeepSeek path with a scripted model: default config, retries, grounding and citation checks, and the
fallback reason each answer records. No network: `stream_turn` / `_stream_once` are replaced."""

from dataclasses import replace
from datetime import date

import pytest

from services.agent import runner
from services.common.settings import DEEPSEEK_BASE_URL, load_settings
from services.generation import llm
from services.generation.llm import LLMError, ToolCall, Turn

from conftest import build_assistant

TRAVEL = date(2026, 10, 20)


def scripted(*turns):
    """A fake stream_turn that plays back one Turn (or exception) per round."""
    queue = list(turns)
    calls = []

    def stream_turn(settings, messages, tools=None, **_):
        calls.append(messages)
        turn = queue.pop(0)
        if isinstance(turn, Exception):
            raise turn
        if turn.content:
            yield turn.content
        yield turn

    stream_turn.calls = calls
    return stream_turn


def llm_assistant():
    assistant = build_assistant()
    assistant.settings = replace(assistant.settings, llm_api_key="test-key", llm_base_url="http://llm.test")
    return assistant


def tool_turn(name, **arguments):
    import json

    return Turn(tool_calls=[ToolCall(id="call_1", name=name, arguments=json.dumps(arguments))])


def test_a_deepseek_key_alone_turns_the_agent_on(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("SAFARI_LLM_BASE_URL", raising=False)
    settings = load_settings()
    assert settings.llm_enabled and settings.llm_base_url == DEEPSEEK_BASE_URL
    assert settings.llm_model == "deepseek-chat" and settings.llm_provider == "DeepSeek"


def test_another_provider_still_needs_its_endpoint(monkeypatch):
    monkeypatch.setenv("SAFARI_LLM_API_KEY", "sk-test")
    monkeypatch.delenv("SAFARI_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    assert not load_settings().llm_enabled


def test_grounded_cited_answer_comes_from_the_agent(monkeypatch):
    assistant = llm_assistant()
    fake = scripted(
        tool_turn("get_park", park="serengeti"),
        Turn(content="**Serengeti** is famous for the wildebeest migration [1].\n[[answered]]"),
    )
    monkeypatch.setattr(runner, "stream_turn", fake)
    result = assistant.ask("Tell me about Serengeti", as_of=TRAVEL)
    assert result["generator"] == "agent" and result["fallback"] is None
    assert "[1]" in result["answer"] and result["citations"]


def test_uncited_answer_is_rewritten_once_then_falls_back(monkeypatch):
    assistant = llm_assistant()
    uncited = Turn(content="Serengeti is a big park with lots of animals.\n[[answered]]")
    fake = scripted(tool_turn("get_park", park="serengeti"), uncited, uncited)
    monkeypatch.setattr(runner, "stream_turn", fake)
    result = assistant.ask("Tell me about Serengeti", as_of=TRAVEL)
    assert len(fake.calls) == 3  # tool round, first draft, the rewrite
    assert "cites no source" in fake.calls[-1][-1]["content"]
    assert result["generator"] == "composer" and result["fallback"] == "ungrounded_citations"


def test_rewrite_that_adds_the_citation_is_accepted(monkeypatch):
    assistant = llm_assistant()
    fake = scripted(
        tool_turn("get_park", park="serengeti"),
        Turn(content="Serengeti hosts the great migration.\n[[answered]]"),
        Turn(content="Serengeti hosts the great migration [1].\n[[answered]]"),
    )
    monkeypatch.setattr(runner, "stream_turn", fake)
    result = assistant.ask("Tell me about Serengeti", as_of=TRAVEL)
    assert result["generator"] == "agent" and result["fallback"] is None


def test_invented_fee_is_never_shown(monkeypatch):
    assistant = llm_assistant()
    invented = Turn(content="Entry to Serengeti costs TZS 999,999 [1].\n[[answered]]")
    monkeypatch.setattr(runner, "stream_turn", scripted(tool_turn("get_park", park="serengeti"), invented, invented))
    result = assistant.ask("Serengeti entry fee", as_of=TRAVEL)
    assert "999,999" not in result["answer"]
    assert result["generator"] == "composer" and result["fallback"] == "ungrounded_figures"


def test_small_talk_without_tools_needs_no_citation(monkeypatch):
    assistant = llm_assistant()
    monkeypatch.setattr(runner, "stream_turn", scripted(Turn(content="You're welcome! Enjoy your safari.\n[[answered]]")))
    result = assistant.ask("thanks a lot", as_of=TRAVEL)
    assert result["generator"] == "agent" and result["fallback"] is None


def test_provider_error_records_why_it_fell_back(monkeypatch):
    assistant = llm_assistant()
    monkeypatch.setattr(runner, "stream_turn", scripted(LLMError("timed out", "timeout")))
    result = assistant.ask("Tell me about Serengeti", as_of=TRAVEL)
    assert result["generator"] == "composer" and result["fallback"] == "timeout"
    assert result["answer"]  # the visitor still gets the grounded template answer


def test_no_key_means_llm_off():
    result = build_assistant().ask("Tell me about Serengeti", as_of=TRAVEL)
    assert result["generator"] == "composer" and result["fallback"] == "llm_off"


@pytest.fixture()
def no_backoff(monkeypatch):
    monkeypatch.setattr(llm, "BACKOFF_S", (0, 0))


def _flaky(*outcomes):
    """A fake _stream_once: each call takes the next outcome (an LLMError, or text to stream)."""
    queue = list(outcomes)
    calls = []

    def stream_once(*_args, **_kwargs):
        calls.append(1)
        outcome = queue.pop(0)
        if isinstance(outcome, tuple):  # (text, error): stream some text, then fail mid-way
            yield outcome[0]
            raise outcome[1]
        if isinstance(outcome, Exception):
            raise outcome
        yield outcome
        yield Turn(content=outcome)

    stream_once.calls = calls
    return stream_once


def test_rate_limits_and_server_errors_are_retried(monkeypatch, no_backoff):
    fake = _flaky(LLMError("429", "rate_limited"), LLMError("503", "server_error"), "Karibu")
    monkeypatch.setattr(llm, "_stream_once", fake)
    pieces = list(llm.stream_turn(load_settings(), []))
    assert pieces[-1].content == "Karibu" and len(fake.calls) == 3


def test_a_rejected_key_is_not_retried(monkeypatch, no_backoff):
    fake = _flaky(LLMError("401", "auth"), "never reached")
    monkeypatch.setattr(llm, "_stream_once", fake)
    with pytest.raises(LLMError) as failure:
        list(llm.stream_turn(load_settings(), []))
    assert failure.value.kind == "auth" and len(fake.calls) == 1
    assert llm.health()["last_error_kind"] == "auth"


def test_no_retry_once_text_has_streamed(monkeypatch, no_backoff):
    fake = _flaky(("Serengeti is", LLMError("dropped", "network")), "never reached")
    monkeypatch.setattr(llm, "_stream_once", fake)
    with pytest.raises(LLMError):
        list(llm.stream_turn(load_settings(), []))
    assert len(fake.calls) == 1
