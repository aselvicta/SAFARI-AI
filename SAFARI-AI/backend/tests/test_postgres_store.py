"""PostgresStore against a real database. Runs when SAFARI_TEST_DATABASE_URL points at a scratch
Postgres with pgvector (e.g. `docker run -p 55432:5432 -e POSTGRES_PASSWORD=x pgvector/pgvector:pg16`),
and is skipped otherwise. The tests only add rows under their own ids and remove them afterwards."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from services.common.models import Chunk, Document

DSN = os.environ.get("SAFARI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="set SAFARI_TEST_DATABASE_URL to run Postgres tests")


@pytest.fixture()
def store():
    from services.common.postgres_store import PostgresStore

    store = PostgresStore(DSN)
    yield store
    store.delete_document("test-doc-pg")
    with store.conn.cursor() as cursor:
        cursor.execute("DELETE FROM app_log WHERE stream = 'test-stream'")
        cursor.execute("DELETE FROM store_meta WHERE key = 'test-key'")


def _document(**extra):
    return Document(document_id="test-doc-pg", title="PG test", organization="TANAPA", document_type="publication", text="full body text", **extra)


def _chunk(position, text):
    return Chunk(
        chunk_id=f"test-doc-pg:{position}", document_id="test-doc-pg", position=position, text=text, embedding=[0.0] * 384,
        title="PG test", organization="TANAPA", document_type="publication",
    )


def test_summary_listing_and_chunk_stats(store):
    store.upsert_document(_document(), [_chunk(0, "abc"), _chunk(1, "defgh")])
    summary = {document.document_id: document for document in store.list_documents(summary=True)}
    assert summary["test-doc-pg"].text == ""
    full = {document.document_id: document for document in store.list_documents()}
    assert full["test-doc-pg"].text == "full body text"
    assert store.chunk_stats()["test-doc-pg"] == (2, 8)
    assert store.count_records("no-such-kind") == 0


def test_logs_meta_and_version(store):
    before = store.version
    store.set_source_status("test-source", {"status": "ok"})
    assert store.version == before + 1
    at = datetime.now(timezone.utc)
    store.append_log("test-stream", at - timedelta(days=3), {"n": 1})
    store.append_log("test-stream", at, {"n": 2})
    assert [row["n"] for row in store.read_log("test-stream")] == [1, 2]
    assert [row["n"] for row in store.read_log("test-stream", at - timedelta(days=1))] == [2]
    assert store.log_bytes("test-stream") > 0
    store.set_meta("test-key", "{}")
    assert store.get_meta("test-key") == "{}"
    with store.conn.cursor() as cursor:
        cursor.execute("DELETE FROM source_status WHERE source_id = 'test-source'")
