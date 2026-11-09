"""Append-only logs behind the admin dashboard: one line per question, one per feedback.

Nothing here identifies a visitor. Session ids are hashed, IP addresses are never written.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.knowledge.tariffs import visitor_class

QUESTION_CHARS = 500


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_at(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return then if then.tzinfo else then.replace(tzinfo=timezone.utc)


class JsonLines:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read(self, since: datetime | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        with self._lock, self.path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since is not None:
                    at = parse_at(row.get("at"))
                    if at is None or at < since:
                        continue
                rows.append(row)
        return rows

    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


class StoreLines:
    """The JsonLines interface over a database store's append-only log (PostgresStore.append_log)."""

    def __init__(self, store, stream: str) -> None:
        self.store = store
        self.stream = stream

    def append(self, record: dict) -> None:
        self.store.append_log(self.stream, parse_at(record.get("at")) or datetime.now(timezone.utc), record)

    def read(self, since: datetime | None = None) -> list[dict]:
        return self.store.read_log(self.stream, since)

    def size_bytes(self) -> int:
        return self.store.log_bytes(self.stream)


class JsonDoc:
    """One JSON object kept in a file, or in the store's metadata when the store is a database."""

    def __init__(self, data_dir: Path, store, name: str) -> None:
        self.store = store if _has_logs(store) else None
        self.key = f"doc:{name}"
        self.path = data_dir / f"{name}.json"

    def load(self) -> dict:
        try:
            if self.store is not None:
                raw = self.store.get_meta(self.key)
                return json.loads(raw) if raw else {}
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except json.JSONDecodeError:
            return {}

    def save(self, value: dict) -> None:
        text = json.dumps(value, ensure_ascii=False)
        if self.store is not None:
            self.store.set_meta(self.key, text)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self.path)


def _has_logs(store) -> bool:
    return store is not None and hasattr(store, "append_log")


def open_lines(data_dir: Path, store, name: str) -> JsonLines | StoreLines:
    """A log in the database when the store has one (hosts without a disk), else a .jsonl file."""
    return StoreLines(store, name) if _has_logs(store) else JsonLines(data_dir / f"{name}.jsonl")


class Analytics:
    """Question events, feedback, and the review state an admin sets on feedback."""

    def __init__(self, data_dir: Path, store=None) -> None:
        self.events = open_lines(data_dir, store, "events")
        self.feedback = open_lines(data_dir, store, "feedback")
        self.reviews = JsonDoc(data_dir, store, "feedback_review")
        self._review_lock = threading.Lock()

    # Writes -------------------------------------------------------------

    def record_question(self, *, question: str, session_id: str | None, profile: dict, result: dict | None, latency_ms: float, channel: str, error: str | None = None) -> None:
        result = result or {}
        understood = result.get("understood") or {}
        self.events.append(
            {
                "at": _now(),
                "session": _hash(session_id),
                "channel": channel,
                "question": question.strip()[:QUESTION_CHARS],
                "language": result.get("language"),
                "intent": result.get("intent") or ("error" if error else None),
                "parks": understood.get("park_slugs") or [],
                "recommended": [park.get("slug") for park in result.get("recommended_parks") or [] if park.get("slug")],
                "animal": understood.get("animal"),
                "fee_category": understood.get("fee_category"),
                "scope": understood.get("scope_hits") or [],
                "generator": result.get("generator"),
                "abstained": bool(result.get("abstained")),
                "confidence": result.get("confidence"),
                "confidence_label": result.get("confidence_label"),
                "citations": len(result.get("citations") or []),
                "blocks": [block.get("type") for block in result.get("blocks") or []],
                "tools": result.get("tool_calls") or [],
                "latency_ms": round(latency_ms, 1),
                "passport": (profile.get("passport") or "").strip()[:60] or None,
                "visitor_class": visitor_class(profile)[0],
                "days": profile.get("days"),
                "adults": profile.get("adults"),
                "children": len(profile.get("child_ages") or []),
                "error": (error or "")[:200] or None,
            }
        )

    def record_feedback(self, payload: dict) -> dict:
        record = {"at": _now(), **payload, "session_id": _hash(payload.get("session_id"))}
        self.feedback.append(record)
        return record

    def set_review(self, feedback_id: str, *, status: str, note: str = "") -> dict:
        with self._review_lock:
            state = self._reviews()
            state[feedback_id] = {"status": status, "note": note[:1000], "at": _now()}
            self.reviews.save(state)
            return state[feedback_id]

    # Reads --------------------------------------------------------------

    def questions(self, days: int | None = None) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        return self.events.read(since)

    def feedback_items(self, days: int | None = None) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        reviews = self._reviews()
        items = []
        for row in self.feedback.read(since):
            item_id = feedback_id(row)
            review = reviews.get(item_id) or {}
            items.append(
                {
                    "id": item_id,
                    "at": row.get("at"),
                    "rating": row.get("rating", 0),
                    "question": row.get("question", ""),
                    "answer": row.get("answer", ""),
                    "comment": row.get("comment", ""),
                    "review_status": review.get("status", "open"),
                    "review_note": review.get("note", ""),
                    "reviewed_at": review.get("at"),
                }
            )
        return items

    def _reviews(self) -> dict:
        return self.reviews.load()


def feedback_id(row: dict) -> str:
    return hashlib.sha1(f"{row.get('at')}|{row.get('question', '')}|{row.get('rating')}".encode("utf-8")).hexdigest()[:16]
