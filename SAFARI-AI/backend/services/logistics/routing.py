"""Road distance and driving time between two points, from OSRM over OpenStreetMap roads.

Routes barely change, so answers are cached on disk for 30 days. When OSRM can't be reached the
straight-line distance times 1.3 is used and the result says it is an approximation.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from services.logistics.places import haversine_km
from services.sources.http import Http

log = logging.getLogger("safari.routing")

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
SOURCE_URL = "https://www.openstreetmap.org/copyright"
CACHE_DAYS = 30
ROAD_FACTOR = 1.3


class Router:
    def __init__(self, cache_path: Path, http: Http | None = None) -> None:
        self.cache_path = cache_path
        self.http = http
        self._lock = threading.Lock()
        self._cache: dict[str, dict] | None = None

    def route(self, lat1: float, lon1: float, lat2: float, lon2: float) -> dict:
        """{km, hours, live, source}. Never raises."""
        key = f"{lat1:.4f},{lon1:.4f};{lat2:.4f},{lon2:.4f}"
        cache = self._load()
        hit = cache.get(key)
        if hit and time.time() - hit.get("at", 0) < CACHE_DAYS * 86400:
            return {key_: value for key_, value in hit.items() if key_ != "at"}
        found = self._osrm(lat1, lon1, lat2, lon2)
        if found:
            with self._lock:
                cache[key] = {**found, "at": time.time()}
                self._save(cache)
            return found
        if hit:  # an old answer is still better than a straight line
            return {key_: value for key_, value in hit.items() if key_ != "at"}
        straight = haversine_km(lat1, lon1, lat2, lon2)
        return {
            "km": round(straight * ROAD_FACTOR, 1),
            "hours": None,
            "live": False,
            "source": f"Approximation: straight-line distance × {ROAD_FACTOR} (the routing service could not be reached)",
        }

    def _osrm(self, lat1: float, lon1: float, lat2: float, lon2: float) -> dict | None:
        client = self.http or Http(timeout=15.0, retries=1)
        try:
            data = client.json(OSRM_URL.format(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2), params={"overview": "false"})
            if data.get("code") != "Ok" or not data.get("routes"):
                raise ValueError(data.get("code") or "no route")
            best = data["routes"][0]
            return {
                "km": round(best["distance"] / 1000, 1),
                "hours": round(best["duration"] / 3600, 1),
                "live": True,
                "source": "OSRM road routing over OpenStreetMap",
            }
        except Exception as exc:
            log.warning("routing failed: %s", exc)
            return None
        finally:
            if self.http is None:
                client.close()

    def _load(self) -> dict[str, dict]:
        with self._lock:
            if self._cache is None:
                try:
                    self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    self._cache = {}
            return self._cache

    def _save(self, cache: dict) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            tmp.replace(self.cache_path)
        except OSError as exc:
            log.warning("could not save route cache: %s", exc)
