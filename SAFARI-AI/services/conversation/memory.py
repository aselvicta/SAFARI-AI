"""Per-session conversation memory with a time-to-live and a cap on sessions held."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict


class SessionMemory:
    def __init__(self, limit: int = 12, ttl_seconds: int = 6 * 3600, max_sessions: int = 5000) -> None:
        self.limit = limit
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self._sessions: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._lock = threading.Lock()

    def history(self, session_id: str | None) -> list[dict]:
        if not session_id:
            return []
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None or time.time() - entry[0] > self.ttl:
                self._sessions.pop(session_id, None)
                return []
            return list(entry[1])

    def remember(self, session_id: str | None, question: str, answer: str) -> None:
        if not session_id:
            return
        with self._lock:
            _stamp, turns = self._sessions.pop(session_id, (0.0, []))
            turns = [*turns, {"role": "user", "content": question}, {"role": "assistant", "content": answer}][-self.limit :]
            self._sessions[session_id] = (time.time(), turns)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)

    def forget(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
