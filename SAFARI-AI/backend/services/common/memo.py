"""A small in-process cache for expensive read-only views (dashboard numbers, inventory, listings).

Callers put everything the result depends on into the key, usually the store version and the
analytics version, so a write produces a new key and the next read recomputes. Entries also expire
after `ttl` seconds, so a write the process cannot see (another process sharing the database) is
picked up within that time.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Callable, Hashable, TypeVar

T = TypeVar("T")
log = logging.getLogger("safari.memo")


class Memo:
    def __init__(self, ttl: float = 300.0, size: int = 64) -> None:
        self.ttl = ttl
        self.size = size
        self._items: OrderedDict[Hashable, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()
        self._building: dict[Hashable, threading.Lock] = {}
        self._refreshing: set[Hashable] = set()

    def get(self, key: Hashable, compute: Callable[[], T]) -> T:
        hit = self._fresh(key)
        if hit is not None:
            return hit[1]  # type: ignore[return-value]
        # One computation per key at a time: concurrent requests for the same view wait for it.
        with self._lock:
            building = self._building.setdefault(key, threading.Lock())
        with building:
            hit = self._fresh(key)
            if hit is not None:
                return hit[1]  # type: ignore[return-value]
            value = compute()
            self._store(key, value)
            with self._lock:
                self._building.pop(key, None)
            return value

    def serve(self, key: Hashable, version: Hashable, compute: Callable[[], T], max_age: float = 60.0) -> T:
        """Stale-while-revalidate: the stored value comes back at once, and when its version or age is
        out of date one background thread recomputes it for the next caller. Only the very first call
        for a key waits for `compute`."""
        with self._lock:
            hit = self._items.get(key)
        if hit is not None:
            stamp, (stored_version, value) = hit  # type: ignore[misc]
            if stored_version != version or time.monotonic() - stamp > max_age:
                self._refresh_later(key, version, compute)
            return value
        value = compute()
        self._store(key, (version, value))
        return value

    def refresh(self, key: Hashable, version: Hashable, compute: Callable[[], T]) -> T:
        """Recompute now and store, for an explicit refresh."""
        value = compute()
        self._store(key, (version, value))
        return value

    def _refresh_later(self, key: Hashable, version: Hashable, compute: Callable[[], object]) -> None:
        with self._lock:
            if key in self._refreshing:
                return
            self._refreshing.add(key)

        def run() -> None:
            try:
                self._store(key, (version, compute()))
            except Exception:  # the stale value stays; the next call tries again
                log.exception("background refresh of %s failed", key)
            finally:
                with self._lock:
                    self._refreshing.discard(key)

        threading.Thread(target=run, name="memo-refresh", daemon=True).start()

    def _store(self, key: Hashable, value: object) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def _fresh(self, key: Hashable):
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return None
            if time.monotonic() - hit[0] > self.ttl:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return hit
