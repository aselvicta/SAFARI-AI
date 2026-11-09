"""Numbers for the admin dashboard: visitor demand, answer quality, data inventory and alerts."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median

from services.analytics.events import Analytics, parse_at
from services.common.text import parse_date
from services.generation import llm as llm_client
from services.knowledge import tariffs

EAT = timezone(timedelta(hours=3))  # Tanzania, no daylight saving
STALE_FACTOR = 2  # a source is stale after twice the refresh interval
TARIFF_WARNING_DAYS = 60
FALLBACK_ALERT_SHARE = 0.1  # warn when more than this share of answers did not come from the LLM
FALLBACK_LABELS = {
    "llm_off": "LLM not configured",
    "rate_limited": "Rate limited",
    "server_error": "Provider server error",
    "timeout": "Timed out",
    "network": "Network error",
    "auth": "Key rejected or no balance",
    "bad_request": "Request rejected",
    "empty": "Empty reply",
    "round_limit": "Too many tool rounds",
    "ungrounded_figures": "Unsupported figures",
    "ungrounded_citations": "No source cited",
}


# Demand and quality ------------------------------------------------------------


def overview(analytics: Analytics, park_names: dict[str, str], days: int = 30) -> dict:
    now = datetime.now(timezone.utc)
    events = analytics.questions(days * 2)
    start = now - timedelta(days=days)
    current = [row for row in events if (parse_at(row.get("at")) or now) >= start]
    previous = [row for row in events if (parse_at(row.get("at")) or now) < start]
    feedback = analytics.feedback_items(days)

    answered = [row for row in current if row.get("intent") not in {"greeting", "error"}]
    return {
        "days": days,
        "generated_at": now.isoformat(timespec="seconds"),
        "kpis": _kpis(current, previous, feedback),
        "series": _daily(current, start, days),
        "hours": _hours(current),
        "intents": _top(row.get("intent") for row in current),
        "parks": _top_parks(answered, "parks", park_names),
        "recommended": _top_parks(answered, "recommended", park_names),
        "languages": _top(row.get("language") for row in current),
        "generators": _top(row.get("generator") for row in current),
        "confidence": _top(row.get("confidence_label") for row in answered),
        "markets": _top(row["passport"].title() for row in current if row.get("passport")),
        "visitor_classes": _top(row.get("visitor_class") or "not set" for row in current),
        "fee_categories": _top(row.get("fee_category") for row in current),
        "animals": _top(row.get("animal") for row in current),
        "tools": _top(tool for row in current for tool in row.get("tools") or []),
        "out_of_scope": _top(name for row in current for name in row.get("scope") or []),
        "trip_length": _top(_days_bucket(row.get("days")) for row in current if row.get("days")),
        "group_size": _top(_group_bucket(row) for row in current if row.get("adults")),
        "gaps": knowledge_gaps(current),
        "top_questions": top_questions(answered),
        "latency": _latency(current),
        "weekday_hours": _weekday_hours(current),
        "outcomes": _outcomes(current),
        "trip_details": _trip_details(answered),
        "fallback_reasons": [
            {**item, "label": FALLBACK_LABELS.get(item["key"], item["key"])}
            for item in _top(row.get("fallback") for row in answered if row.get("fallback") != "not_requested")
        ],
        "llm_health": llm_client.health(),
    }


def _kpis(current: list[dict], previous: list[dict], feedback: list[dict]) -> dict:
    def summary(rows: list[dict]) -> dict:
        real = [row for row in rows if row.get("intent") not in {"greeting", "error"}]
        abstained = sum(1 for row in real if row.get("abstained"))
        latencies = [row["latency_ms"] for row in rows if isinstance(row.get("latency_ms"), (int, float))]
        confidences = [row["confidence"] for row in real if isinstance(row.get("confidence"), (int, float))]
        return {
            "questions": len(rows),
            "sessions": len({row.get("session") for row in rows if row.get("session")}),
            "answer_rate": (1 - abstained / len(real)) if real else None,
            "abstained": abstained,
            "errors": sum(1 for row in rows if row.get("error")),
            "agent_share": (sum(1 for row in real if row.get("generator") == "agent") / len(real)) if real else None,
            "median_latency_ms": median(latencies) if latencies else None,
            "mean_confidence": (sum(confidences) / len(confidences)) if confidences else None,
            "cited_share": (sum(1 for row in real if row.get("citations")) / len(real)) if real else None,
            # Answers the LLM should have written but the template composer did (older events have no field).
            "fallbacks": sum(1 for row in real if row.get("fallback") and row.get("fallback") != "not_requested"),
        }

    now, before = summary(current), summary(previous)
    rated = [item for item in feedback if item["rating"] in (1, -1)]
    positive = sum(1 for item in rated if item["rating"] == 1)
    now["feedback"] = len(feedback)
    now["satisfaction"] = (positive / len(rated)) if rated else None
    now["feedback_open"] = sum(1 for item in feedback if item["review_status"] == "open" and item["rating"] == -1)
    now["questions_per_session"] = (now["questions"] / now["sessions"]) if now["sessions"] else None
    return {"current": now, "previous": before}


def _daily(rows: list[dict], start: datetime, days: int) -> list[dict]:
    """One row per East Africa Time day. The first and last rows cover part of a day (`partial`):
    the window starts mid-day, and today is still in progress."""
    buckets: dict[str, dict] = {}
    first = start.astimezone(EAT).date()
    today = datetime.now(EAT).date()
    for offset in range(days + 1):
        day = first + timedelta(days=offset)
        if day > today:
            break
        buckets[day.isoformat()] = {"date": day.isoformat(), "questions": 0, "abstained": 0, "sessions": set(), "real": 0, "latencies": [], "partial": day in (first, today)}
    for row in rows:
        at = parse_at(row.get("at"))
        if at is None:
            continue
        bucket = buckets.get(at.astimezone(EAT).date().isoformat())
        if bucket is None:
            continue
        bucket["questions"] += 1
        bucket["abstained"] += int(bool(row.get("abstained")))
        if row.get("intent") not in {"greeting", "error"}:
            bucket["real"] += 1
        if isinstance(row.get("latency_ms"), (int, float)):
            bucket["latencies"].append(row["latency_ms"])
        if row.get("session"):
            bucket["sessions"].add(row["session"])
    series = []
    for bucket in buckets.values():
        real, latencies = bucket.pop("real"), bucket.pop("latencies")
        series.append(
            {
                **bucket,
                "sessions": len(bucket["sessions"]),
                "answer_rate": round(1 - bucket["abstained"] / real, 4) if real else None,
                "median_latency_ms": round(median(latencies), 1) if latencies else None,
            }
        )
    return series


def _weekday_hours(rows: list[dict]) -> list[list[int]]:
    """Questions by weekday (Monday first) and hour, East Africa Time: when the desk is busy."""
    grid = [[0] * 24 for _ in range(7)]
    for row in rows:
        at = parse_at(row.get("at"))
        if at:
            local = at.astimezone(EAT)
            grid[local.weekday()][local.hour] += 1
    return grid


def _outcomes(rows: list[dict]) -> list[dict]:
    """How each question ended, best to worst. Greetings are left out."""
    counts = {"answered": 0, "low_confidence": 0, "declined": 0, "failed": 0}
    for row in rows:
        if row.get("intent") == "greeting":
            continue
        if row.get("error"):
            counts["failed"] += 1
        elif row.get("abstained"):
            counts["declined"] += 1
        elif row.get("confidence_label") == "LOW":
            counts["low_confidence"] += 1
        else:
            counts["answered"] += 1
    return [{"key": key, "count": count} for key, count in counts.items()]


def _trip_details(rows: list[dict]) -> dict:
    """Share of questions that came with each trip detail: how much visitors tell the desk."""
    total = len(rows)

    def share(test) -> float | None:
        return round(sum(1 for row in rows if test(row)) / total, 4) if total else None

    return {
        "questions": total,
        "passport": share(lambda row: row.get("passport")),
        "days": share(lambda row: row.get("days")),
        "group": share(lambda row: row.get("adults")),
        "any": share(lambda row: row.get("passport") or row.get("days") or row.get("adults")),
    }


def top_questions(rows: list[dict], limit: int = 10) -> list[dict]:
    """The most repeated questions, grouped by wording."""
    groups: dict[str, dict] = {}
    for row in rows:
        key = _normalize(row.get("question") or "")
        if not key:
            continue
        group = groups.setdefault(key, {"question": row.get("question"), "count": 0, "intent": row.get("intent"), "answered": 0})
        group["count"] += 1
        group["answered"] += int(not row.get("abstained") and not row.get("error"))
    ranked = sorted(groups.values(), key=lambda item: item["count"], reverse=True)[:limit]
    return [{**item, "answer_rate": round(item["answered"] / item["count"], 4)} for item in ranked if item["count"] > 1]


def _hours(rows: list[dict]) -> list[int]:
    counts = [0] * 24
    for row in rows:
        at = parse_at(row.get("at"))
        if at:
            counts[at.astimezone(EAT).hour] += 1
    return counts


def _latency(rows: list[dict]) -> dict:
    values = sorted(row["latency_ms"] for row in rows if isinstance(row.get("latency_ms"), (int, float)))
    if not values:
        return {"p50": None, "p90": None, "p99": None, "max": None, "by_generator": {}}
    by_generator: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if isinstance(row.get("latency_ms"), (int, float)) and row.get("generator"):
            by_generator[row["generator"]].append(row["latency_ms"])
    return {
        "p50": _percentile(values, 0.5),
        "p90": _percentile(values, 0.9),
        "p99": _percentile(values, 0.99),
        "max": values[-1],
        "by_generator": {name: median(items) for name, items in by_generator.items()},
    }


def _percentile(values: list[float], share: float) -> float:
    index = min(len(values) - 1, max(0, round(share * (len(values) - 1))))
    return values[index]


def _top(values, limit: int = 12) -> list[dict]:
    counts = Counter(value for value in values if value)
    return [{"key": key, "count": count} for key, count in counts.most_common(limit)]


def _top_parks(rows: list[dict], field: str, names: dict[str, str], limit: int = 21) -> list[dict]:
    counts = Counter(slug for row in rows for slug in row.get(field) or [])
    return [{"key": slug, "label": names.get(slug, slug), "count": count} for slug, count in counts.most_common(limit)]


def _days_bucket(value) -> str:
    days = int(value)
    if days <= 2:
        return "1-2 days"
    if days <= 4:
        return "3-4 days"
    if days <= 7:
        return "5-7 days"
    return "8+ days"


def _group_bucket(row: dict) -> str:
    people = int(row.get("adults") or 0) + int(row.get("children") or 0)
    if people <= 1:
        return "Solo"
    if people == 2:
        return "Couple"
    if people <= 5:
        return "3-5 people"
    return "6+ people"


def _normalize(question: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", question.lower())).strip()


def knowledge_gaps(rows: list[dict], limit: int = 25) -> list[dict]:
    """Questions the desk declined or answered with low confidence, grouped by wording."""
    groups: dict[str, dict] = {}
    for row in rows:
        weak = row.get("abstained") or row.get("confidence_label") == "LOW" or row.get("error")
        if not weak or row.get("intent") == "greeting":
            continue
        key = _normalize(row.get("question") or "")
        if not key:
            continue
        group = groups.setdefault(key, {"question": row.get("question"), "count": 0, "last_at": row.get("at"), "intent": row.get("intent"), "abstained": 0, "errors": 0})
        group["count"] += 1
        group["abstained"] += int(bool(row.get("abstained")))
        group["errors"] += int(bool(row.get("error")))
        if (row.get("at") or "") > (group["last_at"] or ""):
            group["last_at"] = row.get("at")
            group["question"] = row.get("question")
    return sorted(groups.values(), key=lambda item: (item["count"], item["last_at"] or ""), reverse=True)[:limit]


def question_log(analytics: Analytics, *, days: int | None, q: str = "", intent: str = "", park: str = "", outcome: str = "", limit: int = 50, offset: int = 0) -> dict:
    rows = analytics.questions(days)
    needle = q.strip().lower()
    filtered = []
    for row in reversed(rows):
        if needle and needle not in (row.get("question") or "").lower():
            continue
        if intent and row.get("intent") != intent:
            continue
        if park and park not in (row.get("parks") or []) and park not in (row.get("recommended") or []):
            continue
        if outcome == "abstained" and not row.get("abstained"):
            continue
        if outcome == "answered" and (row.get("abstained") or row.get("error")):
            continue
        if outcome == "error" and not row.get("error"):
            continue
        if outcome == "low" and row.get("confidence_label") != "LOW":
            continue
        filtered.append(row)
    return {"total": len(filtered), "rows": filtered[offset : offset + limit]}


# Data from the TANAPA site --------------------------------------------------------


def inventory(store, tzs_per_usd: float, today: date | None = None) -> dict:
    today = today or date.today()
    tariff_rows = [record.payload for record in store.list_records("tariff")]
    profiles = {record.key: record.payload for record in store.list_records("park_profile")}
    activities = [record.payload for record in store.list_records("activity")]
    accommodation = [record.payload for record in store.list_records("accommodation")]
    documents = store.list_documents(summary=True)
    chunk_counts = {document_id: stats[0] for document_id, stats in store.chunk_stats().items()}
    sources = store.source_status()
    docs_by_park = Counter(document.park_slug for document in documents if document.park_slug)

    rows_by_park: dict[str, list[dict]] = defaultdict(list)
    for row in tariff_rows:
        rows_by_park[row.get("park_slug")].append(row)

    parks = []
    for park in store.list_parks():
        profile = profiles.get(park.slug) or {}
        rows = rows_by_park.get(park.slug, [])
        in_force = [row for row in rows if _covers(row, today)]
        entrance = [
            row["amount"] for row in in_force
            if row.get("category") == tariffs.ENTRANCE and row.get("visitor") == "non_resident" and row.get("age") == "adult"
        ]
        completeness = [bool(profile), bool(profile.get("image_url")), bool(profile.get("contact")), bool(profile.get("about")), bool(in_force)]
        parks.append(
            {
                "slug": park.slug,
                "name": park.name,
                "circuit": park.circuit,
                "zone": profile.get("zone") or "",
                "area_km2": park.area_km2,
                "established_year": park.established_year,
                "image_url": profile.get("image_url"),
                "page_url": profile.get("page_url"),
                "has_profile": bool(profile),
                "has_image": bool(profile.get("image_url")),
                "has_contact": bool(profile.get("contact")),
                "attractions": len(profile.get("attractions") or []),
                "tariff_rows": len(rows),
                "in_force_rows": len(in_force),
                "categories": len({row.get("category") for row in in_force}),
                "nr_adult_entrance_tzs": [min(entrance), max(entrance)] if entrance else None,
                "nr_adult_entrance_usd": [round(min(entrance) / tzs_per_usd, 2), round(max(entrance) / tzs_per_usd, 2)] if entrance else None,
                "documents": docs_by_park.get(park.slug, 0),
                "completeness": round(sum(completeness) / len(completeness), 2),
                "updated_at": profile.get("updated_at"),
            }
        )

    windows: dict[tuple, int] = Counter((row.get("valid_from"), row.get("valid_until")) for row in tariff_rows)
    tariff_windows = []
    for (start, end), count in sorted(windows.items(), key=lambda item: (item[0][0] or "", item[0][1] or "")):
        end_date = parse_date(end)
        start_date = parse_date(start)
        state = "upcoming" if start_date and start_date > today else "expired" if end_date and end_date < today else "in_force"
        tariff_windows.append(
            {
                "valid_from": start,
                "valid_until": end,
                "rows": count,
                "state": state,
                "days_left": (end_date - today).days if end_date and state == "in_force" else None,
            }
        )

    categories = Counter(row.get("category") for row in tariff_rows if _covers(row, today))
    visitors = Counter(row.get("visitor_label") or row.get("visitor") for row in tariff_rows if _covers(row, today))
    needs_ocr = next((item.get("needs_ocr") for item in sources if item.get("needs_ocr")), []) or []
    return {
        "as_of": today.isoformat(),
        "totals": {
            "parks": len(parks),
            "tariff_rows": len(tariff_rows),
            "tariff_rows_in_force": sum(categories.values()),
            "activities": len(activities),
            "accommodation": len(accommodation),
            "fee_notes": store.count_records("fee_note"),
            "documents": len(documents),
            "chunks": sum(chunk_counts.values()),
            "needs_ocr": len(needs_ocr),
        },
        "parks": parks,
        "tariff_windows": tariff_windows,
        "fee_categories": [{"key": key, "count": count} for key, count in categories.most_common()],
        "fee_visitors": [{"key": key, "count": count} for key, count in visitors.most_common()],
        "documents_by_type": _top((document.document_type for document in documents), 20),
        "documents_by_authority": _top((document.authority for document in documents), 20),
        "documents_by_org": _top((document.organization for document in documents), 20),
        "documents_by_status": _top((document.status for document in documents), 20),
        "needs_ocr": needs_ocr,
        "activities": [payload.get("title") for payload in activities],
        "accommodation": [{"title": payload.get("title"), "price_range": payload.get("price_range")} for payload in accommodation],
        "largest_documents": sorted(
            ({"document_id": document.document_id, "title": document.title, "chunks": chunk_counts.get(document.document_id, 0)} for document in documents),
            key=lambda item: -item["chunks"],
        )[:8],
    }


def _covers(row: dict, today: date) -> bool:
    start, end = parse_date(row.get("valid_from")), parse_date(row.get("valid_until"))
    return not ((start and today < start) or (end and today > end))


# Alerts ------------------------------------------------------------------------------


def alerts(store, settings, stats: dict, stock: dict) -> list[dict]:
    items: list[dict] = []
    now = datetime.now(timezone.utc)
    for source in store.source_status():
        name = source.get("name") or source.get("id")
        if source.get("status") == "error":
            api = source.get("id") == "tanapa_api"
            items.append({"level": "critical" if api else "warning", "title": f"{name} failed", "detail": source.get("error") or "No detail recorded.", "action": "harvest" if api else "sources"})
        last = parse_at(source.get("last_success"))
        if source.get("id") == "tanapa_api" and settings.refresh_hours and last and now - last > timedelta(hours=settings.refresh_hours * STALE_FACTOR):
            hours = int((now - last).total_seconds() // 3600)
            items.append({"level": "warning", "title": "TANAPA data is stale", "detail": f"Last successful sync {hours} hours ago; the schedule is every {settings.refresh_hours:g} hours.", "action": "harvest"})
    windows = stock.get("tariff_windows") or []
    if not any(window["state"] == "upcoming" for window in windows):
        ending = [window for window in windows if window["state"] == "in_force" and window["days_left"] is not None]
        soonest = min(ending, key=lambda window: window["days_left"], default=None)
        if soonest and soonest["days_left"] <= TARIFF_WARNING_DAYS:
            items.append({"level": "warning", "title": f"Tariff window ends in {soonest['days_left']} days", "detail": f"{soonest['rows']} fee rows are valid until {soonest['valid_until']} and no newer tariff has been published yet.", "action": "harvest"})
    if stock["totals"]["tariff_rows_in_force"] == 0:
        items.append({"level": "critical", "title": "No fee rows in force today", "detail": "Fee questions will be declined until a current tariff is harvested.", "action": "harvest"})
    if stock["totals"]["needs_ocr"]:
        items.append({"level": "info", "title": f"{stock['totals']['needs_ocr']} scanned PDFs are not indexed", "detail": "They have no text layer. Upload a text version to make them searchable.", "action": "documents"})
    incomplete = [park["name"] for park in stock["parks"] if park["completeness"] < 1]
    if incomplete:
        items.append({"level": "info", "title": f"{len(incomplete)} park profile{'s are' if len(incomplete) != 1 else ' is'} incomplete", "detail": ", ".join(incomplete[:6]) + ("…" if len(incomplete) > 6 else ""), "action": "parks"})
    current = stats["kpis"]["current"]
    if current["questions"] >= 10 and current["answer_rate"] is not None and current["answer_rate"] < 0.8:
        items.append({"level": "warning", "title": f"Answer rate is {current['answer_rate']:.0%}", "detail": "Visitors are asking questions the sources do not cover. Review the knowledge gaps.", "action": "insights"})
    if current["errors"]:
        items.append({"level": "warning", "title": f"{current['errors']} question{'s' if current['errors'] != 1 else ''} failed", "detail": "The desk raised an error while answering. Check the server log.", "action": "questions"})
    if current["feedback_open"]:
        items.append({"level": "info", "title": f"{current['feedback_open']} negative rating{'s' if current['feedback_open'] != 1 else ''} to review", "detail": "Visitors marked these answers unhelpful.", "action": "feedback"})
    if not settings.llm_enabled:
        items.append(
            {
                "level": "critical",
                "title": "DeepSeek is off",
                "detail": "Every answer comes from the template composer. Set DEEPSEEK_API_KEY on the server; the endpoint defaults to api.deepseek.com.",
                "action": "system",
            }
        )
    else:
        health = llm_client.health()
        if health["last_error_kind"] == "auth" and (health["last_error_at"] or "") > (health["last_ok_at"] or ""):
            items.append(
                {
                    "level": "critical",
                    "title": f"{settings.llm_provider} is rejecting requests",
                    "detail": "The API key was refused or the account has no balance, so answers fall back to the composer. " + (health["last_error"] or ""),
                    "action": "system",
                }
            )
        current = stats["kpis"]["current"]
        if current["questions"] >= 5 and current["fallbacks"] / current["questions"] > FALLBACK_ALERT_SHARE:
            reasons = ", ".join(f"{item['label'].lower()} ({item['count']})" for item in stats.get("fallback_reasons", [])[:3])
            items.append(
                {
                    "level": "warning",
                    "title": f"{settings.llm_provider} fell back on {current['fallbacks'] / current['questions']:.0%} of answers",
                    "detail": f"{current['fallbacks']} answers came from the template composer instead: {reasons or 'see System'}.",
                    "action": "insights",
                }
            )
    if not (settings.admin_token or (settings.admin_username and settings.admin_password)):
        items.append({"level": "info", "title": "No admin login set", "detail": "Admin is open to this machine only. Set SAFARI_ADMIN_USERNAME and SAFARI_ADMIN_PASSWORD before exposing the server.", "action": "system"})
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(items, key=lambda item: order[item["level"]])
