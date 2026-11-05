"""Park cards: the 2024 GIS map facts merged with the live TANAPA park page."""

from __future__ import annotations

from services.common.models import Park

GIS_MAP_URL = "https://www.tanzaniaparks.go.tz/uploads/publications/en-1710606473-TNPMapENG.pdf"


def profiles(store) -> dict[str, dict]:
    return {record.key: record.payload for record in store.list_records("park_profile")}


def card(park: Park, profile: dict | None) -> dict:
    profile = profile or {}
    return {
        "slug": park.slug,
        "name": park.name,
        "zone": profile.get("zone") or "",
        "circuit": park.circuit,
        "area_km2": park.area_km2,
        "area_km2_site": profile.get("area_km2_site"),
        "established_year": park.established_year,
        "slogan": profile.get("slogan") or "",
        "summary": profile.get("summary") or _map_summary(park),
        "image_url": profile.get("image_url"),
        "temperature": profile.get("temperature_c") or "",
        "elevation": profile.get("elevation_m") or "",
        "interests": park.interests,
        "attractions": profile.get("attractions") or [],
        "contact": profile.get("contact") or {},
        "source_url": profile.get("page_url") or GIS_MAP_URL,
        "map_source_url": GIS_MAP_URL,
    }


def cards(store) -> list[dict]:
    known = profiles(store)
    return [card(park, known.get(park.slug)) for park in store.list_parks()]


def get_card(store, slug: str) -> dict | None:
    park = next((item for item in store.list_parks() if item.slug == slug), None)
    if park is None:
        return None
    profile = profiles(store).get(slug)
    result = card(park, profile)
    result["about"] = (profile or {}).get("about") or ""
    return result


def _map_summary(park: Park) -> str:
    from services.common.text import format_area

    parts = [f"{park.name} is in the {park.circuit} circuit"]
    if park.area_km2:
        parts.append(f"covering {format_area(park.area_km2)} km² on the 2024 TANAPA GIS map")
    if park.established_year:
        parts.append(f"established in {park.established_year}")
    return ", ".join(parts) + "."
