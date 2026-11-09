"""Analytics and admin state go to the database when the store has logs (hosts without a disk)."""

from services.analytics.events import Analytics, JsonDoc, StoreLines, feedback_id, open_lines


class LogStore:
    """The log and metadata surface of PostgresStore, in memory."""

    def __init__(self):
        self.logs: list[tuple[str, object, dict]] = []
        self.meta: dict[str, str] = {}

    def append_log(self, stream, at, record):
        self.logs.append((stream, at, record))

    def read_log(self, stream, since=None):
        return [record for name, at, record in self.logs if name == stream and (since is None or at >= since)]

    def log_bytes(self, stream):
        return sum(len(str(record)) for name, _, record in self.logs if name == stream)

    def get_meta(self, key):
        return self.meta.get(key)

    def set_meta(self, key, value):
        self.meta[key] = str(value)


def test_analytics_uses_store_logs_and_writes_no_files(tmp_path):
    store = LogStore()
    analytics = Analytics(tmp_path, store)
    assert isinstance(analytics.events, StoreLines)

    analytics.record_question(question="Serengeti fees", session_id="s", profile={}, result={"intent": "fee"}, latency_ms=12, channel="json")
    row = analytics.record_feedback({"question": "Serengeti fees", "answer": "x", "rating": -1, "comment": ""})
    analytics.set_review(feedback_id(row), status="resolved", note="fixed")

    assert [q["intent"] for q in analytics.questions(days=1)] == ["fee"]
    assert analytics.feedback_items()[0]["review_status"] == "resolved"
    assert "doc:feedback_review" in store.meta
    assert list(tmp_path.iterdir()) == []


def test_file_store_keeps_files(tmp_path):
    lines = open_lines(tmp_path, object(), "harvests")
    lines.append({"at": "2026-11-09T10:00:00+00:00", "kind": "api"})
    assert (tmp_path / "harvests.jsonl").exists()

    doc = JsonDoc(tmp_path, None, "evaluation_last")
    doc.save({"ran_at": "now"})
    assert doc.load() == {"ran_at": "now"}
