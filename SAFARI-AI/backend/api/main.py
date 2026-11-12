"""SafariAI HTTP API."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import queue
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.admin import log_harvest, router as admin_router, views, warm
from api.security import login_router
from services.analytics.events import Analytics
from services.common.settings import ROOT, load_settings
from services.common.typography import clean
from services.engine import build_assistant
from services.knowledge import parks as park_knowledge
from services.knowledge import tariffs
from services.logistics.budget import STAY, TRANSPORT, TripRequest
from services.logistics.places import origin_names
from services.planning.briefing import build_briefing
from services.planning.pdf_brief import render_briefing_pdf

log = logging.getLogger("safari.api")
# The frontend is its own app (../frontend). When its build is present the API serves it too,
# so one process is enough locally; in Docker the frontend container serves it instead.
DIST_DIR = Path(os.environ.get("SAFARI_WEB_DIST") or ROOT.parent / "frontend" / "dist")


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


class TripBudgetRequest(BaseModel):
    park: str = Field(min_length=1, max_length=80)
    origin: str = Field(min_length=2, max_length=80)
    days: int = Field(ge=1, le=30)
    adults: int = Field(ge=1, le=40)
    child_ages: list[int] = Field(default_factory=list, max_length=20)
    passport: str = ""
    visitor_class: str = ""
    transport: str = Field(default="self_drive", pattern="^(self_drive|bus)$")
    stay: str = Field(default="hotel", pattern="^(hotel|camping|none)$")
    currency: str | None = Field(default=None, pattern="^[A-Za-z]{3}$")
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
            started = time.perf_counter()
            report = await asyncio.to_thread(refresh_api, assistant.store, assistant.embedder)
            log_harvest(assistant.store, "api", "schedule", started, report)
        logistics_status = {item["id"]: item for item in assistant.store.source_status()}.get("ewura_fuel", {})
        if _age_hours(logistics_status.get("last_attempt")) >= 24:
            log.info("refreshing logistics data (exchange rate, fuel prices, hotel list)")
            try:
                await asyncio.to_thread(assistant.logistics.refresh)
            except Exception:
                log.exception("logistics refresh failed")
        await asyncio.sleep(min(3600, hours * 3600 / 4))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    views.clear()
    app.state.assistant = build_assistant(settings)
    app.state.analytics = Analytics(settings.data_dir, app.state.assistant.store)
    app.state.limiter = RateLimiter()
    task = None
    if settings.refresh_hours > 0 and "PYTEST_CURRENT_TEST" not in os.environ:
        task = asyncio.create_task(_refresh_loop(app, settings.refresh_hours))
    if "PYTEST_CURRENT_TEST" not in os.environ:
        threading.Thread(target=warm, args=(app,), name="warm-dashboard", daemon=True).start()
    yield
    if task:
        task.cancel()


class CleanJSONResponse(JSONResponse):
    """Every JSON answer passes the house style (no em or en dashes) on its way out, whatever produced
    the text: our copy, indexed TANAPA documents, or the LLM."""

    def render(self, content) -> bytes:
        return super().render(clean(content))


app = FastAPI(
    title="SafariAI Tanzania",
    default_response_class=CleanJSONResponse,
    summary="Visitor agent for Tanzania National Parks: official fees, parks, visas, with citations.",
    version="2.0.0",
    lifespan=lifespan,
)
# JSON for the dashboard (fee tables, document lists) shrinks 5-10x. Streams (text/event-stream) are left alone.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Behind a proxy (the Cloudflare Pages function), SAFARI_PROXY_SECRET makes the API answer only
# requests that came through it, so the X-Forwarded-For used for rate limits can be trusted.
# /v1/health stays open for the host's health checks.
PROXY_SECRET = os.environ.get("SAFARI_PROXY_SECRET", "")


@app.middleware("http")
async def require_proxy_secret(request: Request, call_next):
    path = request.url.path
    if PROXY_SECRET and path.startswith("/v1/") and path != "/v1/health":
        sent = request.headers.get("x-proxy-secret", "")
        if not hmac.compare_digest(sent.encode(), PROXY_SECRET.encode()):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)


app.include_router(login_router)
app.include_router(admin_router)
if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
if (DIST_DIR / "brand").is_dir():
    app.mount("/brand", StaticFiles(directory=DIST_DIR / "brand"), name="brand")


# Visitor endpoints --------------------------------------------------------


@app.post("/v1/ask")
def ask(body: AskRequest, request: Request) -> dict:
    _limit(request)
    return _ask(body, channel="json")


@app.post("/v1/ask/stream")
def ask_stream(body: AskRequest, request: Request) -> StreamingResponse:
    _limit(request)
    events: queue.Queue = queue.Queue()

    def emit(event: str, data: dict) -> None:
        events.put((event, data))

    def work() -> None:
        try:
            events.put(("final", _ask(body, emit, channel="stream")))
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
            yield f"event: {event}\ndata: {json.dumps(clean(data), ensure_ascii=False)}\n\n"

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
    card["fees"] = tariffs.fee_block(store, slug, card["name"], as_of or date.today(), settings.tzs_per_usd, fx=app.state.assistant.logistics.fx)
    card["fee_categories"] = tariffs.categories_for(store, slug)
    return card


@app.get("/v1/fees")
def fees(park: str, category: str = "Entrance", as_of: date | None = None) -> dict:
    store = app.state.assistant.store
    card = park_knowledge.get_card(store, park)
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown park")
    block = tariffs.fee_block(store, park, card["name"], as_of or date.today(), app.state.assistant.settings.tzs_per_usd, categories=(category,), fx=app.state.assistant.logistics.fx)
    if block is None:
        raise HTTPException(status_code=404, detail=f"No {category} fee in force on that date")
    return block


@app.post("/v1/trip-budget")
def trip_budget(body: TripBudgetRequest, request: Request) -> dict:
    """Whole-trip budget from a Tanzanian town: live hotel rates and exchange rate, official fees, fuel
    and bus fares, labelled by source. Rate limited like /v1/ask because it calls outside services."""
    _limit(request)
    assistant = app.state.assistant
    store = assistant.store
    from services.sources.tanapa_api import match_park

    card = park_knowledge.get_card(store, match_park(body.park, store.list_parks()) or body.park.lower())
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown park")
    visitor, _reason = tariffs.visitor_class({"passport": body.passport, "visitor_class": body.visitor_class})
    block = assistant.logistics.budget(
        TripRequest(
            park_slug=card["slug"],
            park_name=card["name"],
            origin=body.origin,
            travel_date=body.as_of or date.today(),
            days=body.days,
            adults=body.adults,
            child_ages=[age for age in body.child_ages if 0 <= age <= 17],
            visitor=visitor,
            transport=body.transport,
            stay=body.stay,
            currency=body.currency,
        )
    )
    if block.get("error"):
        raise HTTPException(status_code=422, detail=block)
    return block


@app.get("/v1/trip-budget/options")
def trip_budget_options() -> dict:
    return {"origins": origin_names(), "transport": list(TRANSPORT), "stay": list(STAY)}


@app.get("/v1/fx")
def exchange_rates(amount: float = 1.0, source: str = "USD", target: str = "TZS") -> dict:
    """Today's Bank of Tanzania rate, e.g. /v1/fx?amount=100&source=EUR&target=TZS."""
    result = app.state.assistant.logistics.fx.convert(amount, source, target)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result)
    return result


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
        content=render_briefing_pdf(clean(payload)),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=safari-briefing.pdf"},
    )


@app.post("/v1/feedback")
def feedback(body: FeedbackRequest) -> dict:
    app.state.analytics.record_feedback(body.model_dump())
    return {"ok": True}


# Status and sources ---------------------------------------------------------


def _counts() -> dict:
    """Index sizes for health and status, counted in the database and cached per data version."""
    store = app.state.assistant.store

    def build() -> dict:
        stats = store.chunk_stats()
        return {
            "documents": len(store.list_documents(summary=True)),
            "chunks": sum(chunks for chunks, _ in stats.values()),
            "parks": len(store.list_parks()),
            "tariff_rows": store.count_records("tariff"),
            "sources": store.source_status(),
        }

    return views.get(("counts", store.version), build)


# HEAD too: uptime monitors such as UptimeRobot check with HEAD requests by default.
@app.api_route("/v1/health", methods=["GET", "HEAD"])
def health() -> dict:
    counts = _counts()
    return {"status": "ok", "documents": counts["documents"], "parks": counts["parks"], "store": app.state.assistant.settings.store}


@app.get("/v1/status")
def status() -> dict:
    assistant = app.state.assistant
    return {
        "status": "ok",
        **_counts(),
        "store": assistant.settings.store,
        "llm_enabled": assistant.settings.llm_enabled,
        "llm_model": assistant.settings.llm_model if assistant.settings.llm_enabled else None,
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
        for document in app.state.assistant.store.list_documents(summary=True)
    ]


@app.get("/v1/sources")
def sources() -> list[dict]:
    registry = ROOT / "knowledge" / "sources" / "registry.json"
    return json.loads(registry.read_text(encoding="utf-8"))


# Web app ---------------------------------------------------------------------


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("v1/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    built = DIST_DIR / "index.html"
    if not built.exists():
        return JSONResponse({"service": "SafariAI API", "docs": "/docs", "frontend": "Run the frontend app (frontend/) or build it with `npm run build`."})
    asset = DIST_DIR / path
    if path and asset.is_file() and DIST_DIR.resolve() in asset.resolve().parents:
        return FileResponse(asset)
    return FileResponse(built)


# Helpers -----------------------------------------------------------------------


def _ask(body: AskRequest, emit=None, channel: str = "json") -> dict:
    profile = dict(body.profile or {})
    if body.language and not profile.get("language"):
        profile["language"] = body.language
    started = time.perf_counter()
    result, error = None, None
    try:
        result = app.state.assistant.ask(
            body.question,
            as_of=body.as_of,
            profile=profile,
            session_id=body.session_id,
            language=body.language,
            emit=emit,
        )
        return result
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        raise
    finally:
        try:
            app.state.analytics.record_question(
                question=body.question,
                session_id=body.session_id,
                profile=profile,
                result=result,
                latency_ms=(time.perf_counter() - started) * 1000,
                channel=channel,
                error=error,
            )
        except Exception:  # analytics never breaks an answer
            log.exception("could not record question event")


def _limit(request: Request) -> None:
    key = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "local")
    if not app.state.limiter.allow(key):
        raise HTTPException(status_code=429, detail="Too many questions in a minute. Please wait a moment.")


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
