"""JSON knowledge store used for local runs and tests.

PostgreSQL + pgvector is the production store. This store implements the same
operations so the retrieval math can be tested without a database.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from services.common.models import Chunk, Document, Park, Record

CATALOG_VERSION_KEY = "catalog_version"


class JsonStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.documents: dict[str, Document] = {}
        self.chunks: list[Chunk] = []
        self.parks: dict[str, Park] = {}
        self.records: dict[str, dict[str, Record]] = {}
        self.sources: dict[str, dict] = {}
        self.meta: dict[str, str | int] = {}
        self.version = 0
        self._lock = threading.RLock()
        self._batch = 0
        if path and path.exists():
            self._load()

    # Writes -------------------------------------------------------------

    def batch(self) -> "_Batch":
        """Group many writes into one save: `with store.batch(): ...`."""
        return _Batch(self)

    def upsert_document(self, document: Document, chunks: list[Chunk]) -> None:
        with self._lock:
            self.documents[document.document_id] = document
            self.chunks = [chunk for chunk in self.chunks if chunk.document_id != document.document_id]
            self.chunks.extend(chunks)
            self._changed()

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self.documents.pop(document_id, None)
            self.chunks = [chunk for chunk in self.chunks if chunk.document_id != document_id]
            self._changed()

    def upsert_park(self, park: Park) -> None:
        with self._lock:
            self.parks[park.slug] = park
            self._changed()

    def replace_records(self, kind: str, records: list[Record]) -> None:
        """Swap every record of one kind, so rows removed at the source disappear here too."""
        with self._lock:
            self.records[kind] = {record.key: record for record in records}
            self._changed()

    def set_source_status(self, source_id: str, status: dict) -> None:
        with self._lock:
            self.sources[source_id] = {**self.sources.get(source_id, {}), **status, "id": source_id}
            self._changed()

    def set_meta(self, key: str, value: str | int) -> None:
        with self._lock:
            self.meta[key] = value
            self._changed()

    # Reads --------------------------------------------------------------

    def list_documents(self) -> list[Document]:
        return sorted(self.documents.values(), key=lambda item: item.title)

    def list_parks(self) -> list[Park]:
        return sorted(self.parks.values(), key=lambda item: item.name)

    def all_chunks(self) -> list[Chunk]:
        return list(self.chunks)

    def list_records(self, kind: str) -> list[Record]:
        return list(self.records.get(kind, {}).values())

    def source_status(self) -> list[dict]:
        return sorted(self.sources.values(), key=lambda item: item["id"])

    def fee_rows(self) -> list[tuple[Document, object]]:
        rows = []
        for document in self.documents.values():
            for fee in document.fees:
                rows.append((document, fee))
        return rows

    def get_document(self, document_id: str) -> Document | None:
        return self.documents.get(document_id)

    # Persistence --------------------------------------------------------

    def _changed(self) -> None:
        self.version += 1
        if self._batch == 0:
            self.save()

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "meta": self.meta,
                "documents": [document.to_dict() for document in self.documents.values()],
                "chunks": [chunk.to_dict() for chunk in self.chunks],
                "parks": [park.to_dict() for park in self.parks.values()],
                "records": {kind: [record.to_dict() for record in rows.values()] for kind, rows in self.records.items()},
                "sources": self.sources,
            }
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            temporary.replace(self.path)

    def _load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
        self.meta = raw.get("meta", {})
        self.documents = {item["document_id"]: Document.from_dict(item) for item in raw.get("documents", [])}
        self.chunks = [Chunk.from_dict(item) for item in raw.get("chunks", [])]
        self.parks = {item["slug"]: Park.from_dict(item) for item in raw.get("parks", [])}
        self.records = {
            kind: {item["key"]: Record.from_dict(item) for item in rows}
            for kind, rows in (raw.get("records") or {}).items()
        }
        self.sources = raw.get("sources") or {}


class _Batch:
    def __init__(self, store: JsonStore) -> None:
        self.store = store

    def __enter__(self) -> JsonStore:
        self.store._lock.acquire()
        self.store._batch += 1
        return self.store

    def __exit__(self, *exc) -> None:
        self.store._batch -= 1
        try:
            if self.store._batch == 0:
                self.store.save()
        finally:
            self.store._lock.release()
