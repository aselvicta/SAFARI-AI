"""Assemble a park-visit briefing from the indexed documents."""

from __future__ import annotations

import re
from datetime import date

from services.common.embeddings import HashEmbedder
from services.common.settings import load_settings
from services.common.store import JsonStore
from services.conversation.understand import understand
from services.knowledge import tariffs
from services.planning.entry import entry_lines, plan_rows
from services.retrieval.planner import shortlist

TARIFF_URL = "https://www.tanzaniaparks.go.tz/tourism/visitor-information/tariff"

_INSIDE = (
    "tanzania",
    "dar es salaam",
    "dar",
    "arusha",
    "mwanza",
    "dodoma",
    "mbeya",
    "moshi",
    "tanga",
    "morogoro",
    "iringa",
    "zanzibar",
    "ndani",
    "nchini",
)


def build_briefing(
    store: JsonStore,
    *,
    question: str = "",
    origin: str = "",
    park_slugs: list[str] | None = None,
    days: int | None = None,
    adults: int | None = None,
    children: int = 0,
    child_ages: list[int] | None = None,
    passport: str = "",
    visitor_class: str = "",
    as_of: date | None = None,
    embedder: HashEmbedder | None = None,
) -> dict:
    settings = load_settings()
    question_date = as_of or date.today()
    parks = store.list_parks()
    ages = [age for age in (child_ages or []) if isinstance(age, int) and 0 <= age <= 17]
    profile = {"origin": origin, "days": days, "adults": adults, "child_ages": ages, "passport": passport, "visitor_class": visitor_class}
    query = understand(question or "plan a visit to a Tanzania national park", parks, profile=profile)
    requested = list(park_slugs or []) or list(query.park_slugs)
    selected = [park for park in parks if park.slug in requested]
    named = bool(selected)
    if not selected:
        selected = [park for park, _reason in shortlist(parks, query, limit=3)]
    location = starting_place(origin)
    visitor, visitor_reason = tariffs.visitor_class(profile)
    rows = []
    estimates = []
    for park in selected:
        block = tariffs.fee_block(store, park.slug, park.name, question_date, settings.tzs_per_usd, visitors=(visitor,))
        if block:
            rows.extend({**row, "park_slug": park.slug, "park_name": park.name} for row in block["rows"])
        trip_days = days or query.days
        if trip_days and (adults or ages):
            estimate = tariffs.estimate(store, park.slug, park.name, question_date, settings.tzs_per_usd, days=trip_days, adults=adults or 0, child_ages=ages, visitor=visitor)
            if estimate:
                estimates.append(estimate)
    windows = sorted({(row["valid_from"], row["valid_until"]) for row in rows})
    entry = entry_lines(passport, location)
    plan = plan_rows()
    return {
        "as_of": question_date.isoformat(),
        "language": query.language,
        "origin": origin,
        "location": location,
        "days": days or query.days,
        "adults": adults,
        "children": len(ages) if ages else max(0, children),
        "child_ages": ages,
        "passport": passport,
        "visitor": tariffs.VISITOR_LABELS[visitor],
        "visitor_reason": visitor_reason,
        "named_parks": named,
        "parks": [
            {
                "slug": park.slug,
                "name": park.name,
                "area_km2": park.area_km2,
                "circuit": park.circuit,
                "established_year": park.established_year,
            }
            for park in selected
        ],
        "entry": entry,
        "plan": plan,
        "passages": [],
        "tariff": {
            "title": "TANAPA park fees and tariffs 2026/27" if rows else "",
            "effective_from": windows[0][0] if windows else None,
            "effective_until": windows[-1][1] if windows else None,
            "source_url": TARIFF_URL,
            "in_force": bool(rows),
            "rows": rows,
            "notes": tariffs.fee_notes(store),
        },
        "estimates": estimates,
        "summary": _receipt_text(entry, plan),
    }


def _receipt_text(entry: list[dict], plan: list[dict]) -> str:
    return "\n".join(f"{row['label']}: {row['value']}" for row in [*entry, *plan])


def starting_place(origin: str) -> str:
    cleaned = (origin or "").strip().lower()
    if not cleaned:
        return "unspecified"
    if any(re.search(rf"\b{re.escape(place)}\b", cleaned) for place in _INSIDE):
        return "inside"
    return "outside"
