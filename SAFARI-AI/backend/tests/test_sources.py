from services.catalog import seed_catalog
from services.common.store import JsonStore
from services.sources import tanapa_api
from services.sources.documents import page_text, publication_rows, same_site

from conftest import snapshot


def _parks():
    store = JsonStore(None)
    seed_catalog(store)
    return store.list_parks()


def test_tariff_rows_parse_visitor_class_age_and_season():
    rows = [record.payload for record in tanapa_api.tariff_records(snapshot(), _parks())]
    serengeti = [row for row in rows if row["park_slug"] == "serengeti" and row["category"] == "Entrance"]
    adult_nr = next(row for row in serengeti if row["visitor"] == "non_resident" and row["age"] == "adult")
    assert adult_nr["amount"] == 178850
    assert adult_nr["season"] == "high"
    assert adult_nr["valid_from"] == "2026-05-16"
    child_ex = next(row for row in serengeti if row["visitor"] == "expatriate" and row["age"] == "child_5_15")
    assert child_ex["item"] == "Entrance Children 5 - 15 Years"
    assert {row["visitor"] for row in serengeti} == {"non_resident", "expatriate", "eac_citizen"}


def test_vehicle_rows_use_registration_classes():
    rows = [record.payload for record in tanapa_api.tariff_records(snapshot(), _parks())]
    vehicles = {row["visitor"] for row in rows if row["category"] == "Vehicles"}
    assert {"local_vehicle", "foreign_vehicle"} <= vehicles


def test_api_park_names_match_the_catalog():
    parks = _parks()
    assert tanapa_api.match_park("Udzungwa Mountain National Park", parks) == "udzungwa"
    assert tanapa_api.match_park("Saanane National Park", parks) == "saanane"
    assert tanapa_api.match_park("Tanapa Head Office", parks) is None


def test_park_profiles_carry_text_image_and_contacts():
    profiles = {record.key: record.payload for record in tanapa_api.park_profile_records(snapshot(), _parks())}
    mikumi = profiles["mikumi"]
    assert "elephants" in mikumi["about"]
    assert mikumi["image_url"].startswith("https://tanzaniaparks.go.tz/uploads/")
    assert mikumi["contact"]["email"]


def test_rich_text_blocks_flatten_to_paragraphs():
    text = tanapa_api.blocks_to_text(
        [
            {"type": "paragraph", "children": [{"type": "text", "text": "First."}]},
            {"type": "list", "children": [{"type": "list-item", "children": [{"type": "text", "text": "Item"}]}]},
        ]
    )
    assert text == "First.\n\n- Item"


def test_tariff_bundle_yields_notes_and_faq():
    notes, faq = tanapa_api.parse_tariff_bundle(
        'S=["All fees are inclusive of 18% VAT","Children under 5 years of age enter FREE of charge"],'
        'P=[{question:"How long is my fee valid?",answer:"24 hours from entry."}]'
    )
    assert "Children under 5 years of age enter FREE of charge" in notes
    assert faq == [{"question": "How long is my fee valid?", "answer": "24 hours from entry."}]


def test_translations_and_newsletters_are_skipped():
    rows = publication_rows(
        [
            {"id": 1, "title": "GENERAL BROCHURE - SPANISH", "file": {"data": {"attributes": {"url": "/a.pdf", "size": 10}}}},
            {"id": 2, "title": "GENERAL BROCHURE - ENGLISH", "file": {"data": {"attributes": {"url": "/b.pdf", "size": 10}}}},
        ]
    )
    assert [row["id"] for row in rows] == [2]


def test_redirect_to_another_domain_is_rejected():
    assert same_site("https://www.ncaa.go.tz/about-ncaa/", "https://ncaa.go.tz/about") is True
    assert same_site("https://www.ncaa.go.tz/about-ncaa/", "https://www.cfl.com.br/") is False


def test_page_text_drops_navigation_and_scripts():
    html = "<nav>Home About</nav><script>var x=1</script><main><p>The dry season runs from June to October across most parks.</p></main><footer>© 2026</footer>"
    assert page_text(html) == "The dry season runs from June to October across most parks."


def test_refresh_records_source_status(assistant):
    status = {item["id"]: item for item in assistant.store.source_status()}["tanapa_api"]
    assert status["status"] == "ok"
    assert status["records"]["tariff_rows"] > 100
