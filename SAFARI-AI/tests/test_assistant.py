from datetime import date

from services.agent.runner import ungrounded_numbers
from services.agent.tools import Toolbox
from services.common.embeddings import HashEmbedder
from services.common.models import Chunk
from services.common.scoring import HybridWeights, bm25_scores, confidence_label, confidence_score, freshness_score, hybrid_score
from services.common.store import JsonStore
from services.catalog import seed_catalog
from services.conversation.memory import SessionMemory
from services.conversation.understand import understand
from services.evaluation.metrics import f1_at_k, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from services.evaluation.runner import evaluate, load_questions
from services.knowledge import tariffs
from services.ranking.rerank import rerank
from services.retrieval.hybrid import score_chunks

from conftest import build_assistant

TRAVEL = date(2026, 10, 20)


def test_hybrid_score_and_confidence_bands():
    assert abs(hybrid_score(1, 1, 1, 1, 1, HybridWeights()) - 1) < 1e-9
    assert confidence_label(confidence_score(1, 1, 1, 1)) == "HIGH"
    assert confidence_label(0.5) == "MEDIUM"
    assert confidence_label(0.2) == "LOW"


def test_bm25_prefers_the_document_that_contains_the_query_term():
    scores = bm25_scores(["ruaha", "area"], [["serengeti", "plains"], ["ruaha", "area", "kilometres"]])
    assert scores[1] > scores[0]


def test_version_gate_ranks_the_in_force_document_first():
    embedder = HashEmbedder()
    text = "Serengeti conservation fee per adult non-resident."
    common = dict(text=text, position=0, embedding=embedder.embed(text), document_type="tariff", authority_score=1, park_slug="serengeti")
    old = Chunk(chunk_id="old:0", document_id="old", title="Tariff 2023/24", status="superseded", effective_from="2023-07-01", effective_until="2024-06-30", **common)
    new = Chunk(chunk_id="new:0", document_id="new", title="Tariff 2026/27", status="current", effective_from="2026-07-01", effective_until="2027-06-30", **common)
    store = JsonStore(None)
    seed_catalog(store)
    query = understand("What is the Serengeti conservation fee?", store.list_parks())
    ranked = rerank(query, score_chunks(query, [old, new], embedder, TRAVEL), TRAVEL)
    assert ranked[0].chunk.document_id == "new"
    assert ranked[1].version_penalized is True
    assert freshness_score(old, TRAVEL) < freshness_score(new, TRAVEL)


def test_fee_answer_quotes_the_live_tariff_with_dates(assistant):
    result = assistant.ask("What are the Serengeti entry fees?", as_of=TRAVEL)
    assert result["abstained"] is False
    assert result["confidence_label"] == "HIGH"
    assert "178,850" in result["answer"]
    assert "2026-05-16" in result["answer"]
    block = next(item for item in result["blocks"] if item["type"] == "fees")
    assert {row["visitor"] for row in block["rows"]} == {"non_resident", "expatriate", "eac_citizen"}
    assert result["citations"][0]["source_url"].endswith("/tariff")


def test_fee_outside_the_published_window_is_not_quoted(assistant):
    result = assistant.ask("What are the Serengeti entry fees?", as_of=date(2027, 4, 1))
    assert "178,850" not in result["answer"]


def test_passport_selects_the_fee_class(assistant):
    kenya = assistant.ask("How much is Tarangire entry?", as_of=TRAVEL, profile={"passport": "Kenya"})
    assert "East African citizen" in kenya["answer"]
    assert tariffs.visitor_class({"passport": "Germany"})[0] == "non_resident"
    assert tariffs.visitor_class({"visitor_class": "resident"})[0] == "eac_citizen"


def test_group_estimate_counts_children_by_age(assistant):
    result = assistant.ask(
        "Plan a 3 day safari to Tarangire",
        as_of=TRAVEL,
        profile={"passport": "Germany", "adults": 2, "child_ages": [7, 3]},
    )
    estimate = next(item for item in result["blocks"] if item["type"] == "estimate")
    # 2 adults x 3 days x 127,750 + 1 child x 3 days x 38,325; the 3-year-old is free.
    assert estimate["total_tzs"] == 2 * 3 * 127750 + 3 * 38325
    assert any(item["type"] == "visa" for item in result["blocks"])
    assert result["recommended_parks"][0]["slug"] == "tarangire"


def test_species_come_from_the_official_park_text(assistant):
    result = assistant.ask("Can I see elephants in Mikumi?", as_of=TRAVEL)
    assert result["abstained"] is False
    assert "elephants" in result["answer"]
    assert result["citations"][0]["source_url"].endswith("/mikumi")


def test_unlisted_species_abstains(assistant):
    result = assistant.ask("Can I see penguins in Mikumi?", as_of=TRAVEL)
    assert result["intent"] in {"wildlife", "general"}
    assert result["abstained"] is True


def test_ngorongoro_points_to_ncaa(assistant):
    result = assistant.ask("How much is Ngorongoro crater entry?", as_of=TRAVEL)
    assert result["abstained"] is True
    assert "NCAA" in result["answer"]
    assert result["fees"] == []


def test_helicopter_price_is_not_confirmed(assistant):
    result = assistant.ask("Can I get a helicopter from Serengeti to Mafia Island for TSh 850,000 tomorrow?", as_of=TRAVEL)
    assert result["abstained"] is True
    assert "850" not in result["answer"]


def test_swahili_cost_question_answers_in_swahili(assistant):
    result = assistant.ask("Nataka kwenda Mikumi kwa siku tatu. Nipe makadirio ya gharama.", as_of=TRAVEL, profile={"adults": 2})
    assert result["language"] == "sw"
    assert result["understood"]["days"] == 3
    assert "Makadirio" in result["answer"]
    assert next(item for item in result["blocks"] if item["type"] == "estimate")["total_tzs"] == 2 * 3 * 76650


def test_park_fact_uses_the_gis_map(assistant):
    result = assistant.ask("How big is Ruaha National Park?", as_of=TRAVEL)
    assert "20,300" in result["answer"]
    assert any(citation["source_url"].endswith("TNPMapENG.pdf") for citation in result["citations"])


def test_fee_overview_without_a_park_lists_every_park(assistant):
    result = assistant.ask("What are park entry fees?", as_of=TRAVEL)
    assert "Serengeti National Park" in result["answer"]
    assert "Mikumi National Park" in result["answer"]


def test_greeting_is_short_and_uncited(assistant):
    result = assistant.ask("habari", as_of=TRAVEL)
    assert result["citations"] == []
    assert result["language"] == "sw"


def test_follow_up_reuses_the_park_from_the_conversation(assistant):
    assistant.ask("nahitaji kwenda serengeti", as_of=TRAVEL, session_id="trip")
    result = assistant.ask("how much is camping?", as_of=TRAVEL, session_id="trip")
    assert result["understood"]["park_slugs"] == ["serengeti"]


def test_sessions_do_not_share_memory():
    memory = SessionMemory()
    memory.remember("a", "go to serengeti", "ok")
    assert memory.history("b") == []
    assert memory.history("a")[0]["content"] == "go to serengeti"


def test_grounding_check_flags_numbers_no_tool_returned():
    assistant = build_assistant()
    tools = Toolbox(assistant.store, assistant.index, assistant.settings, TRAVEL, {})
    tools.call("get_fees", {"park": "serengeti"})
    assert ungrounded_numbers("Adults pay TZS 178,850 (≈ USD 70) [1].", tools, "fees?") == []
    assert ungrounded_numbers("Adults pay TZS 200,000.", tools, "fees?") == ["200,000"]


def test_dar_short_trip_prefers_mikumi(assistant):
    result = assistant.ask("3 days wildlife, not beaches", as_of=TRAVEL, profile={"origin": "Dar es Salaam"})
    assert result["recommended_parks"][0]["slug"] == "mikumi"


def test_metric_definitions():
    retrieved, relevant = ["a", "b", "c", "d"], ["b", "d"]
    assert recall_at_k(retrieved, relevant, 3) == 0.5
    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert ndcg_at_k(retrieved, relevant, 4) > 0
    assert abs(f1_at_k(retrieved, relevant, 4) - (2 / 3)) < 1e-9


def test_evaluation_file(assistant):
    report = evaluate(assistant, load_questions(), as_of=TRAVEL)
    failures = [row for row in report["rows"] if row["abstain_ok"] is False or row.get("contains_ok") is False]
    assert failures == []
    assert report["mean_park_recall"] == 1
    assert report["citation_rate"] == 1
