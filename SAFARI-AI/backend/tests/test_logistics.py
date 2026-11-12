from datetime import date

import pytest
from fastapi.testclient import TestClient

from services.common.models import Record
from services.logistics import fuel, hotels
from services.logistics.budget import BUFFER, LATRA_RATES, TripRequest
from services.logistics.fx import fee_usd
from services.logistics.places import find_origin

from conftest import offline_settings, snapshot

TRAVEL = date(2026, 12, 10)

NOTICE = """REF: PPR/2026 - 11/01
PUBLIC NOTICE ON CAP PRICES FOR PETROLEUM PRODUCTS EFFECTIVE
WEDNESDAY, 4TH NOVEMBER 2026
Table 3: Retail Cap Prices – TZS/Litre
S.No. Town Petrol Diesel Kerosene
1.  Dar es Salaam                4,083                 4,128                       4,117
2.  Arusha                4,202                 4,247                       4,236
103 Mikumi 4,144 4,189 4,178
"""


def test_fuel_notice_parses_both_layouts_and_the_date():
    effective, rows = fuel.parse_notice(NOTICE)
    assert effective == "2026-11-04"
    assert [row["town"] for row in rows] == ["Dar es Salaam", "Arusha", "Mikumi"]
    assert rows[1] == {"town": "Arusha", "petrol": 4202.0, "diesel": 4247.0, "kerosene": 4236.0}


def test_newest_fuel_notice_wins_regardless_of_page_order():
    html = (
        '<a href="https://www.ewura.go.tz/uploads/documents/en-1791322203-Petroleum Cap Prices for  October 2026   .pdf">'
        '<a href="https://www.ewura.go.tz/uploads/documents/en_cap_01_07_2026.pdf">'
        '<a href="https://www.ewura.go.tz/uploads/documents/en-1793740364-Cap Prices for the Month of November 2026.pdf">'
    )
    assert fuel.latest_notice_url(html).endswith("November 2026.pdf")


def test_origin_matching():
    assert find_origin("Dar").name == "Dar es Salaam"
    assert find_origin("we drive from Mwanza next week", after_from=True).name == "Mwanza"
    assert find_origin("Nataka kwenda Mikumi kwa siku tatu", after_from=True) is None
    assert find_origin("Atlantis") is None


def test_tanapa_usd_priced_fees_are_exact_and_others_use_the_live_rate(assistant):
    fx = assistant.logistics.fx
    assert fee_usd(178850, "non_resident", fx, 2555) == (70.0, "tanapa")
    usd, basis = fee_usd(10000, "eac_citizen", fx, 2555)
    assert basis == "live" and usd == round(10000 / 2643.5182, 2)
    converted = fx.convert(100, "EUR", "TZS")
    assert converted["result"] == pytest.approx(294064.96) and converted["rate_date"] == "2026-11-11"
    assert fx.convert(1, "XYZ", "TZS")["error"]


def _seed_logistics(store):
    store.replace_records(
        fuel.RECORD_KIND,
        [
            Record(fuel.RECORD_KIND, fuel._key(town), {"town": town, "petrol": 4000.0, "diesel": diesel, "kerosene": 4000.0, "effective": "2026-11-04", "notice_url": "https://www.ewura.go.tz/x.pdf"}, fuel.SOURCE_ID, "https://www.ewura.go.tz/x.pdf", "2026-11-05")
            for town, diesel in (("Dar es Salaam", 4128.0), ("Mikumi", 4189.0), ("Mwanza", 4343.0), ("Kigoma", 4355.0))
        ],
    )
    listings = [
        ("h1", "Gate Lodge", -7.40, 36.98),
        ("h2", "River Camp", -7.41, 36.99),
        ("h3", "Town Inn", -7.42, 36.97),
    ]
    store.replace_records(
        hotels.RECORD_KIND,
        [Record(hotels.RECORD_KIND, key, {"key": key, "name": name, "type": "Hotel", "lat": lat, "lon": lon, "rating": 4.5, "reviews": 10, "url": ""}, hotels.SOURCE_ID, "", "2026-11-05") for key, name, lat, lon in listings],
    )


def _fake_rates(monkeypatch, prices):
    def one(self, hotel, check_in, check_out):
        usd = prices.get(hotel["key"])
        if usd is None:
            return None
        return {**hotel, "usd_per_night": usd, "cheapest_site": "Booking.com", "sites": [{"name": "Booking.com", "usd": usd}]}

    monkeypatch.setattr(hotels.RateCache, "_one", one)


def _request(**overrides):
    base = dict(park_slug="mikumi", park_name="Mikumi National Park", origin="Dar es Salaam", travel_date=TRAVEL, days=3, adults=2, child_ages=[8], visitor="eac_citizen")
    return TripRequest(**{**base, **overrides})


def test_budget_self_drive_with_live_hotels(assistant, monkeypatch):
    _seed_logistics(assistant.store)
    _fake_rates(monkeypatch, {"h1": 40.0, "h2": 60.0, "h3": 100.0})
    block = assistant.logistics.budget(_request())
    assert block["type"] == "trip_budget"
    groups = {line["group"] for line in block["lines"]}
    assert groups == {"live", "official", "estimate"}
    hotel = next(line for line in block["lines"] if line["group"] == "live")
    # median USD 60 × 1 room × 2 nights at the live rate
    assert hotel["total_tzs"] == round(60 * 2643.5182 * 2)
    fuel_line = next(line for line in block["lines"] if line["group"] == "estimate")
    assert "EWURA" in fuel_line["detail"]
    assert block["buffer_tzs"] == round((block["groups"]["live"] + block["groups"]["estimate"]) * BUFFER)
    assert block["total_tzs"] == block["subtotal_tzs"] + block["buffer_tzs"]
    assert block["total_usd"] == round(block["total_tzs"] / 2643.5182, 2)
    assert block["fx"]["live"] and block["fx"]["date"] == "2026-11-11"
    assert {source["key"] for source in block["sources"]} >= {"fuel", "tanapa", "hotels", "fx", "route"}


def test_budget_by_bus_with_camping(assistant, monkeypatch):
    _seed_logistics(assistant.store)
    block = assistant.logistics.budget(_request(transport="bus", stay="camping"))
    bus = next(line for line in block["lines"] if line["label"].startswith("Bus"))
    assert bus["group"] == "official" and str(LATRA_RATES["semi_luxury_paved"]) in bus["detail"]
    assert not any(line["group"] == "estimate" for line in block["lines"])
    assert any("Safari vehicle" in item for item in block["excluded"])


def test_boat_park_has_no_vehicle_fee_and_flags_the_boat(assistant):
    _seed_logistics(assistant.store)
    block = assistant.logistics.budget(_request(park_slug="gombe", park_name="Gombe National Park", origin="Mwanza", visitor="non_resident", stay="none", currency="EUR"))
    assert not any("Vehicle entry" in line["label"] for line in block["lines"])
    assert block["excluded"][0].startswith("Boat")
    assert block["currency"]["code"] == "EUR"


def test_unknown_origin_lists_known_towns(assistant):
    block = assistant.logistics.budget(_request(origin="Atlantis"))
    assert "Dar es Salaam" in block["known_towns"]


def test_composer_gives_a_trip_budget_when_the_origin_is_known(assistant):
    _seed_logistics(assistant.store)
    result = assistant.ask("Plan 3 days in Mikumi, how much will it cost?", as_of=TRAVEL, profile={"origin": "Dar es Salaam", "adults": 2, "passport": "Tanzania"})
    assert "plan_trip_budget" in result["tool_calls"]
    assert any(block["type"] == "trip_budget" for block in result["blocks"])
    assert "Trip budget from Dar es Salaam" in result["answer"]


def _client(monkeypatch):
    import api.main as main
    from services.sources.harvest import refresh_api

    original = main.build_assistant

    def offline_build(_settings=None):
        assistant = original(offline_settings())
        refresh_api(assistant.store, assistant.embedder, snapshot=snapshot())
        _seed_logistics(assistant.store)
        return assistant

    monkeypatch.setattr(main, "build_assistant", offline_build)
    return TestClient(main.app)


def test_trip_budget_and_fx_endpoints(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.post("/v1/trip-budget", json={"park": "Mikumi", "origin": "dar", "days": 2, "adults": 2, "passport": "Kenya", "stay": "camping"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["park_slug"] == "mikumi" and body["visitor"] == "eac_citizen"
        assert client.post("/v1/trip-budget", json={"park": "Mikumi", "origin": "Atlantis", "days": 2, "adults": 2}).status_code == 422
        rate = client.get("/v1/fx", params={"amount": 10, "source": "USD", "target": "TZS"}).json()
        assert rate["result"] == pytest.approx(26435.18)
        assert "Dar es Salaam" in client.get("/v1/trip-budget/options").json()["origins"]


def test_bank_of_tanzania_page_is_the_fallback_when_the_feed_refuses():
    from services.logistics import fx as fx_module

    page = """<table><tr><th>S/NO</th><th>Sarafu</th><th>Kununua</th><th>Kuuza</th><th>Wastani</th><th>Tarehe ya biashara</th></tr>
    <tr><td>1</td><td style="text-align:right">EUR</td><td>2925.9</td><td>2955.4</td><td>2940.6496</td><td>12-Nov-26</td></tr>
    <tr><td>40</td><td style="text-align:right">USD</td><td>2630.3663</td><td>2656.67</td><td>2643.5182</td><td>12-Nov-26</td></tr>
    <tr><td>41</td><td style="text-align:right">GOLD</td><td>10642620.02</td><td>10749046.22</td><td>10695833.12</td><td>12-Nov-26</td></tr></table>"""

    class Page:
        text = page

    class Client:
        def json(self, url, params=None):
            raise RuntimeError("403 Forbidden")

        def get(self, url, params=None):
            return Page()

    snap = fx_module._read_bot_page(Client(), "2026-11-12T00:00:00+00:00")
    assert snap["date"] == "2026-11-12" and snap["rates"] == {"EUR": 2940.6496, "USD": 2643.5182}
    with pytest.raises(RuntimeError):
        fx_module._read_feed(Client(), "now")
