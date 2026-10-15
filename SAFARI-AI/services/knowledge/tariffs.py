"""Official TANAPA fee rows: lookup by park, visitor class, age and date, and a trip estimate.

Only rows whose validity window covers the travel date are returned. Amounts are the
official TZS figures; the USD figure is an approximation at `tzs_per_usd` and is labelled so.
"""

from __future__ import annotations

from datetime import date

from services.common.text import parse_date
from services.sources.tanapa_api import AGE_LABELS, TARIFF_PAGE, VISITOR_LABELS

EAC_COUNTRIES = {
    "tanzania", "kenya", "uganda", "rwanda", "burundi", "south sudan",
    "democratic republic of the congo", "drc", "dr congo", "congo", "somalia",
}
ENTRANCE = "Entrance"
PERSON_VISITORS = ("non_resident", "expatriate", "eac_citizen")
CLASS_ALIASES = {
    "non_resident": "non_resident",
    "expatriate": "expatriate",
    "eac_citizen": "eac_citizen",
    "eac": "eac_citizen",
    "resident": "eac_citizen",
    "citizen": "eac_citizen",
}


def visitor_class(profile: dict | None) -> tuple[str, str]:
    """The fee class to use, and why. Explicit choice > passport > the non-resident default."""
    profile = profile or {}
    explicit = CLASS_ALIASES.get(str(profile.get("visitor_class") or "").strip().lower())
    if explicit:
        return explicit, "chosen in trip details"
    passport = str(profile.get("passport") or "").strip().lower()
    if passport:
        if passport in EAC_COUNTRIES:
            return "eac_citizen", f"{profile.get('passport')} passport (East African Community)"
        return "non_resident", f"{profile.get('passport')} passport"
    return "non_resident", "no passport given, so non-resident rates are shown"


def in_force_rows(store, park_slug: str, as_of: date, *, categories: tuple[str, ...] | None = None, visitors: tuple[str, ...] | None = None) -> list[dict]:
    rows = []
    for record in store.list_records("tariff"):
        row = record.payload
        if row["park_slug"] != park_slug:
            continue
        if categories and row["category"] not in categories:
            continue
        if visitors and row["visitor"] not in visitors and row["visitor"] != "any":
            continue
        start, end = parse_date(row.get("valid_from")), parse_date(row.get("valid_until"))
        if (start and as_of < start) or (end and as_of > end):
            continue
        rows.append(row)
    return sorted(rows, key=_order)


def categories_for(store, park_slug: str) -> list[str]:
    return sorted({record.payload["category"] for record in store.list_records("tariff") if record.payload["park_slug"] == park_slug})


def has_tariffs(store) -> bool:
    return bool(store.list_records("tariff"))


def fee_block(store, park_slug: str, park_name: str, as_of: date, tzs_per_usd: float, *, categories: tuple[str, ...] = (ENTRANCE,), visitors: tuple[str, ...] | None = None) -> dict | None:
    rows = in_force_rows(store, park_slug, as_of, categories=categories, visitors=visitors)
    if not rows:
        return None
    windows = sorted({(row.get("valid_from"), row.get("valid_until")) for row in rows})
    return {
        "type": "fees",
        "park_slug": park_slug,
        "park_name": park_name,
        "as_of": as_of.isoformat(),
        "valid_from": min(start for start, _end in windows if start) if any(start for start, _end in windows) else None,
        "valid_until": max(end for _start, end in windows if end) if any(end for _start, end in windows) else None,
        "in_force": True,
        "rows": [_block_row(row, tzs_per_usd) for row in rows],
        "notes": fee_notes(store),
        "source_url": TARIFF_PAGE,
    }


def fee_notes(store, limit: int = 4) -> list[str]:
    notes = [record.payload["text"] for record in store.list_records("fee_note") if record.payload.get("kind") == "note"]
    order = ("Children under 5", "Child rates", "valid for 24", "VAT")
    notes.sort(key=lambda text: next((index for index, key in enumerate(order) if key.lower() in text.lower()), 99))
    return notes[:limit]


def fee_faq(store) -> list[dict]:
    return [record.payload for record in store.list_records("fee_note") if record.payload.get("kind") == "faq"]


def estimate(store, park_slug: str, park_name: str, as_of: date, tzs_per_usd: float, *, days: int, adults: int, child_ages: list[int], visitor: str) -> dict | None:
    """Conservation (entrance) fees for the party. Everything else is listed as excluded."""
    rows = in_force_rows(store, park_slug, as_of, categories=(ENTRANCE,), visitors=(visitor,))
    adult_row = next((row for row in rows if row["age"] == "adult" and row["visitor"] == visitor), None)
    child_row = next((row for row in rows if row["age"] == "child_5_15" and row["visitor"] == visitor), None)
    if adult_row is None:
        return None
    days = max(1, int(days or 1))
    children = [age for age in child_ages if 5 <= age <= 15]
    infants = [age for age in child_ages if age < 5]
    older = [age for age in child_ages if age > 15]
    lines = []
    adult_count = max(0, int(adults or 0)) + len(older)
    if adult_count:
        lines.append(_line(f"{adult_row['item']} · {VISITOR_LABELS[visitor]}", adult_count, days, adult_row["amount"]))
    if children and child_row:
        lines.append(_line(f"{child_row['item']} · {VISITOR_LABELS[visitor]}", len(children), days, child_row["amount"]))
    if infants:
        lines.append({"label": "Children under 5", "qty": len(infants), "days": days, "unit_tzs": 0, "total_tzs": 0})
    if not lines:
        return None
    total = sum(line["total_tzs"] for line in lines)
    return {
        "type": "estimate",
        "park_slug": park_slug,
        "park_name": park_name,
        "as_of": as_of.isoformat(),
        "days": days,
        "visitor": visitor,
        "visitor_label": VISITOR_LABELS[visitor],
        "lines": lines,
        "total_tzs": total,
        "total_usd": round(total / tzs_per_usd, 2) if tzs_per_usd else None,
        "valid_from": adult_row.get("valid_from"),
        "valid_until": adult_row.get("valid_until"),
        "excludes": [
            "Vehicle entry (charged per vehicle by weight and registration)",
            "Accommodation or camping",
            "Guide, ranger and activity fees",
            "Transport, food and tour operator costs",
        ],
        "source_url": TARIFF_PAGE,
    }


def _line(label: str, qty: int, days: int, unit: float) -> dict:
    return {"label": label, "qty": qty, "days": days, "unit_tzs": unit, "total_tzs": unit * qty * days}


def _block_row(row: dict, tzs_per_usd: float) -> dict:
    return {
        "category": row["category"],
        "item": row["item"],
        "visitor": row["visitor"],
        "visitor_label": row["visitor_label"],
        "age": row["age"],
        "age_label": AGE_LABELS.get(row["age"], ""),
        "season": row["season"],
        "valid_from": row.get("valid_from"),
        "valid_until": row.get("valid_until"),
        "unit": row.get("unit"),
        "amount_tzs": row["amount"],
        "amount_usd": round(row["amount"] / tzs_per_usd, 2) if tzs_per_usd and row["currency"] == "TZS" else None,
    }


def _order(row: dict) -> tuple:
    visitor_rank = {"non_resident": 0, "expatriate": 1, "eac_citizen": 2, "foreign_vehicle": 3, "local_vehicle": 4, "any": 5}
    age_rank = {"adult": 0, "child_5_15": 1, "student": 2, "any": 3}
    return (row["category"], visitor_rank.get(row["visitor"], 9), age_rank.get(row["age"], 9), row["item"])
