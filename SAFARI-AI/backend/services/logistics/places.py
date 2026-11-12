"""Where trips start and where each park is reached by road.

Coordinates come from OpenStreetMap (Nominatim, looked up November 2026). `fuel_town` is the town name
as EWURA prints it in Table 3 of the monthly cap-price notice, so the origin's pump price can be read.
An arrival point is the main gate when OpenStreetMap has it, otherwise the town visitors stage from;
`label` says which.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Place:
    key: str
    name: str
    lat: float
    lon: float
    fuel_town: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Arrival:
    name: str
    lat: float
    lon: float
    label: str
    fuel_town: str
    note: str = ""


@dataclass(frozen=True)
class ParkAccess:
    slug: str
    arrivals: tuple[Arrival, ...]
    # Hotels are searched around this point; defaults to the chosen arrival.
    note: str = ""
    boat_or_flight: bool = False
    hotel_radius_km: float = 45.0
    extra: dict = field(default_factory=dict)


ORIGINS: dict[str, Place] = {
    place.key: place
    for place in (
        Place("dar-es-salaam", "Dar es Salaam", -6.8176, 39.2848, "Dar es Salaam", ("dar", "dsm", "dar es salaam", "daressalaam")),
        Place("arusha", "Arusha", -3.3697, 36.6881, "Arusha"),
        Place("moshi", "Moshi", -3.3486, 37.3435, "Kilimanjaro (Moshi)", ("kilimanjaro airport", "jro")),
        Place("mwanza", "Mwanza", -2.5197, 32.9014, "Mwanza"),
        Place("dodoma", "Dodoma", -6.1730, 35.7419, "Dodoma"),
        Place("morogoro", "Morogoro", -6.8235, 37.6612, "Morogoro"),
        Place("iringa", "Iringa", -7.7700, 35.6930, "Iringa"),
        Place("mbeya", "Mbeya", -8.9065, 33.4687, "Mbeya"),
        Place("tanga", "Tanga", -5.0691, 39.0977, "Tanga"),
        Place("kigoma", "Kigoma", -4.8769, 29.6267, "Kigoma", ("ujiji",)),
        Place("musoma", "Musoma", -1.4998, 33.8083, "Mara (Musoma)"),
        Place("bukoba", "Bukoba", -1.3312, 31.8126, "Kagera (Bukoba)"),
        Place("mtwara", "Mtwara", -10.2736, 40.1828, "Mtwara"),
        Place("lindi", "Lindi", -9.9989, 39.7137, "Lindi"),
        Place("songea", "Songea", -10.6787, 35.6484, "Ruvuma (Songea)"),
        Place("tabora", "Tabora", -5.0167, 32.8000, "Tabora"),
        Place("singida", "Singida", -4.8167, 34.7500, "Singida"),
        Place("shinyanga", "Shinyanga", -3.6619, 33.4232, "Shinyanga"),
        Place("babati", "Babati", -4.2101, 35.7491, "Manyara (Babati)"),
        Place("sumbawanga", "Sumbawanga", -7.9524, 31.6232, "Rukwa (Sumbawanga)"),
        Place("mpanda", "Mpanda", -6.3430, 31.0730, "Katavi (Mpanda)"),
        Place("njombe", "Njombe", -9.3333, 34.7667, "Njombe"),
        Place("geita", "Geita", -2.8708, 32.2341, "Geita"),
        Place("bariadi", "Bariadi", -2.5313, 34.5560, "Simiyu (Bariadi)"),
        Place("kahama", "Kahama", -3.8290, 32.6012, "Kahama"),
        Place("bagamoyo", "Bagamoyo", -6.4422, 38.9062, "Bagamoyo"),
        Place("kibaha", "Kibaha", -6.7864, 38.9920, "Pwani (Kibaha)"),
        Place("same", "Same", -4.0682, 37.7438, "Same"),
        Place("korogwe", "Korogwe", -5.1592, 38.4523, "Korogwe"),
        Place("makambako", "Makambako", -8.8440, 34.8230, "Makambako"),
        Place("ifakara", "Ifakara", -8.1321, 36.6848, "Kilombero (Ifakara)"),
        Place("mafinga", "Mafinga", -8.3015, 35.2989, "Mufindi (Mafinga)"),
        Place("karatu", "Karatu", -3.3387, 35.6733, "Karatu"),
        Place("usa-river", "Usa River", -3.3714, 36.8582, "Arumeru (Usa River)"),
        Place("mikumi", "Mikumi", -7.4049, 36.9770, "Mikumi"),
    )
}


def _arrival(name: str, lat: float, lon: float, label: str, fuel_town: str, note: str = "") -> Arrival:
    return Arrival(name, lat, lon, label, fuel_town, note)


PARKS: dict[str, ParkAccess] = {
    access.slug: access
    for access in (
        ParkAccess(
            "serengeti",
            (
                _arrival(
                    "Naabi Hill Gate", -2.8331, 34.9979, "main gate (from Arusha, through Ngorongoro Conservation Area)", "Karatu",
                    note="The road to Naabi Hill crosses Ngorongoro Conservation Area, which charges its own NCAA transit fees (not TANAPA, not included).",
                ),
                _arrival("Ndabaka Gate", -2.1464, 33.8818, "western gate (from Mwanza)", "Bunda"),
            ),
        ),
        ParkAccess("tarangire", (_arrival("Tarangire Main Gate", -3.7378, 35.9709, "main gate", "Monduli-Makuyuni"),)),
        ParkAccess("lake-manyara", (_arrival("Mto wa Mbu", -3.3767, 35.8558, "town at the main gate", "Monduli-Makuyuni"),)),
        ParkAccess(
            "arusha",
            (
                _arrival("Ngongongare Gate", -3.3199, 36.8797, "main gate", "Arumeru (Usa River)"),
                _arrival("Momella Gate", -3.2333, 36.8501, "Momella gate", "Arumeru (Usa River)"),
            ),
        ),
        ParkAccess(
            "kilimanjaro",
            (
                _arrival("Marangu Gate", -3.2436, 37.5177, "Marangu route gate", "Kilimanjaro (Moshi)"),
                _arrival("Machame Gate", -3.1737, 37.2390, "Machame route gate", "Hai (Bomang'ombe)"),
            ),
        ),
        ParkAccess("mkomazi", (_arrival("Zange Gate", -4.0591, 37.8078, "main gate near Same", "Same"),)),
        ParkAccess("mikumi", (_arrival("Mikumi", -7.4049, 36.9770, "town on the highway by the park", "Mikumi"),)),
        ParkAccess(
            "nyerere",
            (
                _arrival("Mtemere Gate", -7.7550, 38.2286, "eastern gate (from Dar es Salaam)", "Rufiji"),
                _arrival("Matambwe Gate", -7.5343, 37.7630, "northern gate (from Morogoro)", "Morogoro"),
            ),
        ),
        ParkAccess("ruaha", (_arrival("Ruaha Main Gate", -7.7469, 34.9652, "main gate", "Iringa"),)),
        ParkAccess("udzungwa", (_arrival("Mang'ula", -7.8569, 36.8962, "park headquarters", "Kilombero (Ifakara)"),)),
        ParkAccess("kitulo", (_arrival("Matamba", -9.1574, 33.8324, "village at the park", "Busokelo (lwangwa)"),)),
        ParkAccess("saadani", (_arrival("Saadani", -6.0442, 38.7779, "village in the park", "Pangani"),)),
        ParkAccess("katavi", (_arrival("Sitalike", -6.6214, 31.1408, "village at the main gate", "Katavi (Mpanda)"),)),
        ParkAccess(
            "mahale",
            (_arrival("Kigoma", -4.8769, 29.6267, "town where the boat or charter flight leaves", "Kigoma"),),
            note="Mahale is reached by boat on Lake Tanganyika or by charter flight from Kigoma. That leg is not priced here.",
            boat_or_flight=True,
        ),
        ParkAccess(
            "gombe",
            (_arrival("Kigoma", -4.8769, 29.6267, "town where the boat leaves", "Kigoma"),),
            note="Gombe is reached by boat from Kigoma. That leg is not priced here.",
            boat_or_flight=True,
        ),
        ParkAccess("ugalla", (_arrival("Ugalla River National Park", -5.5634, 31.7946, "park area (no gate on the map)", "Tabora"),)),
        ParkAccess(
            "rubondo",
            (_arrival("Muganza", -2.3758, 31.7358, "town where the park boat leaves", "Chato"),),
            note="Rubondo Island is reached by park boat from Muganza. That leg is not priced here.",
            boat_or_flight=True,
        ),
        ParkAccess(
            "saanane",
            (_arrival("Mwanza", -2.5197, 32.9014, "city where the park boat leaves", "Mwanza"),),
            note="Saanane Island is a short park boat ride from Mwanza. That leg is not priced here.",
            boat_or_flight=True,
        ),
        ParkAccess("burigi-chato", (_arrival("Biharamulo", -2.6340, 31.3110, "town at the park", "Biharamulo"),)),
        ParkAccess("ibanda-kyerwa", (_arrival("Kyerwa", -1.3707, 30.7934, "town at the park", "Kyerwa (Ruberwa)"),)),
        ParkAccess("rumanyika-karagwe", (_arrival("Kayanga", -1.5303, 31.1511, "town at the park", "Karagwe (Kayanga)"),)),
    )
}


def find_origin(text: str | None, *, after_from: bool = False) -> Place | None:
    """The known town named in `text`: the whole value first, then a town mentioned in it.

    With `after_from` (free text such as a question) only a town after "from", "kutoka" and the like
    counts, so "I want to go to Mikumi" doesn't make Mikumi the starting point."""
    if not text:
        return None
    value = _norm(text)
    for place in ORIGINS.values():
        if value in {_norm(place.name), place.key.replace("-", " "), *(_norm(alias) for alias in place.aliases)}:
            return place
    match = re.search(r"\b(?:from|kutoka|starting in|starting from|based in|leaving|nikitokea|tukitokea)\s+([a-z' ]{3,40})", value)
    if after_from and not match:
        return None
    tail = match.group(1) if match else value
    best = None
    for place in ORIGINS.values():
        for name in (place.name, *place.aliases):
            needle = _norm(name)
            if re.search(rf"\b{re.escape(needle)}\b", tail) and (best is None or len(needle) > best[0]):
                best = (len(needle), place)
    return best[1] if best else None


def origin_names() -> list[str]:
    return sorted(place.name for place in ORIGINS.values())


def nearest_arrival(access: ParkAccess, origin: Place) -> Arrival:
    return min(access.arrivals, key=lambda arrival: haversine_km(origin.lat, origin.lon, arrival.lat, arrival.lon))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z' ]", " ", value.lower())).strip()
