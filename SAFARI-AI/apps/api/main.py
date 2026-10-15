"""SafariAI HTTP API."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from services.common.settings import ROOT, load_settings
from services.engine import build_assistant
from services.knowledge import parks as park_knowledge
from services.knowledge import tariffs
from services.planning.briefing import build_briefing
from services.planning.pdf_brief import render_briefing_pdf

log = logging.getLogger("safari.api")
WEB_DIR = ROOT / "apps" / "web"
DIST_DIR = WEB_DIR / "dist"
UPLOAD_TYPES = {".pdf", ".txt", ".md"}
MAX_UPLOAD_BYTES = 25_000_000


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=80)
    as_of: date | None = None
    language: str | None = Field(default=None, pattern="^(en|sw)$")
    profile: dict = Field(default_factory=dict)


class BriefingRequest(BaseModel):
    question: str = ""
    origin: str = ""
    parks: list[str] = Field(default_factory=list)
    days: int | None = Field(default=None, ge=1, le=60)
    adults: int | None = Field(default=None, ge=0, le=60)
    children: int = 0
    child_ages: list[int] = Field(default_factory=list)
    passport: str = ""
    visitor_class: str = ""
    as_of: date | None = None


class FeedbackRequest(BaseModel):
    session_id: str | None = None
    question: str = Field(default="", max_length=2000)
    answer: str = Field(default="", max_length=8000)
    rating: int = Field(ge=-1, le=1)
    comment: str = Field(default="", max_length=2000)


class RateLimiter:
    """Sliding-window limit per client, so one caller cannot run up the LLM bill."""

    def __init__(self, limit: int = 30, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            hits = self.hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


async def _refresh_loop(app: FastAPI, hours: float) -> None:
    from services.sources.harvest import refresh_api

    while True:
        assistant = app.state.assistant
        status = {item["id"]: item for item in assistant.store.source_status()}.get("tanapa_api", {})
        if _age_hours(status.get("last_success")) >= hours:
            log.info("refreshing TANAPA API data")
            await asyncio.to_thread(refresh_api, assistant.store, assistant.embedder)
        await asyncio.sleep(min(3600, hours * 3600 / 4))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.assistant = build_assistant(settings)
    app.state.limiter = RateLimiter()
    task = None
    if settings.refresh_hours > 0 and "PYTEST_CURRENT_TEST" not in __import__("os").environ:
        task = asyncio.create_task(_refresh_loop(app, settings.refresh_hours))
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="SafariAI Tanzania",
    summary="Visitor agent for Tanzania National Parks: official fees, parks, visas, with citations.",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
if (DIST_DIR / "brand").is_dir():
    app.mount("/brand", StaticFiles(directory=DIST_DIR / "brand"), name="brand")
elif (WEB_DIR / "public" / "brand").is_dir():
    app.mount("/brand", StaticFiles(directory=WEB_DIR / "public" / "brand"), name="brand")


# Visitor endpoints --------------------------------------------------------


@app.post("/v1/ask")
def ask(body: AskRequest, request: Request) -> dict:
    _limit(request)
    return _ask(body)


@app.post("/v1/ask/stream")
def ask_stream(body: AskRequest, request: Request) -> StreamingResponse:
    _limit(request)
    events: queue.Queue = queue.Queue()

    def emit(event: str, data: dict) -> None:
        events.put((event, data))

    def work() -> None:
        try:
            events.put(("final", _ask(body, emit)))
        except Exception as exc:  # the visitor sees a message, the log keeps the trace
            log.exception("ask failed")
            events.put(("error", {"message": "The desk could not answer just now. Please try again.", "detail": str(exc)[:200]}))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        yield ": open\n\n"
        while True:
            try:
                item = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                return
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/parks")
def parks() -> list[dict]:
    return [_public_card(card) for card in park_knowledge.cards(app.state.assistant.store)]


@app.get("/v1/parks/{slug}")
def park(slug: str, as_of: date | None = None) -> dict:
    store = app.state.assistant.store
    card = park_knowledge.get_card(store, slug)
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown park")
    settings = app.state.assistant.settings
    card["fees"] = tariffs.fee_block(store, slug, card["name"], as_of or date.today(), settings.tzs_per_usd)
    card["fee_categories"] = tariffs.categories_for(store, slug)
    return card


@app.get("/v1/fees")
def fees(park: str, category: str = "Entrance", as_of: date | None = None) -> dict:
    store = app.state.assistant.store
    card = park_knowledge.get_card(store, park)
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown park")
    block = tariffs.fee_block(store, park, card["name"], as_of or date.today(), app.state.assistant.settings.tzs_per_usd, categories=(category,))
    if block is None:
        raise HTTPException(status_code=404, detail=f"No {category} fee in force on that date")
    return block


@app.post("/v1/briefing")
def briefing(body: BriefingRequest, download: bool = False):
    assistant = app.state.assistant
    payload = build_briefing(
        assistant.store,
        question=body.question,
        origin=body.origin,
        park_slugs=body.parks,
        days=body.days,
        adults=body.adults,
        children=body.children,
        child_ages=body.child_ages,
        passport=body.passport,
        visitor_class=body.visitor_class,
        as_of=body.as_of,
        embedder=assistant.embedder,
    )
    if not download:
        return payload
    return Response(
        content=render_briefing_pdf(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=safari-briefing.pdf"},
    )


@app.post("/v1/feedback")
def feedback(body: FeedbackRequest) -> dict:
    path = load_settings().data_dir / "feedback.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), **body.model_dump()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


# Status and sources ---------------------------------------------------------


@app.get("/v1/health")
def health() -> dict:
    assistant = app.state.assistant
    return {
        "status": "ok",
        "documents": len(assistant.store.list_documents()),
        "parks": len(assistant.store.list_parks()),
        "store": assistant.settings.store,
    }


@app.get("/v1/status")
def status() -> dict:
    assistant = app.state.assistant
    store = assistant.store
    return {
        "status": "ok",
        "documents": len(store.list_documents()),
        "chunks": len(store.all_chunks()),
        "parks": len(store.list_parks()),
        "tariff_rows": len(store.list_records("tariff")),
        "store": assistant.settings.store,
        "llm_enabled": assistant.settings.llm_enabled,
        "llm_model": assistant.settings.llm_model if assistant.settings.llm_enabled else None,
        "sources": store.source_status(),
    }


@app.get("/v1/documents")
def documents() -> list[dict]:
    return [
        {
            "document_id": document.document_id,
            "title": document.title,
            "organization": document.organization,
            "document_type": document.document_type,
            "authority": document.authority,
            "authority_score": document.authority_score,
            "status": document.status,
            "effective_from": document.effective_from,
            "effective_until": document.effective_until,
            "retrieved_at": document.retrieved_at,
            "source_url": document.source_url,
            "park_slug": document.park_slug,
            "version": document.version,
        }
        for document in app.state.assistant.store.list_documents()
    ]


@app.get("/v1/sources")
def sources() -> list[dict]:
    registry = ROOT / "knowledge" / "sources" / "registry.json"
    return json.loads(registry.read_text(encoding="utf-8"))


# Admin -----------------------------------------------------------------------


@app.post("/v1/admin/harvest")
async def admin_harvest(request: Request, full: bool = False, x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(request, x_admin_token)
    from services.sources.harvest import harvest, refresh_api

    assistant = app.state.assistant
    if full:
        report = await asyncio.to_thread(harvest, assistant.store, assistant.embedder)
    else:
        report = await asyncio.to_thread(refresh_api, assistant.store, assistant.embedder)
    api = report.get("api", report)
    message = (
        f"Synced {api.get('tariff_rows', 0)} fee rows and {api.get('parks', 0)} park profiles from TANAPA."
        if api.get("status") == "ok"
        else f"Refresh failed: {api.get('error', 'unknown error')}"
    )
    return {"message": message, "report": report}


@app.post("/v1/documents")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin(request, x_admin_token)
    from services.ingestion.pipeline import ingest_file

    try:
        extra = json.loads(metadata or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="metadata must be JSON") from exc
    filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", Path(file.filename or "upload.txt").name)[:120]
    if Path(filename).suffix.lower() not in UPLOAD_TYPES:
        raise HTTPException(status_code=400, detail="Upload a PDF, .txt or .md file")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB")
    destination_dir = load_settings().data_dir / "uploads"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / filename
    destination.write_bytes(content)
    document = await asyncio.to_thread(ingest_file, app.state.assistant.store, destination, extra, app.state.assistant.embedder)
    return {
        "document_id": document.document_id,
        "title": document.title,
        "document_type": document.document_type,
        "authority": document.authority,
        "status": document.status,
    }


@app.post("/v1/evaluate")
def run_evaluation(request: Request, x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(request, x_admin_token)
    from services.evaluation.runner import evaluate, load_questions

    return evaluate(app.state.assistant, load_questions(), use_llm=False)


# Web app ---------------------------------------------------------------------


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("v1/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    asset = DIST_DIR / path
    if path and asset.is_file() and DIST_DIR in asset.resolve().parents:
        return FileResponse(asset)
    built = DIST_DIR / "index.html"
    return FileResponse(built if built.exists() else WEB_DIR / "index.html")


# Helpers -----------------------------------------------------------------------


def _ask(body: AskRequest, emit=None) -> dict:
    profile = dict(body.profile or {})
    if body.language and not profile.get("language"):
        profile["language"] = body.language
    return app.state.assistant.ask(
        body.question,
        as_of=body.as_of,
        profile=profile,
        session_id=body.session_id,
        language=body.language,
        emit=emit,
    )


def _limit(request: Request) -> None:
    key = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "local")
    if not app.state.limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many questions in a minute. Please wait a moment.")


def _require_admin(request: Request, token: str | None) -> None:
    """With SAFARI_ADMIN_TOKEN set, the header must match. Without it, only this machine may call."""
    expected = load_settings().admin_token
    if expected:
        if token != expected:
            raise HTTPException(status_code=401, detail="Admin token required")
        return
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=401, detail="Set SAFARI_ADMIN_TOKEN to use admin endpoints remotely")


def _public_card(card: dict) -> dict:
    return {key: value for key, value in card.items() if key != "about"}


def _age_hours(stamp: str | None) -> float:
    if not stamp:
        return float("inf")
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return float("inf")
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600
