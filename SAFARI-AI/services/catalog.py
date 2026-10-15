"""Load the phase 1 TANAPA catalog into the knowledge store."""

from __future__ import annotations

import json
from pathlib import Path

from services.common.embeddings import HashEmbedder
from services.common.models import Park
from services.common.settings import ROOT
from services.common.store import JsonStore
from services.common.text import format_area
from services.ingestion.pipeline import ingest_text

CATALOG_VERSION = 1
MAP_URL = "https://www.tanzaniaparks.go.tz/uploads/publications/en-1710606473-TNPMapENG.pdf"
MAP_TITLE = "TANAPA GIS map of national parks (2024)"
NATIONAL_PARKS_URL = "https://www.tanzaniaparks.go.tz/nationalparks"


def catalog_path(root: Path | None = None) -> Path:
    return (root or ROOT) / "knowledge" / "metadata" / "parks.json"


def load_catalog(root: Path | None = None) -> dict:
    return json.loads(catalog_path(root).read_text(encoding="utf-8"))


def seed_catalog(store: JsonStore, embedder: HashEmbedder | None = None, root: Path | None = None) -> None:
    encoder = embedder or HashEmbedder()
    catalog = load_catalog(root)
    source = catalog["source"]
    organization = catalog["organization"]
    for raw in catalog["parks"]:
        park = Park.from_dict({**raw, "source_url": source["url"], "source_title": source["title"]})
        store.upsert_park(park)
        text = render_profile(park, source)
        ingest_text(
            store,
            text,
            {
                "document_id": f"tanapa_park_{park.slug}",
                "title": f"{park.name} profile",
                "organization": "TANAPA",
                "document_type": "park_profile",
                "language": "en",
                "authority": "curated",
                "status": "current",
                "version": CATALOG_VERSION,
                "source_url": source["url"],
                "park_slug": park.slug,
                "filename": f"{park.slug}.md",
            },
            encoder,
        )
    ingest_text(
        store,
        render_scope_note(),
        {
            "document_id": "safari_scope_phase1",
            "title": "SafariAI phase 1 scope",
            "organization": "SafariAI",
            "document_type": "scope",
            "language": "en",
            "authority": "system",
            "status": "current",
            "version": CATALOG_VERSION,
            "source_url": NATIONAL_PARKS_URL,
            "filename": "scope.md",
        },
        encoder,
    )
    ingest_text(
        store,
        render_contact(organization),
        {
            "document_id": "tanapa_contact",
            "title": "TANAPA public contact",
            "organization": "TANAPA",
            "document_type": "contact",
            "language": "en",
            "authority": "curated",
            "status": "current",
            "version": CATALOG_VERSION,
            "source_url": organization["contact_source"],
            "filename": "contact.md",
        },
        encoder,
    )
    store.set_meta("catalog_version", CATALOG_VERSION)


def render_profile(park: Park, source: dict) -> str:
    area = format_area(park.area_km2)
    year = str(park.established_year) if park.established_year else "unrecorded"
    gazette = park.gazette or "gazette reference not in the extract"
    interests = ", ".join(park.interests) if park.interests else "none"
    coastal = "yes" if park.beach else "no"
    climb = "yes" if park.mountain_climb else "no"
    alias_note = ""
    if park.slug == "nyerere":
        alias_note = " Questions that say Selous resolve to Nyerere National Park in this index."
    return (
        f"{park.name} is managed by Tanzania National Parks (TANAPA). "
        f"The {source['title']} records an area of {area} km² and establishment in {year} ({gazette}). "
        f"SafariAI planning labels: circuit {park.circuit}; interests {interests}; "
        f"coastal {coastal}; summit climb as the main visit {climb}. "
        "These labels filter trip shortlists. They are not official TANAPA zones and they are not a species list. "
        "This profile does not state entry fees, child rules, camping rules, vehicle rules, or safety procedures."
        f"{alias_note}"
    )


def render_scope_note() -> str:
    return (
        "SafariAI phase 1 answers from TANAPA national park profiles and from documents you ingest. "
        "Ngorongoro Conservation Area is managed by the Ngorongoro Conservation Area Authority (NCAA), "
        "not by TANAPA. Game reserves under the Tanzania Wildlife Management Authority (TAWA), "
        "Tanzania Tourist Board destination material, Zanzibar, and immigration visa rules "
        "are outside this phase. Mafia Island is outside the loaded TANAPA national park index."
    )


def render_contact(organization: dict) -> str:
    return (
        f"{organization['name']} ({organization['abbreviation']}) public contact on the national parks page: "
        f"{organization['postal']}. Phone {organization['phone']}. Email {organization['email']}."
    )
