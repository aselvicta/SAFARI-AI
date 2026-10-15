"""Deterministic answers built from the same tools the agent uses.

Runs when no LLM is configured, when the LLM fails, or when its draft states something the
tools did not return. Every sentence is assembled from tool output, so it is always grounded.
"""

from __future__ import annotations

import re

from services.agent.tools import Toolbox
from services.conversation.understand import UnderstoodQuery
from services.knowledge import tariffs
from services.sources.tanapa_api import TARIFF_PAGE

NCAA_URL = "https://www.ncaa.go.tz/about-ncaa/"
TTB_URL = "https://www.tanzaniatourism.go.tz/"
IMMIGRATION_URL = "https://visa.immigration.go.tz/guidelines"


def compose(query: UnderstoodQuery, tools: Toolbox) -> dict:
    """Returns {answer, abstained, limits}. Citations and blocks accumulate on `tools`."""
    handler = {
        "fee": _fee,
        "planning": _planning,
        "park_fact": _park_fact,
        "wildlife": _wildlife,
        "activity": _activity,
        "visa": _visa,
        "contact": _contact,
        "accommodation": _accommodation,
        "scope": _scope,
        "unsupported": _unsupported,
    }.get(query.intent, _passage)
    return handler(query, tools)


# Intents --------------------------------------------------------------------


def _fee(query, tools):
    sw = query.language == "sw"
    if not query.park_slugs:
        return _fee_overview(query, tools)
    lines = []
    party = _party(query, tools)
    for slug in query.park_slugs[:3]:
        result = tools.call("get_fees", {"park": slug, "category": query.fee_category or "Entrance", "keyword": "balloon" if query.fee_keyword == "balloon" else None})
        if result.get("error"):
            lines.append(result["error"] + ("" if "available_categories" not in result else ". Available: " + ", ".join(result["available_categories"])))
            continue
        if not result["rows"]:
            lines.append(result["note"] + f" [{result['cite']}]")
            continue
        lines.append(_fee_summary(result, tools, sw))
        if party and (result["category"] == "Entrance"):
            estimate = tools.call("estimate_trip_cost", {"park": slug, **party})
            if not estimate.get("error"):
                lines.append(_estimate_sentence(estimate, sw))
    notes = tariffs.fee_notes(tools.store, limit=2)
    if notes:
        lines.append(" ".join(note.rstrip(".") + "." for note in notes))
    return {"answer": "\n\n".join(lines), "abstained": not tools.structured_hit, "limits": [] if tools.structured_hit else ["fees"]}


def _fee_overview(query, tools):
    """No park named: adult entrance for the visitor's class across every park."""
    sw = query.language == "sw"
    visitor, _reason = tariffs.visitor_class(tools.profile)
    rows = []
    for park in tools.store.list_parks():
        found = tariffs.in_force_rows(tools.store, park.slug, tools.as_of, categories=("Entrance",), visitors=(visitor,))
        adult = next((row for row in found if row["age"] == "adult" and row["visitor"] == visitor), None)
        if adult:
            rows.append((adult["amount"], park.name))
    if not rows:
        return {
            "answer": (f"Sina ada ya TANAPA inayotumika tarehe hiyo. Angalia: {TARIFF_PAGE}" if sw else f"I don't have a TANAPA fee in force for that date. Check the official tariff page: {TARIFF_PAGE}"),
            "abstained": True,
            "limits": ["fees"],
        }
    tools.structured_hit = True
    cite = tools._cite_tariff("all parks")
    rows.sort(reverse=True)
    label = tariffs.VISITOR_LABELS[visitor]
    head = (
        f"Ada ya kuingia kwa mtu mzima ({label}) kwa siku, tarehe {tools.as_of.isoformat()} [{cite}]:"
        if sw
        else f"Adult park entry per person per 24 hours ({label}), in force on {tools.as_of.isoformat()} [{cite}]:"
    )
    body = "\n".join(f"- **{name}**: TZS {_money(amount)} (≈ USD {_money(amount / tools.settings.tzs_per_usd)})" for amount, name in rows)
    tail = "Tell me the park for the full table, child rates and camping." if not sw else "Niambie hifadhi upate jedwali kamili."
    return {"answer": f"{head}\n\n{body}\n\n{tail}", "abstained": False, "limits": []}


def _planning(query, tools):
    sw = query.language == "sw"
    parts = []
    if query.park_slugs:
        for slug in query.park_slugs[:3]:
            park = tools.call("get_park", {"park": slug})
            if park.get("error"):
                continue
            parts.append(f"**{park['name']}** — {_first(park['description'], 2)} [{park['cite_park_page']}]")
    else:
        interests = ["wildlife"] if query.wants_wildlife or query.animal else []
        result = tools.call("recommend_parks", {"interests": interests, "days": query.days, "origin": query.origin, "avoid_beach": query.wants_beach is False})
        if result["parks"]:
            intro = (
                f"Hifadhi zinazofaa safari ya siku {query.days}:" if sw and query.days else "Hifadhi zinazofaa:" if sw
                else f"For a {query.days}-day trip, these TANAPA parks fit:" if query.days else "These TANAPA parks fit what you described:"
            )
            parts.append(intro + "\n" + "\n".join(f"- **{item['name']}**" + (f" ({item['zone']})" if item["zone"] else "") + f" — {_first(item['summary'], 2)} [{item['cite']}]" for item in result["parks"]))
            if query.wants_wildlife and query.wants_beach is False:
                parts.append(
                    "Ngorongoro Conservation Area iko chini ya NCAA, si TANAPA: " + NCAA_URL
                    if sw
                    else f"Ngorongoro Conservation Area is managed by the Ngorongoro Conservation Area Authority (NCAA), not TANAPA: {NCAA_URL}"
                )
    party = _party(query, tools)
    for slug in (query.park_slugs or [item["slug"] for item in tools.recommended])[:1]:
        if party:
            estimate = tools.call("estimate_trip_cost", {"park": slug, **party})
            if not estimate.get("error"):
                parts.append(_estimate_sentence(estimate, sw))
        else:
            fees = tools.call("get_fees", {"park": slug, "visitor": tariffs.visitor_class(tools.profile)[0]})
            if fees.get("rows"):
                parts.append(_fee_summary(fees, tools, sw))
    passport = (tools.profile.get("passport") or "").strip()
    if passport:
        visa = tools.call("check_visa", {"passport": passport})
        if not visa.get("error"):
            parts.append(_visa_sentence(visa, sw))
    missing = _missing(query, tools, sw)
    if missing:
        parts.append(missing)
    if not parts:
        return _passage(query, tools)
    return {"answer": "\n\n".join(parts), "abstained": False, "limits": []}


def _park_fact(query, tools):
    if not query.park_slugs:
        return _passage(query, tools)
    park = tools.call("get_park", {"park": query.park_slugs[0]})
    sw = query.language == "sw"
    facts = [
        f"**{park['name']}** ({park['zone']})",
        (f"eneo km² {_money(park['area_km2_gis_map_2024'])}" if sw else f"area {_money(park['area_km2_gis_map_2024'])} km²") + f" [{park['cite_gis_map']}]" if park["area_km2_gis_map_2024"] else "",
        (f"ilianzishwa {park['established']}" if sw else f"established {park['established']}") if park["established"] else "",
    ]
    lines = [", ".join(item for item in facts if item) + "."]
    if park["area_km2_on_park_page"] and park["area_km2_gis_map_2024"] and abs(park["area_km2_on_park_page"] - park["area_km2_gis_map_2024"]) > 1:
        lines.append(f"The TANAPA park page gives {_money(park['area_km2_on_park_page'])} km² [{park['cite_park_page']}]; the 2024 GIS map figure is used above.")
    extra = []
    if park["temperature_c"]:
        extra.append(f"temperature {park['temperature_c']} °C")
    if park["elevation_m"]:
        extra.append(f"elevation {park['elevation_m']} m")
    if extra:
        lines.append(("Climate: " if not sw else "Hali: ") + ", ".join(extra) + f" [{park['cite_park_page']}].")
    lines.append(_first(park["description"], 2) + f" [{park['cite_park_page']}]")
    return {"answer": "\n\n".join(lines), "abstained": False, "limits": []}


def _wildlife(query, tools):
    sw = query.language == "sw"
    animal = (query.animal or "").rstrip("s")
    if query.park_slugs:
        park = tools.call("get_park", {"park": query.park_slugs[0]})
        if not park.get("error"):
            sentence = _sentence_with(park["description"], animal)
            if sentence:
                lead = f"Ndiyo. TANAPA inataja {query.animal} katika {park['name']}:" if sw else f"Yes. TANAPA names {query.animal} in {park['name']}:"
                return {"answer": f"{lead}\n\n> {sentence} [{park['cite_park_page']}]", "abstained": False, "limits": []}
    found = tools.call("search_knowledge", {"query": f"{query.animal} {' '.join(query.park_slugs)}", "park": query.park_slugs[0] if query.park_slugs else None})
    for passage in found["passages"]:
        sentence = _sentence_with(passage["text"], animal)
        if sentence and (not query.park_slugs or any(slug.split("-")[0] in passage["text"].lower() or slug.split("-")[0] in passage["title"].lower() for slug in query.park_slugs)):
            return {"answer": f"{passage['title']}:\n\n> {sentence} [{passage['cite']}]", "abstained": False, "limits": []}
    name = ", ".join(query.park_slugs) or "that park"
    return {
        "answer": (
            f"Kurasa rasmi za TANAPA nilizonazo hazitaji {query.animal} kwa {name}. Sitakisia."
            if sw
            else f"The official TANAPA material I have does not mention {query.animal} for {name.replace('-', ' ').title()}, so I won't guess. Rangers at the gate or a licensed guide can tell you about recent sightings."
        ),
        "abstained": True,
        "limits": ["wildlife_species"],
    }


def _activity(query, tools):
    sw = query.language == "sw"
    found = tools.call("search_knowledge", {"query": query.raw, "park": query.park_slugs[0] if query.park_slugs else None})
    parts = []
    if found["passages"]:
        top = found["passages"][0]
        parts.append(f"{_first(top['text'], 3)} [{top['cite']}]")
    if query.park_slugs and query.fee_category:
        fees = tools.call("get_fees", {"park": query.park_slugs[0], "category": query.fee_category, "keyword": "balloon" if query.fee_keyword == "balloon" else None})
        if fees.get("rows"):
            parts.append(_fee_summary(fees, tools, sw))
    if not parts:
        return _abstain(query, "activity")
    return {"answer": "\n\n".join(parts), "abstained": False, "limits": []}


def _visa(query, tools):
    sw = query.language == "sw"
    passport = (tools.profile.get("passport") or "").strip() or _country_in(query.raw)
    if passport:
        visa = tools.call("check_visa", {"passport": passport})
        if not visa.get("error"):
            return {"answer": _visa_sentence(visa, sw), "abstained": not visa["on_eligibility_list"], "limits": [] if visa["on_eligibility_list"] else ["visa"]}
    found = tools.call("search_knowledge", {"query": query.raw + " visa guideline"})
    passages = [item for item in found["passages"] if "immigration" in item["organization"].lower()]
    ask = "Ni pasipoti ya nchi gani? Nitakuonyesha masharti yake." if sw else "Which passport will you travel on? I'll show the exact visa rule and fee for it."
    if passages:
        return {"answer": f"{_first(passages[0]['text'], 3)} [{passages[0]['cite']}]\n\n{ask}", "abstained": False, "limits": []}
    return {"answer": f"{ask}\n\nOfficial guidelines: {IMMIGRATION_URL}", "abstained": True, "limits": ["visa"]}


def _contact(query, tools):
    if not query.park_slugs:
        org = "TANAPA headquarters: PO Box 3134, Arusha · +255 (0) 272 970 404 · info@tanzaniaparks.go.tz"
        return {"answer": org, "abstained": False, "limits": []}
    park = tools.call("get_park", {"park": query.park_slugs[0]})
    contact = park.get("contact") or {}
    if not (contact.get("phone") or contact.get("email")):
        return _abstain(query, "contact")
    lines = [f"**{park['name']}** [{park['cite_park_page']}]"]
    if contact.get("phone"):
        lines.append("- Phone: " + ", ".join(contact["phone"]))
    if contact.get("email"):
        lines.append("- Email: " + ", ".join(contact["email"]))
    if contact.get("address"):
        lines.append("- Address: " + contact["address"])
    return {"answer": "\n".join(lines), "abstained": False, "limits": []}


def _accommodation(query, tools):
    sw = query.language == "sw"
    parts = []
    options = [record.payload for record in tools.store.list_records("accommodation")]
    if options:
        cite = tools._cite(
            document_id="tanapa_accommodation",
            title="Accommodation types in national parks — TANAPA",
            organization="TANAPA",
            source_url="https://www.tanzaniaparks.go.tz/tourism/visitor-information/accommodation",
            excerpt=", ".join(item["title"] for item in options),
            kind="api",
        )
        parts.append(("Aina za malazi ndani ya hifadhi" if sw else "Ways to stay inside the parks") + f" [{cite}]:\n" + "\n".join(f"- **{item['title']}** ({item['price_range']})" for item in options))
    if query.park_slugs:
        category = query.fee_category or "Public Camping"
        fees = tools.call("get_fees", {"park": query.park_slugs[0], "category": category})
        if fees.get("rows"):
            parts.append(_fee_summary(fees, tools, sw))
    if not parts:
        return _passage(query, tools)
    return {"answer": "\n\n".join(parts), "abstained": False, "limits": []}


def _scope(query, tools):
    sw = query.language == "sw"
    names = ", ".join(query.scope_hits) or "That destination"
    if "Ngorongoro Conservation Area" in query.scope_hits:
        cite = tools._cite(document_id="registry:ncaa", title="Ngorongoro Conservation Area Authority", organization="NCAA", source_url=NCAA_URL, excerpt="Ngorongoro is managed by NCAA, not TANAPA.", kind="pointer")
        answer = (
            f"Ngorongoro iko chini ya Mamlaka ya Hifadhi ya Ngorongoro (NCAA), si TANAPA, hivyo sitaji ada zake [{cite}]. Angalia {NCAA_URL}."
            if sw
            else f"Ngorongoro Conservation Area is run by the Ngorongoro Conservation Area Authority (NCAA), not TANAPA, so I don't quote its fees or rules [{cite}]. Check {NCAA_URL}. I can help with the TANAPA parks around it — Serengeti, Tarangire and Lake Manyara."
        )
    else:
        cite = tools._cite(document_id="registry:ttb", title="Tanzania Tourist Board", organization="Tanzania Tourist Board", source_url=TTB_URL, excerpt="Destinations outside the TANAPA national parks.", kind="pointer")
        answer = (
            f"{names} iko nje ya hifadhi za TANAPA ninazozijua [{cite}]."
            if sw
            else f"{names} is outside the TANAPA national parks I cover. The Tanzania Tourist Board is the official starting point: {TTB_URL} [{cite}]"
        )
    return {"answer": answer, "abstained": True, "limits": ["scope"]}


def _unsupported(query, tools):
    sw = query.language == "sw"
    answer = (
        "Sikupata chanzo rasmi kinachothibitisha bei au huduma hiyo. Thibitisha na mtoa huduma."
        if sw
        else "I couldn't find an official source confirming that service or price, so I won't quote it. Charter and helicopter transfers are sold by private operators; confirm with them directly."
    )
    if query.scope_hits:
        answer += " " + ", ".join(query.scope_hits) + (" iko nje ya hifadhi za TANAPA." if sw else " is outside the TANAPA parks I cover.")
    return {"answer": answer, "abstained": True, "limits": ["unsupported_claim"]}


def _passage(query, tools):
    found = tools.call("search_knowledge", {"query": query.raw, "park": query.park_slugs[0] if query.park_slugs else None})
    strong = [item for item in found["passages"] if item["relevance"] >= 0.30 and _covers(query, item["text"])]
    if not strong:
        return _abstain(query, query.intent)
    top = strong[0]
    answer = f"{_first(top['text'], 4)} [{top['cite']}]"
    if len(strong) > 1 and strong[1]["title"] != top["title"]:
        answer += f"\n\n{_first(strong[1]['text'], 2)} [{strong[1]['cite']}]"
    return {"answer": answer, "abstained": False, "limits": []}


_FILLER = {
    "see", "get", "find", "visit", "tell", "about", "me", "any", "there", "much", "many", "need", "know", "want",
    "go", "going", "will", "would", "should", "could", "is", "are", "the", "and", "for", "can", "what", "how", "in",
    "of", "to", "do", "does", "with", "on", "at", "national", "park", "parks", "tanzania", "my", "we", "you", "it",
    "which", "when", "where", "why", "who", "a", "an", "be", "or", "i", "je", "ya", "wa", "na", "kwa", "ni", "kuna",
}


def _covers(query, text: str) -> bool:
    """A passage answers only if it contains the question's content words (not just the park name)."""
    from services.common.text import tokenize

    park_words = {word for slug in query.park_slugs for word in slug.split("-")}
    content = {token for token in tokenize(query.raw) if token not in _FILLER and token not in park_words and len(token) > 2}
    if not content:
        return True
    found = set(tokenize(text))
    hits = {token for token in content if token in found or token.rstrip("s") in found or f"{token}s" in found}
    return len(hits) >= max(1, (len(content) + 1) // 2)


def _abstain(query, topic: str) -> dict:
    sw = query.language == "sw"
    return {
        "answer": (
            "Sina chanzo rasmi kinachojibu hilo. Sitakisia. Angalia https://www.tanzaniaparks.go.tz au uliza kwenye lango la hifadhi."
            if sw
            else "I don't have an official source that answers this, so I won't guess. TANAPA's site (https://www.tanzaniaparks.go.tz) or the park gate can confirm."
        ),
        "abstained": True,
        "limits": [topic],
    }


# Sentences ------------------------------------------------------------------


def _fee_summary(result: dict, tools: Toolbox, sw: bool) -> str:
    rows = result["rows"]
    visitor, _reason = tariffs.visitor_class(tools.profile)
    wanted = tariffs.VISITOR_LABELS[visitor]
    mine = [row for row in rows if row["visitor"] == wanted] or rows
    shown = mine[:4]
    head = (
        f"**{result['park']} — {result['category']}**, {wanted}, inatumika {result['travel_date']} [{result['cite']}]:"
        if sw
        else f"**{result['park']} — {result['category']}** for {wanted}, in force on {result['travel_date']} [{result['cite']}]:"
    )
    lines = [f"- {row['item']}: TZS {_money(row['tzs'])} (≈ USD {_money(row['usd_approx'])})" + (f", {row['season'].lower()} season" if row["season"].lower() not in {"all"} else "") for row in shown]
    valid = shown[0]["valid"] if shown else ""
    tail = f"Valid {valid}. The full table for every visitor class is below." if not sw else f"Inatumika {valid.replace(' to ', ' hadi ')}. Jedwali kamili liko chini."
    return head + "\n" + "\n".join(lines) + "\n\n" + tail


def _estimate_sentence(estimate: dict, sw: bool) -> str:
    lines = "\n".join(
        f"- {line['label']}: {line['qty']} × {line['days']} × TZS {_money(line['unit_tzs'])} = TZS {_money(line['total_tzs'])}"
        for line in estimate["lines"]
    )
    head = (
        f"**Makadirio ya ada za kuingia {estimate['park']}** ({estimate['visitor_class']}, siku {estimate['days']}) [{estimate['cite']}]:"
        if sw
        else f"**Park entry for your group at {estimate['park']}** ({estimate['visitor_class']}, {estimate['days']} days) [{estimate['cite']}]:"
    )
    total = f"**Total: TZS {_money(estimate['total_tzs'])}** (≈ USD {_money(estimate['total_usd_approx'])})."
    return f"{head}\n{lines}\n\n{total} " + ("Haijumuishi gari, malazi, wala shughuli." if sw else "Vehicle entry, accommodation and activities are extra.")


def _visa_sentence(visa: dict, sw: bool) -> str:
    if not visa["on_eligibility_list"]:
        return (
            f"{visa['passport']} haipo kwenye orodha ya viza niliyonayo. Angalia {IMMIGRATION_URL} [{visa['cite']}]."
            if sw
            else f"{visa['passport']} isn't on the visa eligibility list I hold. Check {IMMIGRATION_URL} [{visa['cite']}]."
        )
    fee = f", fee {visa['visa_fee']}" if visa["visa_fee"] else ""
    if visa["visa"] == "Not required":
        return f"**Visa:** {visa['passport']} passport holders don't need a visa for Tanzania [{visa['cite']}]. Carry a return ticket."
    return (
        f"**Visa:** {visa['passport']} — {visa['visa']}{fee} [{visa['cite']}]. Apply only at {visa['apply_only_at']}; your passport needs 6 months' validity and a blank page."
    )


def _missing(query, tools, sw: bool) -> str:
    profile = tools.profile
    gaps = []
    if not (profile.get("days") or query.days):
        gaps.append("siku ngapi" if sw else "how many days")
    if profile.get("adults") in (None, "") and query.adults is None and not query.child_ages:
        gaps.append("idadi ya watu wazima na umri wa watoto" if sw else "how many adults, and children's ages")
    if not profile.get("passport"):
        gaps.append("pasipoti ya nchi gani" if sw else "your passport country (for the visa and the right fee class)")
    if not gaps:
        return ""
    return ("Nikijua " + ", ".join(gaps) + ", nitakupa jumla ya ada.") if sw else ("Tell me " + ", ".join(gaps) + " and I'll total the park fees for your group.")


def _party(query, tools) -> dict | None:
    profile = tools.profile
    days = profile.get("days") or query.days
    adults = profile.get("adults") if profile.get("adults") not in (None, "") else query.adults
    ages = list(profile.get("child_ages") or query.child_ages or [])
    if not days or (adults in (None, "") and not ages):
        return None
    return {"days": int(days), "adults": int(adults or 0), "child_ages": ages}


def _country_in(text: str) -> str:
    from services.planning.entry import _load_records

    lowered = text.lower()
    for record in _load_records():
        first = record["key"].split(" ")[0]
        stem = first[:-1] if first.endswith(("a", "y")) and len(first) > 5 else first
        if len(first) > 3 and re.search(rf"\b(?:{re.escape(first)}|{re.escape(stem)}(?:ns?|ans?|ians?|ese|ish|s))\b", lowered):
            return record["country"]
    for demonym, country in {"germans?": "Germany", "british": "United Kingdom", "americans?": "USA", "french": "France", "dutch": "Netherlands", "chinese": "China", "japanese": "Japan", "indians?": "India", "ujerumani": "Germany", "uingereza": "United Kingdom", "marekani": "USA", "kenya": "Kenya"}.items():
        if re.search(rf"\b{demonym}\b", lowered):
            return country
    for alias in ("usa", "uk", "america", "britain", "england", "uae"):
        if re.search(rf"\b{alias}\b", lowered):
            return alias
    return ""


def _sentence_with(text: str, word: str) -> str:
    if not word:
        return ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(rf"\b{re.escape(word)}", sentence, re.IGNORECASE):
            return sentence.strip()
    return ""


def _first(text: str, count: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").replace("\n\n", " ").strip())
    return " ".join(sentences[:count]).strip()


def _money(value) -> str:
    value = float(value or 0)
    return f"{int(round(value)):,}" if abs(value - round(value)) < 0.005 or value >= 1000 else f"{value:,.2f}"
