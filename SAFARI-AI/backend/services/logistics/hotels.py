"""Hotels near a park and their live nightly rates, from Xotelo (TripAdvisor listings and the rates that
booking sites show for given dates).

The list of Tanzanian hotels with coordinates is refreshed weekly into the store (about 3,000 rows,
31 requests). Rates are asked for only when someone plans a trip, for a handful of the nearest hotels,
and cached for six hours per hotel and date.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from services.common.models import Record
from services.logistics.places import haversine_km
from services.sources.http import Http

log = logging.getLogger("safari.hotels")

API = "https://data.xotelo.com/api"
SITE = "https://xotelo.com"
TANZANIA = "g293747"
SOURCE_ID = "xotelo_hotels"
RECORD_KIND = "hotel_listing"
PAGE = 100
RATE_TTL = 6 * 3600
CANDIDATES = 12
SKIP_TYPES = {"Campground"}


def refresh_directory(store, http: Http | None = None) -> dict:
    client = http or Http(timeout=30.0, retries=2)
    started = _now()
    listings: list[dict] = []
    try:
        offset = 0
        while True:
            data = client.json(f"{API}/list", {"location_key": TANZANIA, "limit": PAGE, "offset": offset})
            if data.get("error"):
                raise ValueError(str(data["error"]))
            page = (data.get("result") or {}).get("list") or []
            listings.extend(page)
            total = (data.get("result") or {}).get("total_count") or 0
            offset += PAGE
            if not page or offset >= total or offset >= 6000:
                break
            time.sleep(0.3)
    except Exception as exc:
        log.warning("hotel directory refresh failed: %s", exc)
        _status(store, {"status": "error", "error": str(exc)[:300], "last_attempt": started})
        return {"status": "error", "error": str(exc)}
    finally:
        if http is None:
            client.close()
    records = []
    for item in listings:
        geo = item.get("geo") or {}
        if not item.get("key") or geo.get("latitude") is None:
            continue
        review = item.get("review_summary") or {}
        records.append(
            Record(
                RECORD_KIND,
                item["key"],
                {
                    "key": item["key"],
                    "name": item.get("name") or "",
                    "type": item.get("accommodation_type") or "",
                    "lat": float(geo["latitude"]),
                    "lon": float(geo["longitude"]),
                    "rating": review.get("rating"),
                    "reviews": review.get("count"),
                    "url": item.get("url") or "",
                },
                SOURCE_ID,
                f"{API}/list?location_key={TANZANIA}",
                started,
            )
        )
    if len(records) < 100:
        _status(store, {"status": "error", "error": f"only {len(records)} hotels listed", "last_attempt": started})
        return {"status": "error", "error": f"only {len(records)} hotels listed"}
    store.replace_records(RECORD_KIND, records)
    _status(store, {"status": "ok", "error": None, "last_attempt": started, "last_success": started, "records": {"hotels": len(records)}})
    return {"status": "ok", "hotels": len(records)}


def directory_age_days(store) -> float:
    status = {item["id"]: item for item in store.source_status()}.get(SOURCE_ID, {})
    stamp = status.get("last_success")
    if not stamp:
        return float("inf")
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() / 86400
    except ValueError:
        return float("inf")


_listing_cache: dict[int, tuple[object, list[dict]]] = {}


def _listings(store) -> list[dict]:
    """The hotel list, read once per store version instead of on every budget."""
    version = getattr(store, "version", None)
    hit = _listing_cache.get(id(store))
    if hit and version is not None and hit[0] == version:
        return hit[1]
    rows = [record.payload for record in store.list_records(RECORD_KIND)]
    _listing_cache[id(store)] = (version, rows)
    return rows


def nearby(store, lat: float, lon: float, radius_km: float, limit: int = CANDIDATES, exclude: set[str] | None = None) -> list[dict]:
    found = []
    for row in _listings(store):
        if row.get("type") in SKIP_TYPES or (exclude and row["key"] in exclude):
            continue
        distance = haversine_km(lat, lon, row["lat"], row["lon"])
        if distance <= radius_km:
            found.append({**row, "km": round(distance, 1)})
    # Nearest first, but a well-reviewed place a few km further beats an unreviewed one next door.
    found.sort(key=lambda row: row["km"] - min(10.0, (row.get("reviews") or 0) / 50))
    return found[:limit]


class RateCache:
    def __init__(self, http: Http | None = None) -> None:
        self.http = http
        self._items: dict[tuple, tuple[float, dict | None]] = {}
        self._lock = threading.Lock()

    def rates(self, hotels: list[dict], check_in: date, check_out: date) -> list[dict]:
        """Hotels with a live rate: {..., usd_per_night, sites:[{name, usd}]}, cheapest first."""
        if not hotels:
            return []
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda hotel: self._one(hotel, check_in, check_out), hotels))
        priced = [row for row in results if row]
        priced.sort(key=lambda row: row["usd_per_night"])
        return priced

    def _one(self, hotel: dict, check_in: date, check_out: date) -> dict | None:
        key = (hotel["key"], check_in.isoformat(), check_out.isoformat())
        with self._lock:
            hit = self._items.get(key)
        if hit and time.time() - hit[0] < RATE_TTL:
            return hit[1]
        client = self.http or Http(timeout=20.0, retries=1)
        try:
            data = client.json(
                f"{API}/rates",
                {"hotel_key": hotel["key"], "chk_in": check_in.isoformat(), "chk_out": check_out.isoformat(), "currency": "USD"},
            )
            sites = [
                {"name": item.get("name") or item.get("code"), "usd": float(item["rate"]), "tax_usd": item.get("tax")}
                for item in ((data.get("result") or {}).get("rates") or [])
                if isinstance(item.get("rate"), (int, float)) and item["rate"] > 0
            ]
            result = None
            if sites:
                cheapest = min(sites, key=lambda site: site["usd"])
                result = {
                    "key": hotel["key"],
                    "name": hotel["name"],
                    "type": hotel.get("type"),
                    "km": hotel.get("km"),
                    "rating": hotel.get("rating"),
                    "reviews": hotel.get("reviews"),
                    "url": hotel.get("url"),
                    "usd_per_night": cheapest["usd"],
                    "cheapest_site": cheapest["name"],
                    "sites": sorted(sites, key=lambda site: site["usd"])[:4],
                }
        except Exception as exc:
            log.info("rate lookup failed for %s: %s", hotel.get("key"), exc)
            return None  # not cached: the next request tries again
        finally:
            if self.http is None:
                client.close()
        with self._lock:
            self._items[key] = (time.time(), result)
            if len(self._items) > 5000:
                for old in sorted(self._items, key=lambda item: self._items[item][0])[:1000]:
                    self._items.pop(old, None)
        return result


def summarise(priced: list[dict]) -> dict:
    prices = [row["usd_per_night"] for row in priced]
    return {
        "count": len(prices),
        "lowest_usd": min(prices) if prices else None,
        "median_usd": round(statistics.median(prices), 2) if prices else None,
        "highest_usd": max(prices) if prices else None,
    }


def _status(store, status: dict) -> None:
    store.set_source_status(SOURCE_ID, {"name": "Hotel rates (Xotelo, TripAdvisor listings)", "url": SITE, **status})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
