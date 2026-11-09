"""House style: no em or en dashes anywhere visitors or admins read, whatever produced the text."""

import random

import pytest

from services.common.typography import DashStream, clean, clean_dashes

from test_api import _client

DASHES = ("—", "–")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("The park — famous for the migration — is huge.", "The park, famous for the migration, is huge."),
        ("Mikumi—close to Dar—is ideal.", "Mikumi, close to Dar, is ideal."),
        ("Valid 16 May 2026 – 14 Mar 2027.", "Valid 16 May 2026 to 14 Mar 2027."),
        ("Children 5–15; best Jun–Oct; tariff 2026–27.", "Children 5-15; best Jun-Oct; tariff 2026-27."),
        ("— first\n  — second", "- first\n  - second"),
        ("**Serengeti** — vast plains [1]", "**Serengeti**, vast plains [1]"),
        ("Ends with a dash —", "Ends with a dash"),
        ("Bracket (— aside) and colon: — value", "Bracket (aside) and colon: value"),
        ("No dashes, 2026-27.", "No dashes, 2026-27."),
    ],
)
def test_clean_dashes(raw, expected):
    assert clean_dashes(raw) == expected


def test_clean_walks_nested_values_and_leaves_keys():
    value = {"a — key": ["x — y", {"n": 5, "s": "1–2"}], "none": None}
    assert clean(value) == {"a — key": ["x, y", {"n": 5, "s": "1-2"}], "none": None}


def test_streamed_text_matches_whole_text_cleaning():
    text = "**Serengeti** — the migration, Jun–Oct.\n\n— Ngorongoro — NCAA —, not TANAPA (— approx) —"
    random.seed(3)
    for _ in range(300):
        stream, out, i = DashStream(), "", 0
        while i < len(text):
            size = random.randint(1, 6)
            out += stream.feed(text[i : i + size])
            i += size
        assert out + stream.flush() == clean_dashes(text)


def _no_dashes(payload: str):
    found = [dash for dash in DASHES if dash in payload]
    assert not found, f"dash found: {payload[max(0, payload.find(found[0]) - 60):payload.find(found[0]) + 60]!r}"


def test_no_dash_reaches_visitors_or_admins(monkeypatch):
    with _client(monkeypatch) as client:
        # Source titles, TANAPA page text and composed answers in the test store contain dashes.
        for question in ("Tell me about Serengeti", "Serengeti entry fees for 2 adults and a child of 7", "Ngorongoro fees", "Do Germans need a visa?"):
            _no_dashes(client.post("/v1/ask", json={"question": question, "as_of": "2026-10-20", "profile": {"passport": "Germany"}}).text)
        _no_dashes(client.post("/v1/ask/stream", json={"question": "Tell me about Tarangire", "as_of": "2026-10-20"}).text)
        for path in ("/v1/parks", "/v1/parks/serengeti", "/v1/status", "/v1/documents", "/v1/admin/overview", "/v1/admin/inventory", "/v1/admin/documents", "/v1/admin/fees"):
            _no_dashes(client.get(path).text)
        briefing = client.post("/v1/briefing", json={"question": "3 days in Serengeti", "parks": ["serengeti"], "days": 3, "adults": 2, "child_ages": [7]})
        _no_dashes(briefing.text)


def test_dashes_in_indexed_documents_and_llm_output_are_removed(monkeypatch):
    """The safety net, not just our own copy: dashes injected through a document and a streaming LLM."""
    from dataclasses import replace

    from services.agent import runner
    from services.generation.llm import ToolCall, Turn

    with _client(monkeypatch) as client:
        # 1. A document whose title and text are full of dashes, like scraped pages can be.
        upload = client.post(
            "/v1/documents",
            files={"file": ("night-drives.md", "# Night drives — Serengeti\n\nNight drives — guided, 20:00–22:00 — run 1 Jul 2026 – 30 Jun 2027 in Serengeti.".encode(), "text/markdown")},
            data={"metadata": '{"title": "Serengeti night drives — TANAPA", "organization": "TANAPA", "authority": "official"}'},
        )
        assert upload.status_code == 200
        _no_dashes(upload.text)
        _no_dashes(client.get("/v1/admin/documents").text)
        _no_dashes(client.post("/v1/ask", json={"question": "Are there night drives in Serengeti?", "as_of": "2026-10-20"}).text)

        # 2. An LLM that streams dashes split across chunks.
        assistant = client.app.state.assistant
        assistant.settings = replace(assistant.settings, llm_api_key="k", llm_base_url="http://llm.test")
        import re

        # No figures: the grounding check would (rightly) reject numbers the park tool didn't return.
        answer = "**Serengeti** — the migration [{n}] — peaks Jun–Oct—plains—woodland [{n}].\n— a bullet\n[[answered]]"
        rounds = [Turn(tool_calls=[ToolCall(id="c1", name="get_park", arguments='{"park": "serengeti"}')]), None]

        def stream_turn(settings, messages, tools=None, **_):
            turn = rounds.pop(0)
            if turn is None:  # cite the number the park tool actually returned, as a grounded model would
                cite = re.search(r'"cite[a-z_]*": (\d+)', messages[-1]["content"]).group(1)
                turn = Turn(content=answer.format(n=cite))
            for i in range(0, len(turn.content), 3):
                yield turn.content[i : i + 3]
            yield turn

        monkeypatch.setattr(runner, "stream_turn", stream_turn)
        streamed = client.post("/v1/ask/stream", json={"question": "Tell me about Serengeti", "as_of": "2026-10-20"}).text
        _no_dashes(streamed)
        assert '"generator": "agent"' in streamed
        assert "Jun-Oct, plains, woodland" in streamed and "\\n- a bullet" in streamed


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Entrance Children 5 - 15 Years", "Entrance Children 5 to 15 Years"),
        ("General Brochure - English", "General Brochure, English"),
        ("- bullet\n  - nested", "- bullet\n  - nested"),
        ("well-known, 5-15, 2026-11-10, -5", "well-known, 5-15, 2026-11-10, -5"),
        ("| a | - |", "| a | - |"),
    ],
)
def test_spaced_hyphens_read_as_dashes_and_are_cleaned_too(raw, expected):
    assert clean_dashes(raw) == expected
