"""TANAPA website API (Strapi) connector.

The public site at tanzaniaparks.go.tz is a Next.js app that renders from a Strapi API.
Reading the API gives structured, current rows (2026/27 tariffs, park profiles, contacts)
instead of the navigation text a crawler sees in the rendered HTML.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.common.models import Park, Record
from services.sources.http import Http

ORIGIN = "https://tanzaniaparks.go.tz"
SITE = "https://www.tanzaniaparks.go.tz"
API = f"{ORIGIN}/api"
TARIFF_PAGE = f"{SITE}/tourism/visitor-information/tariff"
ACTIVITIES_PAGE = f"{SITE}/tourism/activities"
ACCOMMODATION_PAGE = f"{SITE}/tourism/visitor-information/accommodation"
SOURCE_ID = "tanapa_api"

VISITOR_CODES = {
    "NR": "non_resident",
    "R": "eac_citizen",
    "EX": "expatriate",
    "L": "local_vehicle",
    "F": "foreign_vehicle",
}
VISITOR_LABELS = {
    "non_resident": "Non-resident (NR)",
    "eac_citizen": "East African citizen (R)",
    "expatriate": "Expatriate / permit holder (EX)",
    "local_vehicle": "Tanzania-registered vehicle",
    "foreign_vehicle": "Foreign-registered vehicle",
    "any": "Everyone",
}
AGE_LABELS = {
    "adult": "16 years and above",
    "child_5_15": "Children 5–15",
    "student": "Students",
    "any": "",
}
_CODE_TAIL = re.compile(r"\s*\(\s*(?:NR|R|EX|L|F)\s*\)\s*", re.IGNORECASE)


@dataclass
class ApiSnapshot:
    """Everything one harvest read from the API, kept raw for audit and offline tests."""

    retrieved_at: str
    collections: dict[str, list[dict]] = field(default_factory=dict)
    tariff_notes: list[str] = field(default_factory=list)
    tariff_faq: list[dict] = field(default_factory=list)


# Fetch ------------------------------------------------------------------


COLLECTIONS = {
    "tariff-items": {},
    "web-national-parks": {"populate": "*"},
    "activities": {"populate": "*"},
    "attractions": {"populate": "*"},
    "accommodation-options": {"populate": "*"},
    "park-contacts": {"populate": "*"},
    "web-publications": {"populate": "*"},
}


def fetch_snapshot(http: Http) -> ApiSnapshot:
    snapshot = ApiSnapshot(retrieved_at=_now())
    for name, params in COLLECTIONS.items():
        snapshot.collections[name] = fetch_collection(http, name, params)
    snapshot.tariff_notes, snapshot.tariff_faq = fetch_tariff_page_text(http)
    return snapshot


def fetch_collection(http: Http, name: str, params: dict | None = None, page_size: int = 500) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while True:
        payload = http.json(
            f"{API}/{name}",
            {**(params or {}), "pagination[page]": page, "pagination[pageSize]": page_size},
        )
        data = payload.get("data") or []
        rows.extend(_attributes(item) | {"id": item.get("id")} for item in data if isinstance(item, dict))
        pagination = (payload.get("meta") or {}).get("pagination") or {}
        if page >= int(pagination.get("pageCount") or 1) or not data:
            return rows
        page += 1


def fetch_tariff_page_text(http: Http) -> tuple[list[str], list[dict]]:
    """Fee notes and FAQ printed on the tariff page. They ship inside the page's JS bundle."""
    try:
        html = http.get(TARIFF_PAGE).text
        match = re.search(r'src="(/_next/static/chunks/pages/tourism/visitor-information/tariff-[^"]+\.js)"', html)
        if not match:
            return [], []
        bundle = http.get(SITE + match.group(1)).text
    except Exception:
        return [], []
    return parse_tariff_bundle(bundle)


def parse_tariff_bundle(bundle: str) -> tuple[list[str], list[dict]]:
    faq = [
        {"question": _unescape(question), "answer": _unescape(answer)}
        for question, answer in re.findall(r'question:"((?:[^"\\]|\\.)+)",answer:"((?:[^"\\]|\\.)+)"', bundle)
    ]
    notes: list[str] = []
    anchor = bundle.find("Children under 5 years of age enter FREE")
    if anchor != -1:
        start = bundle.rfind("[", 0, anchor)
        end = bundle.find("]", anchor)
        if start != -1 and end != -1:
            notes = [_unescape(item) for item in re.findall(r'"((?:[^"\\]|\\.)+)"', bundle[start:end])]
    return notes, faq


# Normalize --------------------------------------------------------------


def tariff_records(snapshot: ApiSnapshot, parks: list[Park]) -> list[Record]:
    records = []
    for row in snapshot.collections.get("tariff-items", []):
        parsed = parse_tariff_row(row, parks)
        if parsed is None:
            continue
        records.append(_record("tariff", str(row.get("id")), parsed, TARIFF_PAGE, snapshot.retrieved_at))
    return records


def parse_tariff_row(row: dict, parks: list[Park]) -> dict | None:
    product = re.sub(r"\s+", " ", str(row.get("ProductName") or "")).strip()
    park_name = str(row.get("Park") or "").strip()
    slug = match_park(park_name, parks)
    if not product or slug is None or row.get("Amount") is None:
        return None
    code_match = re.search(r"\(\s*(NR|R|EX|L|F)\s*\)", product, re.IGNORECASE) or re.search(
        r"\((NR|EX)\)\s*-", product, re.IGNORECASE
    )
    visitor = VISITOR_CODES.get(code_match.group(1).upper(), "any") if code_match else "any"
    lowered = product.lower()
    if "child" in lowered:
        age = "child_5_15"
    elif "student" in lowered or "school" in lowered or "college" in lowered or "educational" in lowered:
        age = "student"
    elif "adult" in lowered:
        age = "adult"
    else:
        age = "any"
    season_raw = str(row.get("Season") or "ALL").upper()
    season = "high" if "HIGH" in season_raw else "low" if "LOW" in season_raw else "all"
    category = str(row.get("Category") or "Other").strip()
    return {
        "id": row.get("id"),
        "park_slug": slug,
        "park_name": park_name,
        "category": category,
        "product": product,
        "item": _item_label(product),
        "visitor": visitor,
        "visitor_label": VISITOR_LABELS[visitor],
        "age": age,
        "season": season,
        "season_label": season_raw.title(),
        "currency": str(row.get("Currency") or "TZS").upper(),
        "amount": float(row["Amount"]),
        "valid_from": row.get("FromDate"),
        "valid_until": row.get("ToDate"),
        "revenue_code": row.get("RevenueCode"),
        "unit": "per person per 24 hours" if category == "Entrance" else None,
    }


def park_profile_records(snapshot: ApiSnapshot, parks: list[Park]) -> list[Record]:
    contacts = {}
    for row in snapshot.collections.get("park-contacts", []):
        linked = _attributes(((row.get("national_parks_and_antiquity") or {}).get("data")) or {})
        slug = match_park(str(linked.get("ParkName") or linked.get("slug") or ""), parks)
        if slug:
            contacts[slug] = {
                "phone": [item.get("number") for item in row.get("phone") or [] if item.get("number")],
                "email": [item.get("email") for item in row.get("email") or [] if item.get("email")],
                "address": (row.get("address") or "").strip(),
                "hours": row.get("hours"),
            }
    attractions: dict[str, list[str]] = {}
    for row in snapshot.collections.get("attractions", []):
        for linked in row.get("parks") or []:
            slug = match_park(str((linked or {}).get("ParkName") or (linked or {}).get("slug") or ""), parks)
            if slug:
                attractions.setdefault(slug, []).append(str(row.get("attractionName") or "").strip())
    records = []
    for row in snapshot.collections.get("web-national-parks", []):
        if str(row.get("Type") or "National Park") != "National Park":
            continue
        slug = match_park(str(row.get("ParkName") or ""), parks)
        if slug is None:
            continue
        about = blocks_to_text(row.get("AboutPark"))
        payload = {
            "slug": slug,
            "name": str(row.get("ParkName") or "").strip(),
            "site_slug": row.get("slug"),
            "zone": _clean(row.get("Zone")).replace("Northen", "Northern"),
            "slogan": _clean(row.get("slogan")),
            "area_km2_site": _number(row.get("AreaSize")),
            "temperature_c": _clean(row.get("Temperature")),
            "elevation_m": _clean(row.get("Elevation")),
            "about": about,
            "summary": _first_sentences(about, 2),
            "image_url": image_url(row.get("image")),
            "page_url": f"{SITE}/{row.get('slug') or slug}",
            "contact": contacts.get(slug, {}),
            "attractions": attractions.get(slug, []),
            "updated_at": row.get("updatedAt"),
        }
        records.append(_record("park_profile", slug, payload, payload["page_url"], snapshot.retrieved_at))
    return records


def activity_records(snapshot: ApiSnapshot) -> list[Record]:
    records = []
    for row in snapshot.collections.get("activities", []):
        if row.get("isActive") is False:
            continue
        title = _clean(row.get("title"))
        if not title:
            continue
        payload = {
            "title": title,
            "overview": _clean(row.get("Overview") if isinstance(row.get("Overview"), str) else blocks_to_text(row.get("Overview"))),
            "faq": [
                {"question": _clean(item.get("question")), "answer": _clean(item.get("answer"))}
                for item in row.get("FAQ") or []
                if item.get("question") and item.get("answer")
            ],
            "gear": [_clean(item.get("name")) for item in row.get("gears") or [] if item.get("name")],
            "guidelines": [_clean(item.get("item")) for item in row.get("guidelines") or [] if item.get("item")],
            "image_url": image_url(row.get("MainImage")),
        }
        records.append(_record("activity", _slug(title), payload, ACTIVITIES_PAGE, snapshot.retrieved_at))
    return records


def accommodation_records(snapshot: ApiSnapshot) -> list[Record]:
    records = []
    for row in snapshot.collections.get("accommodation-options", []):
        if row.get("isActive") is False:
            continue
        payload = {
            "title": _clean(row.get("title")).title(),
            "subtitle": _clean(row.get("subtitle")),
            "description": _clean(row.get("longDescription") or row.get("description")),
            "price_range": _clean(row.get("priceRange")),
            "best_for": row.get("bestFor") if isinstance(row.get("bestFor"), list) else _clean(row.get("bestFor")),
        }
        records.append(_record("accommodation", _slug(payload["title"]), payload, ACCOMMODATION_PAGE, snapshot.retrieved_at))
    return records


def fee_note_records(snapshot: ApiSnapshot) -> list[Record]:
    rows = [{"kind": "note", "text": note} for note in snapshot.tariff_notes]
    rows += [{"kind": "faq", "question": item["question"], "answer": item["answer"]} for item in snapshot.tariff_faq]
    return [_record("fee_note", str(index), row, TARIFF_PAGE, snapshot.retrieved_at) for index, row in enumerate(rows)]


def documents_from_snapshot(snapshot: ApiSnapshot, parks: list[Park]) -> list[tuple[str, dict]]:
    """Prose documents for retrieval, built from the same rows (text, metadata)."""
    docs: list[tuple[str, dict]] = []
    base = {
        "organization": "TANAPA",
        "authority": "official",
        "status": "current",
        "language": "en",
        "retrieved_at": snapshot.retrieved_at[:10],
    }
    for record in park_profile_records(snapshot, parks):
        park = record.payload
        lines = [park["about"]]
        facts = []
        if park["zone"]:
            facts.append(f"TANAPA zone: {park['zone']}.")
        if park["slogan"]:
            facts.append(f"Slogan: {park['slogan']}.")
        if park["temperature_c"]:
            facts.append(f"Temperature: {park['temperature_c']} °C.")
        if park["elevation_m"]:
            facts.append(f"Elevation: {park['elevation_m']} m.")
        if park["attractions"]:
            facts.append("Attractions: " + ", ".join(park["attractions"]) + ".")
        contact = park["contact"]
        if contact.get("phone") or contact.get("email"):
            facts.append(
                f"Contact {park['name']}: "
                + "; ".join(filter(None, [", ".join(contact.get("phone") or []), ", ".join(contact.get("email") or []), contact.get("address")]))
                + "."
            )
        if facts:
            lines.append(" ".join(facts))
        docs.append(
            (
                "\n\n".join(item for item in lines if item),
                {
                    **base,
                    "document_id": f"tanapa_live_park_{park['slug']}",
                    "title": f"{park['name']} — TANAPA park page",
                    "document_type": "park_guide",
                    "source_url": park["page_url"],
                    "park_slug": park["slug"],
                },
            )
        )
    for record in activity_records(snapshot):
        activity = record.payload
        parts = [f"{activity['title']}.", activity["overview"]]
        parts.extend(f"Q: {item['question']} A: {item['answer']}" for item in activity["faq"])
        if activity["gear"]:
            parts.append("What to bring: " + ", ".join(activity["gear"]) + ".")
        docs.append(
            (
                "\n\n".join(item for item in parts if item),
                {
                    **base,
                    "document_id": f"tanapa_activity_{record.key}",
                    "title": f"{activity['title']} — TANAPA activity",
                    "document_type": "activity",
                    "source_url": ACTIVITIES_PAGE,
                },
            )
        )
    attractions = snapshot.collections.get("attractions", [])
    if attractions:
        text = "\n\n".join(
            f"{_clean(row.get('attractionName'))}: {_clean(row.get('description'))}"
            for row in attractions
            if row.get("attractionName") and row.get("description")
        )
        docs.append(
            (
                text,
                {**base, "document_id": "tanapa_attractions", "title": "Attractions in Tanzania's national parks — TANAPA", "document_type": "attraction", "source_url": f"{SITE}/tourism"},
            )
        )
    accommodation = accommodation_records(snapshot)
    if accommodation:
        text = "\n\n".join(
            f"{item.payload['title']} ({item.payload['price_range']}): {item.payload['description']}" for item in accommodation
        )
        docs.append(
            (
                text,
                {**base, "document_id": "tanapa_accommodation", "title": "Accommodation types in national parks — TANAPA", "document_type": "accommodation", "source_url": ACCOMMODATION_PAGE},
            )
        )
    if snapshot.tariff_notes or snapshot.tariff_faq:
        parts = ["Park fee notes published on the TANAPA tariff page."]
        parts.extend(f"- {note}" for note in snapshot.tariff_notes)
        parts.extend(f"Q: {item['question']} A: {item['answer']}" for item in snapshot.tariff_faq)
        docs.append(
            (
                "\n\n".join(parts),
                {**base, "document_id": "tanapa_tariff_faq", "title": "Park fees: notes and FAQ — TANAPA", "document_type": "fee_guide", "source_url": TARIFF_PAGE},
            )
        )
    return docs


# Helpers ----------------------------------------------------------------


def match_park(name: str, parks: list[Park]) -> str | None:
    lowered = re.sub(r"[^a-z0-9 -]+", " ", (name or "").lower())
    if not lowered.strip() or "head office" in lowered:
        return None
    for park in parks:
        if lowered.strip() == park.slug or lowered.strip() == park.name.lower():
            return park.slug
    for park in parks:
        keys = [park.name.lower().replace(" national park", ""), *park.aliases, *park.strict_aliases, park.slug.replace("-", " ")]
        if any(re.search(rf"\b{re.escape(key.lower())}\b", lowered) for key in keys if key):
            return park.slug
    return None


def blocks_to_text(blocks) -> str:
    if blocks is None:
        return ""
    if isinstance(blocks, str):
        return _clean(blocks)
    paragraphs: list[str] = []

    def walk(node) -> str:
        if isinstance(node, dict):
            if "text" in node and not node.get("children"):
                return str(node.get("text") or "")
            return "".join(walk(child) for child in node.get("children") or [])
        if isinstance(node, list):
            return "".join(walk(child) for child in node)
        return ""

    for block in blocks if isinstance(blocks, list) else [blocks]:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "list":
            for item in block.get("children") or []:
                text = _clean(walk(item))
                if text:
                    paragraphs.append(f"- {text}")
            continue
        text = _clean(walk(block))
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


def image_url(media, size: str = "large") -> str | None:
    data = (media or {}).get("data") if isinstance(media, dict) else None
    if isinstance(data, list):
        data = data[0] if data else None
    attrs = _attributes(data or {})
    if not attrs:
        return None
    formats = attrs.get("formats") or {}
    chosen = (formats.get(size) or formats.get("medium") or {}).get("url") or attrs.get("url")
    if not chosen:
        return None
    return chosen if chosen.startswith("http") else ORIGIN + chosen


def _record(kind: str, key: str, payload: dict, url: str, retrieved_at: str) -> Record:
    return Record(kind=kind, key=key, payload=payload, source_id=SOURCE_ID, source_url=url, retrieved_at=retrieved_at)


def _item_label(product: str) -> str:
    label = _CODE_TAIL.sub(" ", product)
    label = re.sub(r"\((?:NR|EX|Ex)\)\s*-?", " ", label)
    return re.sub(r"\s+", " ", label).strip(" -")


def _attributes(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    return item.get("attributes") or item


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _number(value) -> float | None:
    text = re.sub(r"[^0-9.]", "", str(value or ""))
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _first_sentences(text: str, count: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n\n", " "))
    return " ".join(sentences[:count]).strip()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _unescape(value: str) -> str:
    try:
        return value.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return value.replace('\\"', '"')


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
