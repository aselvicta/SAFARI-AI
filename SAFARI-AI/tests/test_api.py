import json

from fastapi.testclient import TestClient

from services.common.store import JsonStore
from services.ingestion.pipeline import classify_document, ingest_file

from conftest import offline_settings, snapshot


def test_classify_tariff_text():
    assert classify_document("Conservation fee tariff for national parks", "tariffs.pdf") == "tariff"


def test_ingest_text_file(tmp_path):
    path = tmp_path / "visitor-guideline.txt"
    path.write_text("Visitors should keep receipts from official TANAPA gates.\n\nThis guideline is a test file.", encoding="utf-8")
    store = JsonStore(None)
    document = ingest_file(store, path, {"authority": "official", "organization": "TANAPA"})
    assert document.document_type == "guideline"
    assert store.all_chunks()


def _client(monkeypatch):
    import apps.api.main as main
    from services.sources.harvest import refresh_api

    original = main.build_assistant

    def offline_build(_settings=None):
        assistant = original(offline_settings())
        refresh_api(assistant.store, assistant.embedder, snapshot=snapshot())
        return assistant

    monkeypatch.setattr(main, "build_assistant", offline_build)
    return TestClient(main.app)


def test_api_end_to_end(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.get("/v1/health").json()["parks"] == 21
        status = client.get("/v1/status").json()
        assert status["tariff_rows"] > 100
        assert any(item["id"] == "tanapa_api" for item in status["sources"])

        parks = client.get("/v1/parks").json()
        serengeti = next(item for item in parks if item["slug"] == "serengeti")
        assert serengeti["image_url"] and "about" not in serengeti

        fees = client.get("/v1/fees", params={"park": "serengeti", "as_of": "2026-10-20"}).json()
        assert fees["type"] == "fees" and fees["rows"]

        asked = client.post("/v1/ask", json={"question": "How big is Ruaha National Park?", "as_of": "2026-10-20", "session_id": "s1"})
        assert asked.status_code == 200
        assert "20,300" in asked.json()["answer"]

        assert client.post("/v1/ask", json={"question": "hi"}).status_code == 200
        assert client.get("/admin").status_code == 200


def test_stream_ends_with_the_final_payload(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.post("/v1/ask/stream", json={"question": "Serengeti entry fees", "as_of": "2026-10-20"})
        events = [block for block in response.text.split("\n\n") if block.startswith("event:")]
        final = next(block for block in events if block.startswith("event: final"))
        payload = json.loads(final.split("data: ", 1)[1])
        assert payload["intent"] == "fee"
        assert any(block.startswith("event: status") for block in events)


def test_upload_and_feedback(monkeypatch, tmp_path):
    with _client(monkeypatch) as client:
        upload = client.post(
            "/v1/documents",
            files={"file": ("note.txt", b"Camping procedure test for Tarangire gate receipts.", "text/plain")},
            data={"metadata": '{"title": "Test procedure", "document_type": "procedure", "authority": "unverified"}'},
        )
        assert upload.status_code == 200
        assert any(item["title"] == "Test procedure" for item in client.get("/v1/documents").json())
        assert client.post("/v1/documents", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
        assert client.post("/v1/feedback", json={"rating": 1, "question": "q", "answer": "a"}).json() == {"ok": True}
        assert (tmp_path / "feedback.jsonl").exists()


def test_admin_token_is_enforced(monkeypatch):
    monkeypatch.setenv("SAFARI_ADMIN_TOKEN", "secret")
    with _client(monkeypatch) as client:
        assert client.post("/v1/admin/harvest").status_code == 401


def test_briefing_pdf_lists_live_fees(monkeypatch):
    from io import BytesIO

    from pypdf import PdfReader

    with _client(monkeypatch) as client:
        response = client.post(
            "/v1/briefing?download=true",
            json={"parks": ["serengeti"], "origin": "Nairobi", "passport": "Germany", "days": 3, "adults": 2, "child_ages": [7], "as_of": "2026-10-20"},
        )
        assert response.status_code == 200
        text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
        assert "178,850" in text
        assert "Nairobi" in text
        assert "Total" in text
