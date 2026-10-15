"""Tools the agent may call. Each returns plain JSON for the model and records, as a side effect,
the citations and UI blocks that back it. The final answer can only cite what a tool produced.
"""

from __future__ import annotations

import json
import re
from datetime import date

from services.common.scoring import confidence_score
from services.common.settings import Settings
from services.common.text import format_area, tokenize
from services.conversation.understand import UnderstoodQuery, understand
from services.knowledge import parks as park_knowledge
from services.knowledge import tariffs
from services.knowledge.visa import visa_block
from services.retrieval.index import HybridIndex
from services.retrieval.planner import shortlist
from services.sources.tanapa_api import TARIFF_PAGE, VISITOR_LABELS, match_park

NOISE_TYPES = {"manual", "statistics", "policy", "act", "newsletter", "publication"}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_fees",
            "description": "Official TANAPA fees in force on the travel date for one park. Categories include Entrance (conservation fee), Public Camping, Special Camping, Seasonal Camping, Vehicles, Walking Safari, Night Game Drive, Ranger Fees, Boating, Canoeing, Sport Fishing, Huts, Cottage, Bandas, Hostel, Rest House, Bush Meals, Others (balloon safari), Rescue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "park": {"type": "string", "description": "Park name, e.g. Serengeti"},
                    "category": {"type": "string", "description": "Fee category. Defaults to Entrance."},
                    "visitor": {"type": "string", "enum": ["non_resident", "expatriate", "eac_citizen"], "description": "Omit to get every visitor class."},
                    "keyword": {"type": "string", "description": "Optional word the fee item must contain, e.g. balloon"},
                },
                "required": ["park"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_trip_cost",
            "description": "Total park entrance (conservation) fees for a party over a number of days, from the official tariff. Use this for any total; never add up fees yourself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "park": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1},
                    "adults": {"type": "integer", "minimum": 0},
                    "child_ages": {"type": "array", "items": {"type": "integer"}},
                    "visitor": {"type": "string", "enum": ["non_resident", "expatriate", "eac_citizen"]},
                },
                "required": ["park", "days", "adults"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_park",
            "description": "Profile of one TANAPA national park: official description (habitats, wildlife named by TANAPA, activities), zone, area, year established, temperature, elevation, attractions, contacts.",
            "parameters": {"type": "object", "properties": {"park": {"type": "string"}}, "required": ["park"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recommend_parks",
            "description": "Shortlist TANAPA parks for a trip from interests, length and starting point.",
            "parameters": {
                "type": "object",
                "properties": {
                    "interests": {"type": "array", "items": {"type": "string"}, "description": "e.g. wildlife, hiking, primates, beach, birds"},
                    "days": {"type": "integer"},
                    "origin": {"type": "string", "description": "Where the visitor starts, e.g. Arusha or Dar es Salaam"},
                    "avoid_beach": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_visa",
            "description": "Tanzania visa requirement and fee for a passport country, from the immigration eligibility list.",
            "parameters": {"type": "object", "properties": {"passport": {"type": "string"}}, "required": ["passport"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search official documents (TANAPA park pages, activities and their FAQs, fee notes, plan-a-trip seasons and rules, guidelines, regulations, brochures, immigration guideline, NCAA/TAWA pages). Use for seasons, rules, safety, activities, wildlife and anything not covered by the other tools.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "park": {"type": "string", "description": "Optional park to focus on"}},
                "required": ["query"],
            },
        },
    },
]


class Toolbox:
    def __init__(self, store, index: HybridIndex, settings: Settings, as_of: date, profile: dict | None = None) -> None:
        self.store = store
        self.index = index
        self.settings = settings
        self.as_of = as_of
        self.profile = profile or {}
        self.citations: list[dict] = []
        self.blocks: list[dict] = []
        self.evidence: list[str] = []
        self.recommended: list[dict] = []
        self.calls: list[dict] = []
        self.best_retrieval: float = 0.0
        self.structured_hit = False

    # Dispatch -----------------------------------------------------------

    def call(self, name: str, arguments: dict) -> dict:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            result = {"error": f"unknown tool {name}"}
        else:
            try:
                result = handler(**{key: value for key, value in arguments.items() if value not in (None, "")})
            except TypeError as exc:
                result = {"error": f"bad arguments: {exc}"}
        self.calls.append({"name": name, "arguments": arguments})
        self.evidence.append(json.dumps(result, ensure_ascii=False))
        return result

    # Tools --------------------------------------------------------------

    def tool_get_fees(self, park: str, category: str = "Entrance", visitor: str | None = None, keyword: str | None = None) -> dict:
        slug, name = self._park(park)
        if slug is None:
            return {"error": f"'{park}' is not a TANAPA national park in the index", "parks": self._park_names()}
        if not tariffs.has_tariffs(self.store):
            return {"error": "The live tariff has not been loaded. Say fees cannot be quoted and give the official tariff page.", "tariff_page": TARIFF_PAGE}
        available = tariffs.categories_for(self.store, slug)
        chosen = _match_category(category or "Entrance", available)
        if chosen is None:
            return {"error": f"No '{category}' fees for {name}", "available_categories": available}
        visitors = (visitor,) if visitor in tariffs.PERSON_VISITORS else None
        rows = tariffs.in_force_rows(self.store, slug, self.as_of, categories=(chosen,), visitors=visitors)
        if keyword:
            rows = [row for row in rows if keyword.lower() in row["product"].lower()] or rows
        if not rows:
            return {
                "park": name,
                "category": chosen,
                "travel_date": self.as_of.isoformat(),
                "rows": [],
                "note": f"TANAPA publishes no {chosen} row in force on {self.as_of.isoformat()} for {name}.",
                "published_windows": self._windows(slug, chosen),
                "cite": self._cite_tariff(name),
            }
        self.structured_hit = True
        block = tariffs.fee_block(self.store, slug, name, self.as_of, self.settings.tzs_per_usd, categories=(chosen,), visitors=visitors)
        if block:
            if keyword:
                block["rows"] = [row for row in block["rows"] if keyword.lower() in row["item"].lower()] or block["rows"]
            block["category"] = chosen
            self._add_block(block)
        cite = self._cite_tariff(name)
        return {
            "park": name,
            "category": chosen,
            "travel_date": self.as_of.isoformat(),
            "currency_note": f"Official amounts are TZS. USD is approximate at {self.settings.tzs_per_usd:g} TZS per USD.",
            "rows": [
                {
                    "item": row["item"],
                    "visitor": row["visitor_label"],
                    "season": row["season_label"],
                    "valid": f"{row['valid_from']} to {row['valid_until']}",
                    "tzs": row["amount"],
                    "usd_approx": round(row["amount"] / self.settings.tzs_per_usd, 2),
                    **({"unit": row["unit"]} if row.get("unit") else {}),
                }
                for row in rows[:40]
            ],
            "notes": tariffs.fee_notes(self.store),
            "cite": cite,
        }

    def tool_estimate_trip_cost(self, park: str, days: int, adults: int, child_ages: list | None = None, visitor: str | None = None) -> dict:
        slug, name = self._park(park)
        if slug is None:
            return {"error": f"'{park}' is not a TANAPA national park in the index"}
        chosen, reason = (visitor, "given") if visitor in tariffs.PERSON_VISITORS else tariffs.visitor_class(self.profile)
        ages = [int(age) for age in (child_ages or []) if str(age).lstrip("-").isdigit()]
        block = tariffs.estimate(self.store, slug, name, self.as_of, self.settings.tzs_per_usd, days=int(days), adults=int(adults), child_ages=ages, visitor=chosen)
        if block is None:
            return {"error": f"No entrance fee in force on {self.as_of.isoformat()} for {name} ({VISITOR_LABELS[chosen]})."}
        self.structured_hit = True
        self._add_block(block)
        cite = self._cite_tariff(name)
        return {
            "park": name,
            "visitor_class": block["visitor_label"],
            "visitor_class_reason": reason,
            "days": block["days"],
            "lines": block["lines"],
            "total_tzs": block["total_tzs"],
            "total_usd_approx": block["total_usd"],
            "excludes": block["excludes"],
            "cite": cite,
        }

    def tool_get_park(self, park: str) -> dict:
        slug, _name = self._park(park)
        if slug is None:
            return {"error": f"'{park}' is not a TANAPA national park in the index", "parks": self._park_names()}
        card = park_knowledge.get_card(self.store, slug)
        self.structured_hit = True
        self._recommend(card, "Asked about this park.")
        self._add_block({"type": "parks", "parks": [_public_card(card)]})
        page_cite = self._cite(
            document_id=f"tanapa_live_park_{slug}",
            title=f"{card['name']} — TANAPA park page",
            organization="TANAPA",
            source_url=card["source_url"],
            excerpt=card["summary"] or card["about"][:300],
            kind="api",
        )
        map_cite = self._cite(
            document_id=f"tanapa_park_{slug}",
            title="TANAPA GIS map of national parks (2024)",
            organization="TANAPA",
            source_url=card["map_source_url"],
            excerpt=f"{card['name']}: {format_area(card['area_km2'])} km², established {card['established_year']}.",
            kind="document",
        )
        return {
            "name": card["name"],
            "zone": card["zone"],
            "area_km2_gis_map_2024": card["area_km2"],
            "area_km2_on_park_page": card["area_km2_site"],
            "established": card["established_year"],
            "slogan": card["slogan"],
            "temperature_c": card["temperature"],
            "elevation_m": card["elevation"],
            "attractions": card["attractions"],
            "contact": card["contact"],
            "description": card["about"][:2400],
            "cite_park_page": page_cite,
            "cite_gis_map": map_cite,
        }

    def tool_recommend_parks(self, interests: list | None = None, days: int | None = None, origin: str | None = None, avoid_beach: bool | None = None) -> dict:
        words = " ".join(str(item) for item in (interests or []))
        text = f"{days or ''} days {words} {'no beach' if avoid_beach else ''} which parks"
        profile = {**self.profile}
        if origin:
            profile["origin"] = origin
        query = understand(text, self.store.list_parks(), profile=profile)
        query.park_slugs = []
        picks = shortlist(self.store.list_parks(), query, limit=4)
        cards = []
        for park, reason in picks:
            card = park_knowledge.get_card(self.store, park.slug)
            self._recommend(card, reason)
            cards.append(card)
        if cards:
            self.structured_hit = True
            self._add_block({"type": "parks", "parks": [_public_card(card) for card in cards]})
        return {
            "parks": [
                {
                    "name": card["name"],
                    "zone": card["zone"],
                    "summary": card["summary"],
                    "cite": self._cite(
                        document_id=f"tanapa_live_park_{card['slug']}",
                        title=f"{card['name']} — TANAPA park page",
                        organization="TANAPA",
                        source_url=card["source_url"],
                        excerpt=card["summary"],
                        kind="api",
                    ),
                }
                for card in cards
            ],
            "note": "Shortlist from SafariAI planning tags (interest, coast, circuit). It is not an itinerary.",
            "ngorongoro": "Ngorongoro Conservation Area is run by NCAA, not TANAPA (https://www.ncaa.go.tz).",
        }

    def tool_check_visa(self, passport: str) -> dict:
        block = visa_block(passport, self.profile.get("origin") or "")
        if block is None:
            return {"error": "passport country is required"}
        self.structured_hit = block["found"]
        self._add_block(block)
        cite = self._cite(
            document_id="immigration_visa_eligibility",
            title="List of countries with visa eligibility — Tanzania Immigration",
            organization="Tanzania Immigration",
            source_url=block["source_url"],
            excerpt=f"{block['country']}: {block['visa']} {block['fee']}".strip(),
            kind="document",
        )
        return {
            "passport": block["country"],
            "visa": block["visa"],
            "visa_fee": block["fee"],
            "on_eligibility_list": block["found"],
            "details": {row["label"]: row["value"] for row in block["lines"]},
            "apply_only_at": block["apply_url"],
            "cite": cite,
        }

    def tool_search_knowledge(self, query: str, park: str | None = None) -> dict:
        slug = self._park(park)[0] if park else None
        understood = understand(query, self.store.list_parks())
        if slug and slug not in understood.park_slugs:
            understood.park_slugs = [slug]
            understood.retrieval_query += f" {slug}"
        wants_policy = bool(re.search(r"\b(invest|policy|act|statistic|regulation|law|sheria)\b", query, re.IGNORECASE))
        ranked = self.index.search(understood, self.as_of, top_k=8, exclude_types=None if wants_policy else NOISE_TYPES)
        passages = []
        for item in ranked[:6]:
            excerpt = best_excerpt(understood.retrieval_query, item.chunk.text)
            if not excerpt:
                continue
            self.best_retrieval = max(self.best_retrieval, confidence_score(item.score, item.reranker, item.authority, item.freshness))
            cite = self._cite(
                document_id=item.chunk.document_id,
                title=item.chunk.title,
                organization=item.chunk.organization,
                source_url=item.chunk.source_url or "",
                excerpt=excerpt[:320],
                kind="document",
                status=item.chunk.status,
                authority=item.chunk.authority,
                effective_from=item.chunk.effective_from,
                effective_until=item.chunk.effective_until,
            )
            passages.append(
                {
                    "cite": cite,
                    "title": item.chunk.title,
                    "organization": item.chunk.organization,
                    "status": item.chunk.status,
                    "text": excerpt,
                    "relevance": round(item.score, 3),
                }
            )
        return {"passages": passages} if passages else {"passages": [], "note": "No official passage matched."}

    # Helpers ------------------------------------------------------------

    def _park(self, text: str | None) -> tuple[str | None, str | None]:
        if not text:
            return None, None
        parks = self.store.list_parks()
        slug = match_park(text, parks)
        if slug is None:
            found = understand(text, parks).park_slugs
            slug = found[0] if found else None
        name = next((park.name for park in parks if park.slug == slug), None)
        return slug, name

    def _park_names(self) -> list[str]:
        return [park.name for park in self.store.list_parks()]

    def _windows(self, slug: str, category: str) -> list[str]:
        windows = {
            f"{record.payload['valid_from']} to {record.payload['valid_until']}"
            for record in self.store.list_records("tariff")
            if record.payload["park_slug"] == slug and record.payload["category"] == category
        }
        return sorted(windows)

    def _cite_tariff(self, park_name: str) -> int:
        return self._cite(
            document_id="tanapa_tariff_live",
            title="TANAPA park fees and tariffs 2026/27 (live)",
            organization="TANAPA",
            source_url=TARIFF_PAGE,
            excerpt=f"Official fee rows for {park_name}, valid on {self.as_of.isoformat()}.",
            kind="api",
        )

    def _cite(self, *, document_id: str, title: str, organization: str, source_url: str, excerpt: str, kind: str, status: str = "current", authority: str = "official", effective_from=None, effective_until=None) -> int:
        for citation in self.citations:
            if citation["document_id"] == document_id:
                return citation["n"]
        number = len(self.citations) + 1
        self.citations.append(
            {
                "n": number,
                "document_id": document_id,
                "title": title,
                "organization": organization,
                "authority": authority,
                "status": status,
                "effective_from": effective_from,
                "effective_until": effective_until,
                "source_url": source_url,
                "excerpt": excerpt,
                "kind": kind,
            }
        )
        return number

    def _add_block(self, block: dict) -> None:
        key = (block["type"], block.get("park_slug"), block.get("category"), block.get("passport"))
        self.blocks = [item for item in self.blocks if (item["type"], item.get("park_slug"), item.get("category"), item.get("passport")) != key or item["type"] == "parks"]
        if block["type"] == "parks":
            existing = next((item for item in self.blocks if item["type"] == "parks"), None)
            if existing:
                seen = {card["slug"] for card in existing["parks"]}
                existing["parks"].extend(card for card in block["parks"] if card["slug"] not in seen)
                return
        self.blocks.append(block)

    def _recommend(self, card: dict, reason: str) -> None:
        if all(item["slug"] != card["slug"] for item in self.recommended):
            self.recommended.append({"slug": card["slug"], "name": card["name"], "reason": reason})


def _public_card(card: dict) -> dict:
    return {key: value for key, value in card.items() if key != "about"}


def _match_category(wanted: str, available: list[str]) -> str | None:
    lowered = wanted.lower().strip()
    for category in available:
        if category.lower() == lowered:
            return category
    for category in available:
        if lowered in category.lower() or category.lower() in lowered:
            return category
    aliases = {"conservation": "Entrance", "entry": "Entrance", "camping": "Public Camping", "vehicle": "Vehicles", "balloon": "Others"}
    for key, value in aliases.items():
        if key in lowered and value in available:
            return value
    return None


def best_excerpt(query: str, text: str, limit: int = 700) -> str:
    """The contiguous run of sentences that shares the most terms with the query."""
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if part.strip()]
    if not sentences:
        return ""
    wanted = set(tokenize(query)) - _STOP
    if not wanted:
        return " ".join(sentences)[:limit]
    scores = [len(wanted & set(tokenize(sentence))) for sentence in sentences]
    best = max(range(len(sentences)), key=lambda index: scores[index])
    if scores[best] == 0:
        return ""
    picked = [sentences[best]]
    left, right = best - 1, best + 1
    while len(" ".join(picked)) < limit and (left >= 0 or right < len(sentences)):
        if right < len(sentences):
            picked.append(sentences[right])
            right += 1
        elif left >= 0:
            picked.insert(0, sentences[left])
            left -= 1
    return " ".join(picked)[:limit].rsplit(" ", 1)[0] if len(" ".join(picked)) > limit else " ".join(picked)


_STOP = {
    "the", "and", "for", "can", "what", "how", "is", "are", "in", "of", "to", "a", "do", "does", "with", "on", "at",
    "national", "park", "parks", "tanzania", "i", "my", "we", "you", "be", "it", "there", "which", "when", "where",
}


def query_for(question: str, store, profile: dict, history: list[dict]) -> UnderstoodQuery:
    return understand(question, store.list_parks(), profile=profile, history=history)
