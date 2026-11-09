from test_api import _client


def _ask(client, question, session="visitor-1", **profile):
    response = client.post("/v1/ask", json={"question": question, "as_of": "2026-10-20", "session_id": session, "profile": profile})
    assert response.status_code == 200


def test_questions_are_logged_and_summarised(monkeypatch, tmp_path):
    with _client(monkeypatch) as client:
        _ask(client, "Serengeti entry fees", passport="Germany", days=3, adults=2)
        _ask(client, "How big is Ruaha National Park?")
        _ask(client, "What is the price of a helicopter tour to Mars?", session="visitor-2")

        log = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
        assert "visitor-1" not in log  # session ids are hashed

        overview = client.get("/v1/admin/overview", params={"days": 7}).json()
        current = overview["kpis"]["current"]
        assert current["questions"] == 3
        assert current["sessions"] == 2
        assert {item["key"] for item in overview["parks"]} >= {"serengeti", "ruaha"}
        assert overview["markets"][0]["key"] == "Germany"
        assert overview["inventory_totals"]["parks"] == 21
        assert sum(day["questions"] for day in overview["series"]) == 3
        assert isinstance(overview["alerts"], list)

        rows = client.get("/v1/admin/questions", params={"park": "ruaha"}).json()
        assert rows["total"] == 1 and rows["rows"][0]["question"].startswith("How big")
        assert client.get("/v1/admin/questions", params={"q": "helicopter"}).json()["total"] == 1

        csv = client.get("/v1/admin/questions.csv")
        assert csv.status_code == 200 and "Serengeti entry fees" in csv.text


def test_feedback_review(monkeypatch):
    with _client(monkeypatch) as client:
        client.post("/v1/feedback", json={"rating": -1, "question": "Gombe fees?", "answer": "…", "session_id": "s"})
        items = client.get("/v1/admin/feedback").json()
        assert items["counts"] == {"total": 1, "positive": 0, "negative": 1, "open": 1}
        item_id = items["items"][0]["id"]
        assert client.post(f"/v1/admin/feedback/{item_id}", json={"status": "resolved", "note": "added fee row"}).status_code == 200
        assert client.get("/v1/admin/feedback").json()["items"][0]["review_status"] == "resolved"
        assert client.post("/v1/admin/feedback/unknown", json={"status": "resolved"}).status_code == 404


def test_inventory_fees_and_documents(monkeypatch):
    with _client(monkeypatch) as client:
        stock = client.get("/v1/admin/inventory", params={"as_of": "2026-10-20"}).json()
        serengeti = next(park for park in stock["parks"] if park["slug"] == "serengeti")
        assert serengeti["in_force_rows"] > 0
        assert 178850 in serengeti["nr_adult_entrance_tzs"]
        assert stock["tariff_windows"]

        fees = client.get("/v1/admin/fees", params={"park": "serengeti", "category": "Entrance", "state": ""}).json()
        assert fees["total"] > 0 and all(row["park_slug"] == "serengeti" for row in fees["rows"])

        documents = client.get("/v1/admin/documents").json()
        target = documents[0]["document_id"]
        assert client.delete(f"/v1/admin/documents/{target}").status_code == 200
        assert all(item["document_id"] != target for item in client.get("/v1/admin/documents").json())

        system = client.get("/v1/admin/system").json()
        assert system["store"] == "memory" and "rate_limit" in system


def test_admin_reads_need_the_token(monkeypatch):
    monkeypatch.setenv("SAFARI_ADMIN_TOKEN", "secret")
    with _client(monkeypatch) as client:
        assert client.get("/v1/admin/overview").status_code == 401
        assert client.get("/v1/admin/questions").status_code == 401
        assert client.get("/v1/admin/overview", headers={"X-Admin-Token": "secret"}).status_code == 200


def test_overview_has_the_dashboard_views(monkeypatch):
    with _client(monkeypatch) as client:
        _ask(client, "Serengeti entry fees")
        _ask(client, "Serengeti entry fees", session="visitor-2")
        _ask(client, "What is the price of a helicopter tour to Mars?")
        overview = client.get("/v1/admin/overview", params={"days": 7}).json()
        assert len(overview["weekday_hours"]) == 7 and all(len(day) == 24 for day in overview["weekday_hours"])
        assert sum(map(sum, overview["weekday_hours"])) == 3
        assert {item["key"] for item in overview["outcomes"]} == {"answered", "low_confidence", "declined", "failed"}
        assert sum(item["count"] for item in overview["outcomes"]) == 3
        assert overview["series"][-1]["partial"] is True and overview["series"][1]["partial"] is False
        assert overview["top_questions"][0]["question"] == "Serengeti entry fees" and overview["top_questions"][0]["count"] == 2
        assert overview["tariff_windows"]
        assert overview["trip_details"]["questions"] == 3 and 0 <= overview["trip_details"]["any"] <= 1


def test_overview_is_served_from_cache_and_refreshes(monkeypatch):
    with _client(monkeypatch) as client:
        _ask(client, "Serengeti entry fees")
        assert client.get("/v1/admin/overview").json()["kpis"]["current"]["questions"] == 1
        _ask(client, "How big is Ruaha National Park?")
        # Served at once from cache (stale-while-revalidate); the Refresh button asks for fresh numbers.
        assert client.get("/v1/admin/overview", params={"fresh": "true"}).json()["kpis"]["current"]["questions"] == 2


def test_fees_and_feedback_are_paginated(monkeypatch):
    with _client(monkeypatch) as client:
        first = client.get("/v1/admin/fees", params={"limit": 10}).json()
        second = client.get("/v1/admin/fees", params={"limit": 10, "offset": 10}).json()
        assert first["total"] > 20 and len(first["rows"]) == 10 and first["rows"][0] != second["rows"][0]
        assert "_text" not in first["rows"][0]
        for index in range(3):
            client.post("/v1/feedback", json={"rating": 1, "question": f"q{index}", "answer": "…", "session_id": "s"})
        page = client.get("/v1/admin/feedback", params={"limit": 2}).json()
        assert page["total"] == 3 and len(page["items"]) == 2 and page["items"][0]["question"] == "q2"


def test_deepseek_off_is_a_critical_alert(monkeypatch):
    with _client(monkeypatch) as client:
        _ask(client, "Serengeti entry fees")
        overview = client.get("/v1/admin/overview").json()
        off = [alert for alert in overview["alerts"] if alert["title"] == "DeepSeek is off"]
        assert off and off[0]["level"] == "critical"
        assert overview["kpis"]["current"]["fallbacks"] == 1
        assert overview["fallback_reasons"][0]["key"] == "llm_off"
