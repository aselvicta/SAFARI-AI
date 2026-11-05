"""Ask pipeline: understand -> agent (LLM + tools) or composer (tools only) -> payload."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date

from services.agent.composer import compose
from services.agent.followups import follow_ups
from services.agent.runner import Ungrounded, run_agent
from services.agent.tools import Toolbox
from services.catalog import seed_catalog
from services.common.embeddings import HashEmbedder
from services.common.scoring import HybridWeights, confidence_label
from services.common.settings import Settings, load_settings
from services.common.store import JsonStore
from services.conversation.memory import SessionMemory
from services.conversation.understand import understand
from services.generation.llm import LLMError
from services.retrieval.index import HybridIndex

log = logging.getLogger("safari.engine")
Emit = Callable[[str, dict], None]

_GREETING = re.compile(
    r"^(hey|hi|hello|habari|habari yako|mambo|karibu|niaje|yo|good (morning|afternoon|evening)|hujambo|shikamoo|jambo)[!.?,\s]*$",
    re.IGNORECASE,
)


class Assistant:
    def __init__(self, store: JsonStore, embedder: HashEmbedder | None = None, weights: HybridWeights | None = None, settings: Settings | None = None) -> None:
        self.store = store
        self.embedder = embedder or HashEmbedder()
        self.weights = weights or HybridWeights()
        self.settings = settings or load_settings()
        self.index = HybridIndex(store, self.embedder, self.weights)
        self.memory = SessionMemory()

    def ask(
        self,
        question: str,
        *,
        as_of: date | None = None,
        profile: dict | None = None,
        session_id: str | None = None,
        language: str | None = None,
        emit: Emit | None = None,
        use_llm: bool | None = None,
    ) -> dict:
        emit = emit or (lambda _event, _data: None)
        question = question.strip()
        question_date = as_of or date.today()
        profile = _clean_profile(profile)
        history = self.memory.history(session_id)
        if _GREETING.match(question):
            result = _greeting(question, question_date, language)
            self.memory.remember(session_id, question, result["answer"])
            return result
        query = understand(question, self.store.list_parks(), profile=profile, history=history)
        if language in {"en", "sw"} and query.language == "en" and language == "sw":
            query.language = "sw"
        tools = Toolbox(self.store, self.index, self.settings, question_date, profile)
        llm = self.settings.llm_enabled if use_llm is None else use_llm
        generator = "composer"
        answer = None
        status = "answered"
        if llm:
            try:
                answer, status = run_agent(question, history, tools, self.settings, query.language, emit)
                generator = "agent"
            except (LLMError, Ungrounded) as exc:
                log.warning("agent fell back to composer: %s", exc)
                emit("reset", {})
                tools = Toolbox(self.store, self.index, self.settings, question_date, profile)
        if answer is None:
            emit("status", {"label": "Checking official sources"})
            composed = compose(query, tools)
            answer = composed["answer"]
            abstained = composed["abstained"]
            limits = composed["limits"]
        else:
            abstained = status != "answered"
            limits = [] if status == "answered" else [status]
        confidence = 0.9 if tools.structured_hit else max(0.24, min(0.85, tools.best_retrieval)) if not abstained else 0.28
        if abstained:
            confidence = min(confidence, 0.32)
        park_name = next((item["name"] for item in tools.recommended), None)
        if park_name is None and query.park_slugs:
            park_name = next((park.name for park in self.store.list_parks() if park.slug == query.park_slugs[0]), None)
        result = {
            "answer": answer,
            "language": query.language,
            "intent": query.intent,
            "abstained": abstained,
            "confidence": round(confidence, 4),
            "confidence_label": confidence_label(confidence),
            "generator": generator,
            "citations": _referenced(answer, tools.citations),
            "blocks": tools.blocks,
            "recommended_parks": tools.recommended,
            "follow_ups": follow_ups(query.intent, park_name, query.language, abstained),
            "limits": limits,
            "tool_calls": [call["name"] for call in tools.calls],
            "understood": query.to_dict(),
            "as_of": question_date.isoformat(),
            # v1 field, kept for API clients that read it.
            "fees": [row for block in tools.blocks if block["type"] == "fees" for row in block["rows"]],
            "outside_scope": [{"name": name} for name in query.scope_hits],
        }
        self.memory.remember(session_id, question, answer)
        return result


def _referenced(answer: str, citations: list[dict]) -> list[dict]:
    """Only the sources the answer actually cites; all of them if it cites none."""
    used = {int(number) for number in re.findall(r"\[(\d{1,2})\]", answer)}
    kept = [citation for citation in citations if citation["n"] in used]
    return kept or citations


def _clean_profile(profile: dict | None) -> dict:
    profile = dict(profile or {})
    cleaned: dict = {}
    for key in ("passport", "origin", "visitor_class", "language"):
        value = str(profile.get(key) or "").strip()
        if value:
            cleaned[key] = value[:80]
    for key in ("days", "adults"):
        try:
            value = int(profile.get(key)) if profile.get(key) not in (None, "") else None
        except (TypeError, ValueError):
            value = None
        if value is not None and 0 <= value <= 60:
            cleaned[key] = value
    ages = []
    for age in profile.get("child_ages") or []:
        try:
            age = int(age)
        except (TypeError, ValueError):
            continue
        if 0 <= age <= 17:
            ages.append(age)
    if ages:
        cleaned["child_ages"] = ages
    return cleaned


def _greeting(question: str, question_date: date, language: str | None) -> dict:
    swahili = language == "sw" or bool(re.match(r"^(habari|mambo|karibu|niaje|hujambo|shikamoo|jambo)", question.strip(), re.IGNORECASE))
    answer = (
        "Karibu! Mimi ni SafariAI, dawati la wageni la hifadhi za taifa za Tanzania. Niambie hifadhi unayotaka, siku ngapi, na mnasafiri wangapi — nitakupa ada rasmi za TANAPA, wanyama, malazi na viza."
        if swahili
        else "Karibu! I'm SafariAI, the visitor desk for Tanzania's national parks. Tell me where you'd like to go, for how many days and who's travelling, and I'll give you official TANAPA fees, wildlife, places to stay and visa rules."
    )
    return {
        "answer": answer,
        "language": "sw" if swahili else "en",
        "intent": "greeting",
        "abstained": False,
        "confidence": 0.5,
        "confidence_label": "MEDIUM",
        "generator": "composer",
        "citations": [],
        "blocks": [],
        "recommended_parks": [],
        "follow_ups": follow_ups("default", None, "sw" if swahili else "en", False),
        "limits": [],
        "tool_calls": [],
        "understood": {},
        "as_of": question_date.isoformat(),
        "fees": [],
        "outside_scope": [],
    }


def open_store(settings: Settings | None = None) -> JsonStore:
    chosen = settings or load_settings()
    if chosen.store == "postgres":
        from services.common.postgres_store import PostgresStore

        return PostgresStore(chosen.database_url)
    return JsonStore(chosen.data_dir / "knowledge.json")


def build_assistant(settings: Settings | None = None) -> Assistant:
    chosen = settings or load_settings()
    store = open_store(chosen)
    assistant = Assistant(store, settings=chosen)
    with store.batch():
        seed_catalog(store, assistant.embedder, chosen.root)
    return assistant
