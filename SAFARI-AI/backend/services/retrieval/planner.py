"""Trip shortlist over structured park tags.

The tags are SafariAI planning labels stored on each park profile. They are not
official TANAPA tourism zones and they are not a species list.
"""

from __future__ import annotations

from services.common.models import Park
from services.conversation.understand import UnderstoodQuery

PRIORITY = [
    "serengeti",
    "tarangire",
    "lake-manyara",
    "arusha",
    "mkomazi",
    "ruaha",
    "nyerere",
    "mikumi",
    "katavi",
    "gombe",
    "mahale",
    "udzungwa",
    "kitulo",
    "saadani",
    "rubondo",
    "saanane",
    "ugalla",
    "burigi-chato",
    "ibanda-kyerwa",
    "rumanyika-karagwe",
    "kilimanjaro",
]


DAR_SHORT = ["mikumi", "nyerere", "udzungwa"]


def shortlist(parks: list[Park], query: UnderstoodQuery, limit: int = 4) -> list[tuple[Park, str]]:
    if query.park_slugs:
        named = [park for park in parks if park.slug in query.park_slugs]
        if named:
            return [(park, _reason(park, query)) for park in named]
    chosen: list[Park] = []
    for park in parks:
        if query.wants_beach is False and park.beach:
            continue
        if query.wants_beach is True and not park.beach and "wildlife" not in query.raw.lower():
            continue
        if park.mountain_climb and query.wants_wildlife:
            continue
        if query.wants_wildlife and "wildlife" not in park.interests:
            continue
        chosen.append(park)

    dar_short = _from_dar(query.origin) and query.days is not None and query.days <= 4

    def sort_key(park: Park) -> tuple[int, int]:
        if dar_short and park.slug in DAR_SHORT:
            return (0, DAR_SHORT.index(park.slug))
        priority = PRIORITY.index(park.slug) if park.slug in PRIORITY else 100
        return (1, priority)

    chosen.sort(key=sort_key)
    results: list[tuple[Park, str]] = []
    for park in chosen[:limit]:
        results.append((park, _reason(park, query)))
    return results


def _from_dar(origin: str | None) -> bool:
    if not origin:
        return False
    lowered = origin.lower()
    return "dar" in lowered or "morogoro" in lowered


def _reason(park: Park, query: UnderstoodQuery) -> str:
    interests = ", ".join(park.interests) or "general visit"
    coast = "It is marked coastal, so a no-beach filter would drop it." if park.beach else "It is not marked as a coastal park."
    return (
        f"{park.name} is in the {park.circuit} planning circuit and tagged {interests}. {coast}"
    )
