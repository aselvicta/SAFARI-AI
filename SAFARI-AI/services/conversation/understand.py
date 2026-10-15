"""Intent, language, and entity understanding for a visitor question."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from services.common.models import Park

SWAHILI_MARKERS = {
    "nataka",
    "nahitaji",
    "ndio",
    "ndiyo",
    "twende",
    "kwenda",
    "nipe",
    "gharama",
    "hifadhi",
    "watoto",
    "mtoto",
    "wanyamapori",
    "tembo",
    "simba",
    "panga",
    "safari",
    "kuona",
    "kambi",
    "ada",
    "ngapi",
    "lini",
    "naweza",
    "tafadhali",
    "makadirio",
    "siku",
    "kuingia",
    "wageni",
    "raia",
    "wapi",
    "gani",
    "je",
    "bei",
}

SWAHILI_NUMBERS = {
    "moja": 1,
    "mbili": 2,
    "tatu": 3,
    "nne": 4,
    "tano": 5,
    "sita": 6,
    "saba": 7,
    "nane": 8,
    "tisa": 9,
    "kumi": 10,
}

SWAHILI_EXPANSIONS = {
    "hifadhi": "national park",
    "ada": "fee tariff conservation",
    "gharama": "cost fee price",
    "bei": "price fee",
    "wanyamapori": "wildlife animals",
    "tembo": "elephant",
    "simba": "lion",
    "watoto": "children child",
    "mtoto": "child",
    "kambi": "camping camp",
    "gari": "vehicle car",
    "kuingia": "entry enter",
    "makadirio": "estimate cost",
    "ngapi": "how much",
    "lini": "when season",
}

MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

ANIMALS = (
    "elephant", "elephants", "lion", "lions", "leopard", "leopards", "cheetah", "cheetahs", "giraffe", "giraffes",
    "rhino", "rhinos", "wildebeest", "zebra", "zebras", "buffalo", "buffaloes", "hippo", "hippos", "crocodile",
    "crocodiles", "chimpanzee", "chimpanzees", "chimps", "wild dog", "wild dogs", "flamingo", "flamingos", "birds",
    "tembo", "simba", "chui", "duma", "twiga", "kifaru", "nyumbu", "pundamilia", "nyati", "kiboko", "mamba", "sokwe",
)

SWAHILI_ANIMALS = {
    "tembo": "elephant", "simba": "lion", "chui": "leopard", "duma": "cheetah", "twiga": "giraffe",
    "kifaru": "rhino", "nyumbu": "wildebeest", "pundamilia": "zebra", "nyati": "buffalo", "kiboko": "hippo",
    "mamba": "crocodile", "sokwe": "chimpanzee",
}

ACTIVITY_TERMS = (
    "balloon", "walking safari", "night game drive", "night drive", "canoe", "canoeing", "boat", "boating",
    "chimp trekking", "chimpanzee trekking", "habituation", "climb", "climbing", "hike", "hiking", "trek",
    "fishing", "canopy", "cycling", "horse riding", "kayak", "snorkel", "sundowner", "bush meal", "game drive",
    "paragliding", "hot spring", "activity", "activities", "things to do",
)

FEE_CATEGORY_TERMS = {
    "camp": "Public Camping",
    "camping": "Public Camping",
    "special campsite": "Special Camping",
    "seasonal campsite": "Seasonal Camping",
    "fly camp": "FlyCamp",
    "vehicle": "Vehicles",
    "car": "Vehicles",
    "walking safari": "Walking Safari",
    "night game drive": "Night Game Drive",
    "night drive": "Night Game Drive",
    "ranger": "Ranger Fees",
    "guide": "Ranger Fees",
    "balloon": "Others",
    "canoe": "Canoeing",
    "boat": "Boating",
    "fishing": "Sport Fishing",
    "hut": "Huts",
    "cottage": "Cottage",
    "banda": "Bandas",
    "hostel": "Hostel",
    "rest house": "Rest House",
    "bush meal": "Bush Meals",
    "rescue": "Rescue",
    "concession": "Concession",
    "filming": "Filming",
    "rhino": "Rhino Viewing",
    "cycling": "Cycling",
    "canopy": "Canopy Walk",
    "kambi": "Public Camping",
    "gari": "Vehicles",
}

UNSUPPORTED_TERMS = ("helicopter", "charter flight")

SCOPE_TERMS = {
    "ngorongoro": "Ngorongoro Conservation Area",
    "zanzibar": "Zanzibar",
    "mafia": "Mafia Island",
}


@dataclass
class UnderstoodQuery:
    raw: str
    language: str
    retrieval_query: str
    intent: str
    park_slugs: list[str] = field(default_factory=list)
    days: int | None = None
    month: str | None = None
    children: bool = False
    wants_beach: bool | None = None
    wants_wildlife: bool = False
    visitor_category: str | None = None
    mentions_price: bool = False
    unsupported_terms: list[str] = field(default_factory=list)
    scope_hits: list[str] = field(default_factory=list)
    origin: str | None = None
    animal: str | None = None
    adults: int | None = None
    child_ages: list[int] = field(default_factory=list)
    fee_category: str | None = None
    fee_keyword: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def understand(question: str, parks: list[Park], profile: dict | None = None, history: list[dict] | None = None) -> UnderstoodQuery:
    profile = profile or {}
    history = history or []
    raw = question.strip()
    lowered = raw.lower()
    language = _language(lowered)
    park_slugs = _parks_in_text(lowered, parks)
    if not park_slugs:
        for turn in reversed(history):
            prior = _parks_in_text(str(turn.get("content", "")).lower(), parks)
            if prior:
                park_slugs = prior
                break
    days = _days(lowered) or _optional_int(profile.get("days"))
    month = _month(lowered)
    children = bool(re.search(r"\b(children|child|kids|watoto|mtoto)\b", lowered)) or bool(profile.get("children"))
    wants_beach = _beach_preference(lowered, profile)
    wants_wildlife = bool(
        re.search(r"\b(wildlife|animals|safari|wanyamapori|game)\b", lowered)
        or "wildlife" in [item.lower() for item in profile.get("interests", [])]
    )
    visitor_category = _visitor_category(lowered)
    mentions_price = bool(
        re.search(r"\b(how much|cost|fee|fees|price|prices|tariff|gharama|ada|bei|ngapi|makadirio)\b", lowered)
        or re.search(r"\b(tsh|usd|\$|tzs)\b", lowered)
        or bool(re.search(r"\d[\d,]{2,}", lowered))
    )
    unsupported = [term for term in UNSUPPORTED_TERMS if term in lowered]
    if re.search(r"\bhelicopters?\b", lowered):
        unsupported.append("helicopter")
    scope_hits = [label for needle, label in SCOPE_TERMS.items() if needle in lowered]
    origin = (profile.get("origin") or profile.get("starting_location") or "").strip() or None
    adults = _optional_int(profile.get("adults"))
    child_ages = []
    for item in profile.get("child_ages") or []:
        age = _optional_int(item)
        if age is not None and 0 <= age <= 120:
            child_ages.append(age)
    if child_ages:
        children = True
    animal = next((word for word in ANIMALS if re.search(rf"\b{word}\b", lowered)), None)
    if animal in SWAHILI_ANIMALS:
        animal = SWAHILI_ANIMALS[animal]
    intent = _intent(
        lowered,
        days=days,
        mentions_price=mentions_price,
        unsupported=unsupported,
        animal=animal,
        wants_wildlife=wants_wildlife,
        scope_hits=scope_hits,
        park_slugs=park_slugs,
    )
    fee_keyword = next((term for term in sorted(FEE_CATEGORY_TERMS, key=len, reverse=True) if re.search(rf"\b{re.escape(term)}\b", lowered)), None)
    retrieval_query = _expand(lowered, language, park_slugs, history)
    return UnderstoodQuery(
        raw=raw,
        language=language,
        retrieval_query=retrieval_query,
        intent=intent,
        park_slugs=park_slugs,
        days=days,
        month=month,
        children=children,
        wants_beach=wants_beach,
        wants_wildlife=wants_wildlife,
        visitor_category=visitor_category,
        mentions_price=mentions_price,
        unsupported_terms=sorted(set(unsupported)),
        scope_hits=scope_hits,
        origin=origin,
        animal=animal,
        adults=adults,
        child_ages=child_ages,
        fee_category=FEE_CATEGORY_TERMS.get(fee_keyword) if fee_keyword else None,
        fee_keyword=fee_keyword,
    )


def _language(text: str) -> str:
    tokens = set(re.findall(r"[a-z]+", text))
    hits = tokens & SWAHILI_MARKERS
    return "sw" if len(hits) >= 2 else "en"


def _expand(text: str, language: str, park_slugs: list[str], history: list[dict]) -> str:
    extra = []
    if language == "sw":
        for marker, expansion in SWAHILI_EXPANSIONS.items():
            if re.search(rf"\b{marker}\b", text):
                extra.append(expansion)
    if park_slugs:
        extra.extend(park_slugs)
    if history and not park_slugs:
        prior = " ".join(str(turn.get("content", "")) for turn in history[-4:])
        extra.append(prior)
    return f"{text} {' '.join(extra)}".strip()


def _parks_in_text(text: str, parks: list[Park]) -> list[str]:
    found: list[str] = []
    for park in parks:
        matched = False
        for phrase in park.strict_aliases:
            if phrase.lower() in text:
                matched = True
                break
        if not matched:
            for alias in park.aliases:
                if re.search(rf"\b{re.escape(alias.lower())}\b", text):
                    matched = True
                    break
        if matched:
            found.append(park.slug)
    return found


def _days(text: str) -> int | None:
    numeric = re.search(r"\b(\d{1,2})\s*(day|days|siku)\b", text)
    if numeric:
        return int(numeric.group(1))
    word = re.search(r"\bsiku\s+([a-z]+)\b", text)
    if word and word.group(1) in SWAHILI_NUMBERS:
        return SWAHILI_NUMBERS[word.group(1)]
    return None


def _month(text: str) -> str | None:
    for month in MONTHS:
        if re.search(rf"\b{month}\b", text):
            return month
    return None


def _beach_preference(text: str, profile: dict) -> bool | None:
    interests = [item.lower() for item in profile.get("interests", [])]
    if re.search(r"\b(no|not|without|skip|si|sio)\b.{0,12}\b(beach|beaches|pwani|ufukwe)\b", text):
        return False
    if re.search(r"\b(beach|beaches|ufukwe|pwani)\b", text):
        return True
    if "beach" in interests:
        return True
    return None


def _visitor_category(text: str) -> str | None:
    if re.search(r"\b(nida|tanzanian citizen|raia wa tanzania|citizen)\b", text):
        return "citizen"
    if re.search(r"\b(non[- ]resident|foreigner|international|mgeni)\b", text):
        return "non_resident"
    if re.search(r"\b(east african|eac)\b", text):
        return "eac_citizen"
    if re.search(r"\b(resident|expatriate|mkazi)\b", text):
        return "resident"
    return None


def _optional_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _intent(
    text: str,
    *,
    days: int | None,
    mentions_price: bool,
    unsupported: list[str],
    animal: str | None,
    wants_wildlife: bool,
    scope_hits: list[str],
    park_slugs: list[str],
) -> str:
    if unsupported or (mentions_price and re.search(r"\b(tomorrow|kesho)\b", text) and scope_hits):
        return "unsupported"
    if re.search(r"\b(ngorongoro|zanzibar)\b", text):
        return "scope"
    if re.search(r"\b(visa|viza|passport|pasipoti|evisa|immigration)\b", text):
        return "visa"
    if mentions_price or re.search(r"\b(entry fee|conservation fee|park fee|fees|tariffs?|ada|kiingilio)\b", text):
        return "fee"
    if re.search(r"\b(phone|email|contact|call|address|mawasiliano|simu)\b", text):
        return "contact"
    if re.search(r"\b(accommodation|lodges?|stay|sleep|hotels?|cottages?|bandas?|hostels?|camp|camping|campsites?|kambi|malazi|kulala)\b", text):
        return "accommodation"
    if re.search(r"\b(best time|when to visit|season|lini)\b", text):
        return "season"
    if re.search(
        r"\b(camp|camping|kambi|own car|vehicle|break down|breakdown|food|children enter|child enter|nida|permit|permits)\b",
        text,
    ) or "what documents" in text:
        return "rules"
    if re.search(r"\b(safety|dangerous|attack|breakdown|breaks down)\b", text):
        return "safety"
    if any(term in text for term in ACTIVITY_TERMS) and not re.search(r"\b(plan|itinerary|panga|days?|siku)\b", text):
        return "activity"
    if park_slugs and re.search(r"\b(kwenda|nahitaji|twende|enda|visit|go|plan|panga|safari)\b", text):
        return "planning"
    if animal and (park_slugs or re.search(r"\b(see|find|watch|ona|kuona|are there|can i|where)\b", text)):
        return "wildlife"
    if park_slugs and re.fullmatch(r"(ndio|ndiyo|yes|yeah|sawa|ok|okay|haya|tafadhali)", text.strip()):
        return "planning"
    if days or re.search(r"\b(which parks|plan|itinerary|recommend|consider|shortlist|nataka|nahitaji|panga)\b", text):
        return "planning"
    if wants_wildlife and re.search(r"\b(which|where|recommend)\b", text):
        return "planning"
    if re.search(r"\b(how big|area|size|where is|established|when was|ukubwa|eneo)\b", text):
        return "park_fact"
    if scope_hits and not wants_wildlife:
        return "scope"
    return "general"
