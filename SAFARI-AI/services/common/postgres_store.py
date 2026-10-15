"""PostgreSQL + pgvector store.

The hybrid score still runs in Python so the formula stays inspectable.
`semantic_candidates` is the ANN entry point for when the corpus no longer fits a full scan.
"""

from __future__ import annotations

import contextlib
import json

from services.common.models import Chunk, Document, FeeRecord, Park, Record


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self.conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)
        self.version = 0

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
            for record in records:
                cursor.execute(
                    "INSERT INTO records (kind, key, payload, source_id, source_url, retrieved_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (kind, record.key, json.dumps(record.payload), record.source_id, record.source_url, record.retrieved_at),
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

    def list_documents(self) -> list[Document]:
        with self.conn.cursor() as cursor:
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
