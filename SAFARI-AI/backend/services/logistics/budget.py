"""A trip budget from a Tanzanian town to a national park, every line labelled by where its number comes from.

Groups:
- live: fetched for this trip (hotel rates for the dates, today's exchange rate)
- official: published tables in force on the travel date (TANAPA fees, EWURA fuel caps, LATRA bus fares)
- estimate: our assumption on top of official prices (fuel used = distance × consumption)

Nothing is invented: when there is no source for a cost (safari vehicle hire, food, NCAA transit, boat legs)
it is listed under "not included" instead of being guessed. A buffer covers price moves on the live and
estimated lines.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from services.knowledge import tariffs
from services.logistics import fuel, hotels
from services.logistics.fx import LiveFx, fee_usd
from services.logistics.places import ORIGINS, PARKS, Place, find_origin, nearest_arrival, origin_names
from services.logistics.routing import Router
from services.sources.tanapa_api import TARIFF_PAGE

# LATRA long-distance fare caps, TZS per passenger-km, gazetted 17 April 2026, in force from 1 May 2026.
LATRA_RATES = {
    "semi_luxury_paved": 74.18,
    "ordinary_paved": 57.93,
    "ordinary_gravel": 66.62,
}
LATRA_EFFECTIVE = "2026-05-01"
LATRA_URL = "https://www.thecitizen.co.tz/tanzania/news/national/tanzania-announces-new-fares-after-fuel-prices-increase-5428338"
LITRES_PER_100KM = 12.0  # a 4x4 safari vehicle on mixed roads
VEHICLE_ITEM = "Vehicles 2001 to 3000"  # a typical 4x4 (Land Cruiser Prado class)
BUFFER = 0.10
TRANSPORT = ("self_drive", "bus")
STAY = ("hotel", "camping", "none")


@dataclass
class TripRequest:
    park_slug: str
    park_name: str
    origin: str
    travel_date: date
    days: int
    adults: int
    child_ages: list[int]
    visitor: str
    transport: str = "self_drive"
    stay: str = "hotel"
    currency: str | None = None


class Logistics:
    """Holds the live connectors (exchange rate, routing, hotel rates) so their caches are shared."""

    def __init__(self, store, data_dir: Path, tanapa_rate: float) -> None:
        self.store = store
        self.tanapa_rate = tanapa_rate
        self.fx = LiveFx(store, tanapa_rate)
        self.router = Router(data_dir / "cache" / "routes.json")
        self.rates = hotels.RateCache()

    def refresh(self, *, force: bool = False) -> dict:
        report = {"fx": self.fx.refresh(), "fuel": fuel.refresh(self.store, force=force)}
        if force or hotels.directory_age_days(self.store) >= 7:
            report["hotels"] = hotels.refresh_directory(self.store)
        return report

    def refresh_due(self) -> dict:
        """What the hourly server loop runs: fuel daily, the hotel list weekly, and either one again
        after an hour when its last attempt failed (so one bad fetch doesn't leave a day-long gap)."""
        status = {item["id"]: item for item in self.store.source_status()}
        report = {}
        fuel_status = status.get(fuel.SOURCE_ID, {})
        if _hours_since(fuel_status.get("last_attempt")) >= (1 if fuel_status.get("status") == "error" else 24):
            report["fuel"] = fuel.refresh(self.store)
        hotel_status = status.get(hotels.SOURCE_ID, {})
        if hotels.directory_age_days(self.store) >= 7 and _hours_since(hotel_status.get("last_attempt")) >= 1:
            report["hotels"] = hotels.refresh_directory(self.store)
        return report

    def budget(self, request: TripRequest) -> dict:
        origin = find_origin(request.origin)
        access = PARKS.get(request.park_slug)
        if origin is None:
            return {"error": f"'{request.origin}' is not a town I can route from yet", "known_towns": origin_names()}
        if access is None:
            return {"error": f"No road access data for {request.park_name}"}
        return _Builder(self, request, origin, access).build()


class _Builder:
    def __init__(self, logistics: Logistics, request: TripRequest, origin: Place, access) -> None:
        self.lx = logistics
        self.req = request
        self.origin = origin
        self.access = access
        self.arrival = nearest_arrival(access, origin)
        self.lines: list[dict] = []
        self.excluded: list[str] = []
        self.notes: list[str] = []
        self.sources: dict[str, dict] = {}

    def build(self) -> dict:
        req = self.req
        days = max(1, int(req.days or 1))
        people = max(0, int(req.adults or 0)) + len(req.child_ages)
        if people == 0:
            return {"error": "Say how many people are travelling"}
        route = self.lx.router.route(self.origin.lat, self.origin.lon, self.arrival.lat, self.arrival.lon)
        self._source("route", route["source"], "https://www.openstreetmap.org/copyright", None, route["live"])
        if route.get("hours") and route["hours"] > 9:
            self.notes.append(f"The road trip is about {route['hours']:g} hours each way. Plan an overnight stop on the way; it is not counted here.")
        if req.transport == "bus":
            self._bus(route, people)
        else:
            self._drive(route, days)
        self._park_fees(days)
        nights = max(0, days - 1)
        if nights:
            if req.stay == "camping":
                self._camping(nights)
            elif req.stay == "hotel":
                self._hotel(nights, people)
        for note in (self.arrival.note, self.access.note):
            if note:
                self.notes.append(note)
        self.excluded += [
            "Food and drinks",
            "Guide, cook and tips",
            "Activities beyond entry (walking safari, balloon, night drive): ask for those fees",
        ]
        if self.access.boat_or_flight:
            self.excluded.insert(0, "Boat or charter flight to the park")
        return self._finish(route, days, nights, people)

    # Lines ----------------------------------------------------------------

    def _drive(self, route: dict, days: int) -> None:
        out_price = fuel.price(self.lx.store, self.origin.fuel_town)
        back_price = fuel.price(self.lx.store, self.arrival.fuel_town)
        if out_price and back_price:
            litres_each_way = route["km"] * LITRES_PER_100KM / 100
            total = litres_each_way * (out_price["tzs_per_litre"] + back_price["tzs_per_litre"])
            self._line(
                "estimate",
                "Fuel, return trip by road",
                f"{_n(route['km'] * 2)} km × {LITRES_PER_100KM:g} L/100 km = {_n(litres_each_way * 2)} L of diesel at EWURA cap prices "
                f"({out_price['town']} TZS {_n(out_price['tzs_per_litre'])}/L, {back_price['town']} TZS {_n(back_price['tzs_per_litre'])}/L)",
                total,
                "fuel",
            )
            self._source("fuel", f"EWURA cap prices effective {out_price['effective']}", out_price["source_url"], out_price["effective"], False)
            self.notes.append("Game drives inside the park use more fuel; that is not counted.")
        else:
            self.excluded.append("Fuel (EWURA prices not loaded yet)")
        row = None if self.access.boat_or_flight else self._tariff_row("Vehicles", "local_vehicle", VEHICLE_ITEM)
        if row:
            self._line(
                "official",
                "Vehicle entry, Tanzania-registered 4x4 (2,001 to 3,000 kg)",
                f"TZS {_n(row['amount'])} × {days} day(s); counted per 24 hours like conservation fees, confirm at the gate",
                row["amount"] * days,
                "tanapa",
                usd=fee_usd(row["amount"] * days, "local_vehicle", self.lx.fx, self.lx.tanapa_rate)[0],
            )

    def _bus(self, route: dict, people: int) -> None:
        rate = LATRA_RATES["semi_luxury_paved"]
        fare = math.ceil(route["km"] * rate / 500) * 500  # bus fares are in round 500s
        self._line(
            "official",
            f"Bus, {self.origin.name} to {self.arrival.name} and back",
            f"{_n(route['km'])} km × TZS {rate} per km (LATRA semi-luxury cap) ≈ TZS {_n(fare)} per person each way × 2 × {people} people. "
            f"Ordinary buses are capped at TZS {LATRA_RATES['ordinary_paved']}/km.",
            fare * 2 * people,
            "latra",
        )
        self._source("latra", "LATRA long-distance fare caps (Government Gazette 17 April 2026)", LATRA_URL, LATRA_EFFECTIVE, False)
        self.notes.append("Long-distance buses stop in towns, not at park gates. Children may pay less; ask the bus company.")
        self.excluded.insert(0, "Safari vehicle with driver for game drives (ask a licensed operator for a quote)")

    def _park_fees(self, days: int) -> None:
        req = self.req
        estimate = tariffs.estimate(
            self.lx.store, req.park_slug, req.park_name, req.travel_date, self.lx.tanapa_rate,
            days=days, adults=req.adults, child_ages=req.child_ages, visitor=req.visitor, fx=self.lx.fx,
        )
        if not estimate:
            self.excluded.insert(0, "Park entry fees (no TANAPA rate in force on the travel date)")
            return
        for line in estimate["lines"]:
            if not line["total_tzs"]:
                continue
            self._line(
                "official",
                line["label"],
                f"{line['qty']} × {line['days']} day(s) × TZS {_n(line['unit_tzs'])}",
                line["total_tzs"],
                "tanapa",
                usd=fee_usd(line["total_tzs"], req.visitor, self.lx.fx, self.lx.tanapa_rate)[0],
            )
        self._source("tanapa", f"TANAPA tariff in force on {req.travel_date.isoformat()}", TARIFF_PAGE, req.travel_date.isoformat(), False)

    def _camping(self, nights: int) -> None:
        req = self.req
        rows = tariffs.in_force_rows(self.lx.store, req.park_slug, req.travel_date, categories=("Public Camping",), visitors=(req.visitor,))
        adult = next((row for row in rows if row["age"] == "adult" and row["visitor"] == req.visitor), None)
        child = next((row for row in rows if row["age"] == "child_5_15" and row["visitor"] == req.visitor), None)
        if not adult:
            self.excluded.append("Camping (no public campsite fee published for this park and date)")
            return
        adults = req.adults + len([age for age in req.child_ages if age > 15])
        kids = len([age for age in req.child_ages if 5 <= age <= 15])
        total = adult["amount"] * adults * nights + (child["amount"] * kids * nights if child else 0)
        self._line(
            "official",
            "Public campsite inside the park",
            f"{nights} night(s): {adults} adult(s) × TZS {_n(adult['amount'])}" + (f", {kids} child(ren) × TZS {_n(child['amount'])}" if child and kids else ""),
            total,
            "tanapa",
            usd=fee_usd(total, req.visitor, self.lx.fx, self.lx.tanapa_rate)[0],
        )
        self.excluded.append("Tent and camping gear")

    def _hotel(self, nights: int, people: int) -> None:
        req = self.req
        # Same-day rates are often empty, so a trip dated today is priced from tomorrow.
        check_in = max(req.travel_date, date.today() + timedelta(days=1))
        found, priced, seen = [], [], set()
        # Many lodges near a gate list no online rate, so widen the circle until three have one.
        for radius in (self.access.hotel_radius_km, self.access.hotel_radius_km * 2, self.access.hotel_radius_km * 3):
            batch = hotels.nearby(self.lx.store, self.arrival.lat, self.arrival.lon, radius, exclude=seen)
            seen.update(item["key"] for item in batch)
            found += batch
            priced = sorted(priced + self.lx.rates.rates(batch, check_in, check_in + timedelta(days=1)), key=lambda row: row["usd_per_night"])
            if len(priced) >= 3:
                break
        if not found:
            if not self.lx.store.count_records(hotels.RECORD_KIND):
                self.excluded.append("Accommodation (the hotel list has not loaded yet; try again shortly)")
            else:
                self.excluded.append("Accommodation (no listed hotels near the park; check the park's own bandas and campsites)")
            return
        if not priced:
            self.excluded.append("Accommodation (booking sites returned no rates for these dates)")
            self.hotel_options = [{**item, "usd_per_night": None} for item in found[:4]]
            return
        summary = hotels.summarise(priced)
        rooms = max(1, math.ceil(max(1, req.adults) / 2))
        usd_rate = self.lx.fx.rate("USD") or self.lx.tanapa_rate
        per_night_tzs = summary["median_usd"] * usd_rate
        self._line(
            "live",
            f"Hotel near {self.arrival.name}, {nights} night(s)",
            f"Median of {summary['count']} nearby hotels: USD {summary['median_usd']:g} per room per night "
            f"(from USD {summary['lowest_usd']:g}) × {rooms} room(s) × {nights} night(s), converted at today's rate",
            per_night_tzs * rooms * nights,
            "hotels",
            usd=round(summary["median_usd"] * rooms * nights, 2),
        )
        self.hotel_options = priced[:5]
        if priced[-1]["km"] and priced[-1]["km"] > self.access.hotel_radius_km:
            self.notes.append(f"Few lodges near {self.arrival.name} list online rates, so hotels up to {priced[-1]['km']:g} km away are included.")
        self.hotel_summary = {**summary, "rooms": rooms, "nights": nights, "check_in": check_in.isoformat()}
        self._source("hotels", f"Live rates from booking sites for {check_in.isoformat()} (Xotelo)", hotels.SITE, check_in.isoformat(), True)
        self.notes.append("Room count assumes two adults per room with children sharing. Rates are per room per night as booking sites list them; some add taxes at checkout.")

    # Assembly -------------------------------------------------------------

    def _finish(self, route: dict, days: int, nights: int, people: int) -> dict:
        fx = self.lx.fx
        fx_meta = fx.meta()
        self._source("fx", fx_meta["source"], fx_meta["source_url"], fx_meta["date"], fx_meta["live"])
        groups = {name: round(sum(line["total_tzs"] for line in self.lines if line["group"] == name)) for name in ("live", "official", "estimate")}
        subtotal = sum(groups.values())
        buffer = round((groups["live"] + groups["estimate"]) * BUFFER)
        total = subtotal + buffer
        currency = (self.req.currency or "").upper()
        extra = None
        if currency and currency not in {"USD", "TZS"} and fx.rate(currency):
            extra = {"code": currency, "total": fx.to(total, currency), "rate": round(fx.rate(currency), 4)}
        for line in self.lines:
            if line.get("usd") is None:
                line["usd"] = fx.to(line["total_tzs"], "USD")
        return {
            "type": "trip_budget",
            "park_slug": self.req.park_slug,
            "park_name": self.req.park_name,
            "origin": self.origin.name,
            "arrival": {"name": self.arrival.name, "label": self.arrival.label},
            "route": {"km": route["km"], "hours": route["hours"], "live": route["live"]},
            "transport": self.req.transport,
            "stay": self.req.stay,
            "travel_date": self.req.travel_date.isoformat(),
            "days": days,
            "nights": nights,
            "people": people,
            "visitor": self.req.visitor,
            "lines": self.lines,
            "groups": groups,
            "subtotal_tzs": subtotal,
            "buffer_rate": BUFFER,
            "buffer_tzs": buffer,
            "total_tzs": total,
            "total_usd": fx.to(total, "USD"),
            "per_person_tzs": round(total / people),
            "currency": extra,
            "fx": fx_meta,
            "hotels": getattr(self, "hotel_options", []),
            "hotel_summary": getattr(self, "hotel_summary", None),
            "excluded": list(dict.fromkeys(self.excluded)),
            "notes": self.notes,
            "sources": list(self.sources.values()),
        }

    def _line(self, group: str, label: str, detail: str, total: float, source: str, usd: float | None = None) -> None:
        self.lines.append({"group": group, "label": label, "detail": detail, "total_tzs": round(total), "usd": usd, "source": source})

    def _source(self, key: str, title: str, url: str, as_of: str | None, live: bool) -> None:
        self.sources[key] = {"key": key, "title": title, "url": url, "as_of": as_of, "live": live}

    def _tariff_row(self, category: str, visitor: str, item_prefix: str) -> dict | None:
        rows = tariffs.in_force_rows(self.lx.store, self.req.park_slug, self.req.travel_date, categories=(category,), visitors=(visitor,))
        wanted = item_prefix.lower()
        return next((row for row in rows if row["visitor"] == visitor and row["item"].lower().startswith(wanted)), None)


def _hours_since(stamp: str | None) -> float:
    if not stamp:
        return float("inf")
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() / 3600
    except ValueError:
        return float("inf")


def _n(value: float) -> str:
    return f"{value:,.0f}"


__all__ = ["Logistics", "TripRequest", "ORIGINS", "TRANSPORT", "STAY"]
