"""Admin API behind the dashboard: insights, the question log, feedback review, data and site management."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import json
import platform
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.security import auth_required, login_enabled, require_admin
from services.analytics import insights
from services.analytics.events import JsonDoc, open_lines
from services.common.memo import Memo
from services.common.settings import load_settings
from services.common.text import parse_date

UPLOAD_TYPES = {".pdf", ".txt", ".md"}
MAX_UPLOAD_BYTES = 25_000_000
STARTED_AT = datetime.now(timezone.utc)
CSV_FIELDS = ["at", "question", "intent", "language", "parks", "recommended", "generator", "abstained", "confidence_label", "citations", "latency_ms", "passport", "visitor_class", "days", "adults", "children", "channel", "error"]

router = APIRouter(dependencies=[Depends(require_admin)])
log = logging.getLogger("safari.admin")

# Dashboard views are computed once per data version and served from memory until the store or the
# analytics change (or `ttl` passes). Keys carry those versions, so a write never shows stale numbers.
views = Memo(ttl=300, size=96)


class ReviewRequest(BaseModel):
    status: Literal["open", "reviewed", "resolved", "dismissed"]
    note: str = Field(default="", max_length=1000)


def _assistant(request: Request):
    return request.app.state.assistant


def _analytics(request: Request):
    return request.app.state.analytics


def _park_names(store) -> dict[str, str]:
    return {park.slug: park.name for park in store.list_parks()}


def harvest_log(store):
    return open_lines(load_settings().data_dir, store, "harvests")


def log_harvest(store, kind: str, trigger: str, started: float, report: dict) -> None:
    api = report.get("api", report)
    harvest_log(store).append(
        {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            "trigger": trigger,
            "status": api.get("status", "unknown"),
            "error": api.get("error"),
            "tariff_rows": api.get("tariff_rows"),
            "parks": api.get("parks"),
            "documents": (report.get("totals") or {}).get("documents"),
            "duration_s": round(time.perf_counter() - started, 1),
        }
    )


# Overview and insights ---------------------------------------------------------------


@router.get("/v1/admin/session")
def session(request: Request) -> dict:
    settings = _assistant(request).settings
    return {"ok": True, "token_required": auth_required(settings), "username": settings.admin_username if login_enabled(settings) else None}


def cached_inventory(assistant, as_of: date | None = None) -> dict:
    day = as_of or date.today()
    return views.get(
        ("inventory", assistant.store.version, day.isoformat()),
        lambda: insights.inventory(assistant.store, assistant.settings.tzs_per_usd, day),
    )


def _build_overview(assistant, analytics, days: int) -> dict:
    store = assistant.store
    stats = insights.overview(analytics, _park_names(store), days)
    stock = cached_inventory(assistant)
    stats["alerts"] = insights.alerts(store, assistant.settings, stats, stock)
    stats["inventory_totals"] = stock["totals"]
    stats["tariff_windows"] = stock["tariff_windows"]
    stats["sources"] = store.source_status()
    stats["llm_enabled"] = assistant.settings.llm_enabled
    return stats


def overview_view(assistant, analytics, days: int, fresh: bool = False) -> dict:
    """The overview for `days`, served stale-while-revalidate: a new question or harvest never makes the
    dashboard wait. `fresh` recomputes before answering (the Refresh button)."""
    key = ("overview", days)
    version = (analytics.version, assistant.store.version)
    compute = lambda: _build_overview(assistant, analytics, days)  # noqa: E731
    if fresh:
        return views.refresh(key, version, compute)
    return views.serve(key, version, compute, max_age=60)


@router.get("/v1/admin/overview")
def overview(request: Request, days: int = Query(30, ge=1, le=365), fresh: bool = False) -> dict:
    return overview_view(_assistant(request), _analytics(request), days, fresh)


def warm(app) -> None:
    """Fill the dashboard caches after start, so the first admin visit doesn't wait for them."""
    assistant, analytics = app.state.assistant, app.state.analytics
    started = time.perf_counter()
    try:
        cached_inventory(assistant)
        overview_view(assistant, analytics, 30)
        _fee_table(assistant)
        views.get(("documents", assistant.store.version), lambda: _document_rows(assistant.store))
        for days in (7, 90):  # the other common periods, after the default is ready
            overview_view(assistant, analytics, days)
        log.info("dashboard caches warm in %.1fs", time.perf_counter() - started)
    except Exception:
        log.exception("warming dashboard caches failed")


@router.get("/v1/admin/questions")
def questions(
    request: Request,
    days: int | None = Query(None, ge=1, le=365),
    q: str = "",
    intent: str = "",
    park: str = "",
    outcome: str = "",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    return insights.question_log(_analytics(request), days=days, q=q, intent=intent, park=park, outcome=outcome, limit=limit, offset=offset)


@router.get("/v1/admin/questions.csv")
def questions_csv(request: Request, days: int | None = Query(None, ge=1, le=365)) -> Response:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in _analytics(request).questions(days):
        writer.writerow({**row, "parks": " ".join(row.get("parks") or []), "recommended": " ".join(row.get("recommended") or [])})
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=safari-questions-{date.today().isoformat()}.csv"},
    )


# Feedback ---------------------------------------------------------------------------


@router.get("/v1/admin/feedback")
def feedback(
    request: Request,
    status: str = "",
    rating: int | None = Query(None, ge=-1, le=1),
    days: int | None = Query(None, ge=1, le=365),
    limit: int = Query(25, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    items = _analytics(request).feedback_items(days)
    counts = {
        "total": len(items),
        "positive": sum(1 for item in items if item["rating"] == 1),
        "negative": sum(1 for item in items if item["rating"] == -1),
        "open": sum(1 for item in items if item["review_status"] == "open"),
    }
    if status:
        items = [item for item in items if item["review_status"] == status]
    if rating is not None:
        items = [item for item in items if item["rating"] == rating]
    newest_first = list(reversed(items))
    return {"counts": counts, "total": len(newest_first), "items": newest_first[offset : offset + limit]}


@router.post("/v1/admin/feedback/{feedback_id}")
def review_feedback(feedback_id: str, body: ReviewRequest, request: Request) -> dict:
    analytics = _analytics(request)
    if not any(item["id"] == feedback_id for item in analytics.feedback_items()):
        raise HTTPException(status_code=404, detail="Unknown feedback item")
    return analytics.set_review(feedback_id, status=body.status, note=body.note)


# Data from the TANAPA site --------------------------------------------------------------


@router.get("/v1/admin/inventory")
def inventory(request: Request, as_of: date | None = None) -> dict:
    return cached_inventory(_assistant(request), as_of)


def _fee_table(assistant) -> dict:
    """Every tariff row with its validity state and USD estimate, plus the filter options. Cached per data version."""

    def build() -> dict:
        today = date.today()
        rate = assistant.settings.tzs_per_usd
        rows = []
        for record in assistant.store.list_records("tariff"):
            row = record.payload
            start, end = parse_date(row.get("valid_from")), parse_date(row.get("valid_until"))
            row_state = "upcoming" if start and start > today else "expired" if end and end < today else "in_force"
            usd = round(float(row.get("amount") or 0) / rate, 2) if row.get("currency") == "TZS" else None
            rows.append({**row, "state": row_state, "usd": usd, "_text": f"{row.get('product', '')} {row.get('item', '')} {row.get('park_name', '')}".lower()})
        rows.sort(key=lambda row: (row.get("park_name") or "", row.get("category") or "", row.get("item") or "", row.get("visitor") or "", row.get("valid_from") or ""))
        return {
            "rows": rows,
            "categories": sorted({row.get("category") for row in rows if row.get("category")}),
            "visitors": sorted({row.get("visitor") for row in rows if row.get("visitor")}),
        }

    return views.get(("fees", assistant.store.version, date.today().isoformat()), build)


@router.get("/v1/admin/fees")
def fee_rows(
    request: Request,
    park: str = "",
    category: str = "",
    visitor: str = "",
    state: Literal["", "in_force", "upcoming", "expired"] = "",
    q: str = "",
    limit: int = Query(50, ge=1, le=3000),
    offset: int = Query(0, ge=0),
) -> dict:
    assistant = _assistant(request)
    table = _fee_table(assistant)
    needle = q.strip().lower()
    rows = [
        row
        for row in table["rows"]
        if (not park or row.get("park_slug") == park)
        and (not category or row.get("category") == category)
        and (not visitor or row.get("visitor") == visitor)
        and (not state or row["state"] == state)
        and (not needle or needle in row["_text"])
    ]
    return {
        "total": len(rows),
        "offset": offset,
        "rows": [{key: value for key, value in row.items() if key != "_text"} for row in rows[offset : offset + limit]],
        "categories": table["categories"],
        "visitors": table["visitors"],
        "tzs_per_usd": assistant.settings.tzs_per_usd,
    }


# Documents ------------------------------------------------------------------------------------


@router.get("/v1/admin/documents")
def documents(request: Request) -> list[dict]:
    store = _assistant(request).store
    return views.get(("documents", store.version), lambda: _document_rows(store))


def _document_rows(store) -> list[dict]:
    stats = store.chunk_stats()
    return [
        {
            "document_id": document.document_id,
            "title": document.title,
            "organization": document.organization,
            "document_type": document.document_type,
            "language": document.language,
            "authority": document.authority,
            "authority_score": document.authority_score,
            "status": document.status,
            "effective_from": document.effective_from,
            "effective_until": document.effective_until,
            "retrieved_at": document.retrieved_at,
            "source_url": document.source_url,
            "park_slug": document.park_slug,
            "version": document.version,
            "chunks": stats.get(document.document_id, (0, 0))[0],
            "characters": stats.get(document.document_id, (0, 0))[1],
        }
        for document in store.list_documents(summary=True)
    ]


@router.delete("/v1/admin/documents/{document_id}")
def delete_document(document_id: str, request: Request) -> dict:
    store = _assistant(request).store
    document = store.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Unknown document")
    store.delete_document(document_id)
    return {"ok": True, "message": f"Removed {document.title} from the index."}


@router.post("/v1/documents")
async def upload_document(request: Request, file: UploadFile = File(...), metadata: str = Form("{}")) -> dict:
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
    assistant = _assistant(request)
    document = await asyncio.to_thread(ingest_file, assistant.store, destination, extra, assistant.embedder)
    return {
        "document_id": document.document_id,
        "title": document.title,
        "document_type": document.document_type,
        "authority": document.authority,
        "status": document.status,
    }


# Sources -------------------------------------------------------------------------------------


@router.post("/v1/admin/harvest")
async def admin_harvest(request: Request, full: bool = False) -> dict:
    from services.sources.harvest import harvest, refresh_api

    assistant = _assistant(request)
    started = time.perf_counter()
    if full:
        report = await asyncio.to_thread(harvest, assistant.store, assistant.embedder)
    else:
        report = await asyncio.to_thread(refresh_api, assistant.store, assistant.embedder)
    log_harvest(assistant.store, "full" if full else "api", "admin", started, report)
    api = report.get("api", report)
    message = (
        f"Synced {api.get('tariff_rows', 0)} fee rows and {api.get('parks', 0)} park profiles from TANAPA."
        if api.get("status") == "ok"
        else f"Refresh failed: {api.get('error', 'unknown error')}"
    )
    return {"message": message, "report": report}


@router.get("/v1/admin/harvests")
def harvests(request: Request, limit: int = Query(30, ge=1, le=500)) -> list[dict]:
    return list(reversed(harvest_log(_assistant(request).store).read()))[:limit]


# Evaluation and system ------------------------------------------------------------------------


def _evaluation_doc(request: Request) -> JsonDoc:
    return JsonDoc(load_settings().data_dir, _assistant(request).store, "evaluation_last")


@router.post("/v1/evaluate")
async def run_evaluation(request: Request) -> dict:
    from services.evaluation.runner import evaluate, load_questions

    result = await asyncio.to_thread(evaluate, _assistant(request), load_questions(), None, False)
    result["ran_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _evaluation_doc(request).save(result)
    return result


@router.get("/v1/admin/evaluation")
def last_evaluation(request: Request) -> dict:
    return _evaluation_doc(request).load()


@router.get("/v1/admin/system")
def system(request: Request) -> dict:
    assistant = _assistant(request)
    settings = assistant.settings
    analytics = _analytics(request)
    data_files = []
    if settings.data_dir.exists():
        for path in sorted(settings.data_dir.rglob("*")):
            if path.is_file():
                data_files.append({"path": str(path.relative_to(settings.data_dir)), "bytes": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return {
        "version": request.app.version,
        "python": platform.python_version(),
        "started_at": STARTED_AT.isoformat(timespec="seconds"),
        "uptime_s": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
        "store": settings.store,
        "data_dir": str(settings.data_dir),
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.llm_model if settings.llm_enabled else None,
        "llm_base_url": settings.llm_base_url or None,
        "refresh_hours": settings.refresh_hours,
        "tzs_per_usd": settings.tzs_per_usd,
        "admin_token_set": bool(settings.admin_token),
        "admin_login_set": login_enabled(settings),
        "rate_limit": {"limit": request.app.state.limiter.limit, "window_s": request.app.state.limiter.window},
        "sessions_in_memory": len(assistant.memory._sessions),
        "event_log_bytes": analytics.events.size_bytes(),
        "data_files": data_files,
    }
