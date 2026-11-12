"""PostgreSQL + pgvector store.

The hybrid score still runs in Python so the formula stays inspectable.
`semantic_candidates` is the ANN entry point for when the corpus no longer fits a full scan.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from datetime import datetime

from services.common.models import Chunk, Document, FeeRecord, Park, Record
from services.common.settings import ROOT

# Every statement in it is idempotent, so it runs on each start and a fresh database needs no manual setup.
SCHEMA_FILE = ROOT / "postgres" / "init.sql"
SUMMARY_COLUMNS = (
    "document_id, title, organization, document_type, language, authority, authority_score, status, version, "
    "published_date, effective_from, effective_until, retrieved_at, source_url, park_slug"
)
IDLE_PING_S = 30  # seconds a connection may sit unused before it is checked
SCHEMA_LOCK_ID = 7_310_442  # pg_advisory_lock key, so two instances starting together don't race


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._conn = None
        self._conn_lock = threading.Lock()
        self._last_used = 0.0
        self.version = 0
        self._ensure_schema()

    @property
    def conn(self):
        # Hosted poolers (Supabase) close idle connections. After a quiet spell, check the connection
        # with a cheap ping and reconnect, so the next visitor doesn't get the error.
        import psycopg
        from psycopg.rows import dict_row

        with self._conn_lock:
            now = time.monotonic()
            if self._conn is not None and not self._conn.closed and now - self._last_used > IDLE_PING_S:
                try:
                    self._conn.execute("SELECT 1")
                except psycopg.Error:
                    self._conn.close()
            if self._conn is None or self._conn.closed or self._conn.broken:
                self._conn = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)
            self._last_used = now
            return self._conn

    def _ensure_schema(self) -> None:
        if not SCHEMA_FILE.is_file():
            return
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK_ID,))
            try:
                cursor.execute(SCHEMA_FILE.read_text())
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK_ID,))

    def batch(self):
        return contextlib.nullcontext(self)

    def _changed(self) -> None:
        self.version += 1

    def delete_document(self, document_id: str) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE document_id = %s", (document_id,))
        self._changed()

    def replace_records(self, kind: str, records: list[Record]) -> None:
        with self.conn.transaction(), self.conn.cursor() as cursor:
            cursor.execute("DELETE FROM records WHERE kind = %s", (kind,))
            # One pipelined batch: the weekly hotel list is ~3,000 rows.
            cursor.executemany(
                "INSERT INTO records (kind, key, payload, source_id, source_url, retrieved_at) VALUES (%s, %s, %s, %s, %s, %s)",
                [(kind, record.key, json.dumps(record.payload), record.source_id, record.source_url, record.retrieved_at) for record in records],
            )
        self._changed()

    def list_records(self, kind: str) -> list[Record]:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT * FROM records WHERE kind = %s", (kind,))
            return [
                Record(
                    kind=row["kind"],
                    key=row["key"],
                    payload=row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"]),
                    source_id=row["source_id"],
                    source_url=row.get("source_url") or "",
                    retrieved_at=row.get("retrieved_at") or "",
                )
                for row in cursor.fetchall()
            ]

    def set_source_status(self, source_id: str, status: dict) -> None:
        current = {item["id"]: item for item in self.source_status()}.get(source_id, {})
        merged = {**current, **status, "id": source_id}
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO source_status (source_id, status) VALUES (%s, %s)
                ON CONFLICT (source_id) DO UPDATE SET status = EXCLUDED.status
                """,
                (source_id, json.dumps(merged)),
            )
        self._changed()

    def source_status(self) -> list[dict]:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT status FROM source_status ORDER BY source_id")
            return [row["status"] if isinstance(row["status"], dict) else json.loads(row["status"]) for row in cursor.fetchall()]

    def upsert_document(self, document: Document, chunks: list[Chunk]) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute("DELETE FROM documents WHERE document_id = %s", (document.document_id,))
            cursor.execute(
                """
                INSERT INTO documents (
                    document_id, title, organization, document_type, body, language, authority,
                    authority_score, status, version, published_date, effective_from, effective_until,
                    retrieved_at, source_url, park_slug
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    document.document_id,
                    document.title,
                    document.organization,
                    document.document_type,
                    document.text,
                    document.language,
                    document.authority,
                    document.authority_score,
                    document.status,
                    document.version,
                    document.published_date,
                    document.effective_from,
                    document.effective_until,
                    document.retrieved_at,
                    document.source_url,
                    document.park_slug,
                ),
            )
            cursor.execute(
                """
                INSERT INTO document_versions (
                    document_id, version, title, status, effective_from, effective_until, source_url
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document.document_id,
                    document.version,
                    document.title,
                    document.status,
                    document.effective_from,
                    document.effective_until,
                    document.source_url,
                ),
            )
            for chunk in chunks:
                cursor.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, document_id, position, body, embedding, title, organization,
                        document_type, language, authority, authority_score, status, version,
                        published_date, effective_from, effective_until, retrieved_at, source_url, park_slug
                    ) VALUES (
                        %s, %s, %s, %s, %s::vector, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.position,
                        chunk.text,
                        _vector(chunk.embedding),
                        chunk.title,
                        chunk.organization,
                        chunk.document_type,
                        chunk.language,
                        chunk.authority,
                        chunk.authority_score,
                        chunk.status,
                        chunk.version,
                        chunk.published_date,
                        chunk.effective_from,
                        chunk.effective_until,
                        chunk.retrieved_at,
                        chunk.source_url,
                        chunk.park_slug,
                    ),
                )
            for fee in document.fees:
                cursor.execute(
                    """
                    INSERT INTO fees (
                        document_id, park_slug, name, visitor_category, age_band, amount, currency, unit
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        document.document_id,
                        fee.park_slug,
                        fee.name,
                        fee.visitor_category,
                        fee.age_band,
                        fee.amount,
                        fee.currency,
                        fee.unit,
                    ),
                )
        self._changed()

    def upsert_park(self, park: Park) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO parks (
                    slug, name, area_km2, established_year, gazette, circuit, interests,
                    beach, mountain_climb, aliases, strict_aliases, source_url, source_title
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    area_km2 = EXCLUDED.area_km2,
                    established_year = EXCLUDED.established_year,
                    gazette = EXCLUDED.gazette,
                    circuit = EXCLUDED.circuit,
                    interests = EXCLUDED.interests,
                    beach = EXCLUDED.beach,
                    mountain_climb = EXCLUDED.mountain_climb,
                    aliases = EXCLUDED.aliases,
                    strict_aliases = EXCLUDED.strict_aliases,
                    source_url = EXCLUDED.source_url,
                    source_title = EXCLUDED.source_title
                """,
                (
                    park.slug,
                    park.name,
                    park.area_km2,
                    park.established_year,
                    park.gazette,
                    park.circuit,
                    park.interests,
                    park.beach,
                    park.mountain_climb,
                    park.aliases,
                    park.strict_aliases,
                    park.source_url,
                    park.source_title,
                ),
            )
        self._changed()

    def set_meta(self, key: str, value: str | int) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO store_meta (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, str(value)),
            )

    def get_meta(self, key: str) -> str | None:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT value FROM store_meta WHERE key = %s", (key,))
            row = cursor.fetchone()
        return row["value"] if row else None

    # Append-only logs (question events, feedback, harvest runs), so they survive hosts without a disk.

    def append_log(self, stream: str, at: datetime, record: dict) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO app_log (stream, at, record) VALUES (%s, %s, %s::jsonb)",
                (stream, at, json.dumps(record, ensure_ascii=False)),
            )

    def read_log(self, stream: str, since: datetime | None = None) -> list[dict]:
        with self.conn.cursor() as cursor:
            if since is None:
                cursor.execute("SELECT record FROM app_log WHERE stream = %s ORDER BY id", (stream,))
            else:
                cursor.execute("SELECT record FROM app_log WHERE stream = %s AND at >= %s ORDER BY id", (stream, since))
            return [row["record"] for row in cursor.fetchall()]

    def log_bytes(self, stream: str) -> int:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(pg_column_size(record)), 0) AS size FROM app_log WHERE stream = %s", (stream,))
            return int(cursor.fetchone()["size"])

    def list_documents(self, summary: bool = False) -> list[Document]:
        """Every document. `summary` skips the body text and fee rows, for listings and counts."""
        with self.conn.cursor() as cursor:
            if summary:
                cursor.execute(f"SELECT {SUMMARY_COLUMNS} FROM documents ORDER BY title")
                return [_document_from_row(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM documents ORDER BY title")
            documents = [_document_from_row(row) for row in cursor.fetchall()]
            cursor.execute("SELECT * FROM fees")
            fees_by_document: dict[str, list[FeeRecord]] = {}
            for row in cursor.fetchall():
                fees_by_document.setdefault(row["document_id"], []).append(
                    FeeRecord(
                        park_slug=row["park_slug"],
                        name=row["name"],
                        visitor_category=row["visitor_category"],
                        age_band=row["age_band"],
                        amount=float(row["amount"]),
                        currency=row["currency"],
                        unit=row["unit"],
                    )
                )
        for document in documents:
            document.fees = fees_by_document.get(document.document_id, [])
        return documents

    def list_parks(self) -> list[Park]:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT * FROM parks ORDER BY name")
            return [_park_from_row(row) for row in cursor.fetchall()]

    def chunk_stats(self) -> dict[str, tuple[int, int]]:
        """document_id → (chunks, characters), counted in the database instead of loading every vector."""
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT document_id, COUNT(*) AS chunks, COALESCE(SUM(LENGTH(body)), 0) AS characters FROM chunks GROUP BY document_id")
            return {row["document_id"]: (int(row["chunks"]), int(row["characters"])) for row in cursor.fetchall()}

    def count_records(self, kind: str) -> int:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS n FROM records WHERE kind = %s", (kind,))
            return int(cursor.fetchone()["n"])

    def all_chunks(self) -> list[Chunk]:
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT * FROM chunks")
            return [_chunk_from_row(row) for row in cursor.fetchall()]

    def semantic_candidates(self, embedding: list[float], limit: int = 80) -> list[Chunk]:
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (_vector(embedding), limit),
            )
            return [_chunk_from_row(row) for row in cursor.fetchall()]

    def fee_rows(self) -> list[tuple[Document, FeeRecord]]:
        rows = []
        for document in self.list_documents():
            for fee in document.fees:
                rows.append((document, fee))
        return rows

    def get_document(self, document_id: str) -> Document | None:
        for document in self.list_documents():
            if document.document_id == document_id:
                return document
        return None


def _vector(values: list[float]) -> str:
    if not values:
        values = [0.0] * 384
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _parse_vector(value) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        return [float(item) for item in value]
    text = str(value).strip("[]")
    if not text:
        return []
    return [float(part) for part in text.split(",")]


def _date(value):
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _document_from_row(row: dict) -> Document:
    return Document(
        document_id=row["document_id"],
        title=row["title"],
        organization=row.get("organization") or "",
        document_type=row.get("document_type") or "publication",
        text=row.get("body") or "",
        language=row.get("language") or "en",
        authority=row.get("authority") or "curated",
        authority_score=float(row.get("authority_score") or 0.85),
        status=row.get("status") or "current",
        version=int(row.get("version") or 1),
        published_date=_date(row.get("published_date")),
        effective_from=_date(row.get("effective_from")),
        effective_until=_date(row.get("effective_until")),
        retrieved_at=_date(row.get("retrieved_at")),
        source_url=row.get("source_url"),
        park_slug=row.get("park_slug"),
    )


def _chunk_from_row(row: dict) -> Chunk:
    return Chunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        text=row.get("body") or "",
        position=int(row.get("position") or 0),
        embedding=_parse_vector(row.get("embedding")),
        title=row.get("title") or "",
        organization=row.get("organization") or "",
        document_type=row.get("document_type") or "",
        language=row.get("language") or "en",
        authority=row.get("authority") or "curated",
        authority_score=float(row.get("authority_score") or 0.85),
        status=row.get("status") or "current",
        version=int(row.get("version") or 1),
        published_date=_date(row.get("published_date")),
        effective_from=_date(row.get("effective_from")),
        effective_until=_date(row.get("effective_until")),
        retrieved_at=_date(row.get("retrieved_at")),
        source_url=row.get("source_url"),
        park_slug=row.get("park_slug"),
    )


def _park_from_row(row: dict) -> Park:
    return Park(
        slug=row["slug"],
        name=row["name"],
        area_km2=row.get("area_km2"),
        established_year=row.get("established_year"),
        gazette=row.get("gazette"),
        circuit=row.get("circuit") or "",
        interests=list(row.get("interests") or []),
        beach=bool(row.get("beach")),
        mountain_climb=bool(row.get("mountain_climb")),
        aliases=list(row.get("aliases") or []),
        strict_aliases=list(row.get("strict_aliases") or []),
        source_url=row.get("source_url") or "",
        source_title=row.get("source_title") or "",
    )
