"""Pull every source into the store and record how each one went.

`refresh_api` is the quick path (one API sweep, ~2 s) that the server runs on a schedule.
`harvest` adds the PDF publications and HTML pages.
A source that fails keeps its previous data; its status shows the error.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from services.catalog import seed_catalog
from services.common.embeddings import HashEmbedder
from services.common.settings import load_settings
from services.ingestion.pipeline import ingest_file, ingest_text, read_document_file
from services.sources import documents as docs
from services.sources import tanapa_api
from services.sources.http import Http

log = logging.getLogger("safari.harvest")


def refresh_api(store, embedder: HashEmbedder | None = None, http: Http | None = None, snapshot: tanapa_api.ApiSnapshot | None = None) -> dict:
    encoder = embedder or HashEmbedder()
    started = _now()
    client = http or Http()
    try:
        snap = snapshot or tanapa_api.fetch_snapshot(client)
    except Exception as exc:  # network, TLS, schema
        log.warning("TANAPA API refresh failed: %s", exc)
        store.set_source_status(
            tanapa_api.SOURCE_ID,
            {"name": "TANAPA website API", "status": "error", "error": str(exc)[:300], "last_attempt": started},
        )
        return {"status": "error", "error": str(exc)}
    finally:
        if http is None:
            client.close()
    _save_raw(snap)
    parks = store.list_parks()
    tariffs = tanapa_api.tariff_records(snap, parks)
    profiles = tanapa_api.park_profile_records(snap, parks)
    activities = tanapa_api.activity_records(snap)
    accommodation = tanapa_api.accommodation_records(snap)
    prose = tanapa_api.documents_from_snapshot(snap, parks)
    with store.batch():
        if tariffs:
            store.replace_records("tariff", tariffs)
        if profiles:
            store.replace_records("park_profile", profiles)
        if activities:
            store.replace_records("activity", activities)
        if accommodation:
            store.replace_records("accommodation", accommodation)
        if snap.tariff_notes or snap.tariff_faq:
            store.replace_records("fee_note", tanapa_api.fee_note_records(snap))
        for text, metadata in prose:
            if text.strip():
                ingest_text(store, text, metadata, encoder)
        for document_id in docs.OBSOLETE_DOCUMENT_IDS:
            if store.get_document(document_id):
                store.delete_document(document_id)
        counts = {
            "tariff_rows": len(tariffs),
            "parks": len(profiles),
            "activities": len(activities),
            "accommodation": len(accommodation),
            "documents": len(prose),
        }
        valid = sorted({(row.payload["valid_from"], row.payload["valid_until"]) for row in tariffs if row.payload.get("valid_from")})
        store.set_source_status(
            tanapa_api.SOURCE_ID,
            {
                "name": "TANAPA website API",
                "url": tanapa_api.TARIFF_PAGE,
                "status": "ok" if tariffs else "empty",
                "error": None,
                "last_attempt": started,
                "last_success": snap.retrieved_at,
                "records": counts,
                "tariff_windows": [list(item) for item in valid],
            },
        )
    return {"status": "ok", **counts}


def harvest(store=None, embedder: HashEmbedder | None = None, include_documents: bool = True) -> dict:
    settings = load_settings()
    if store is None:
        from services.engine import open_store

        store = open_store(settings)
    encoder = embedder or HashEmbedder()
    seed_catalog(store, encoder, settings.root)
    http = Http()
    report: dict = {"api": refresh_api(store, encoder, http)}
    if include_documents:
        report["publications"] = _publications(store, encoder, http)
        report["local"] = _local_documents(store, encoder)
        report["pages"] = _pages(store, encoder, http)
    _drop_empty_documents(store)
    http.close()
    report["totals"] = {"documents": len(store.list_documents()), "chunks": len(store.all_chunks())}
    return report


def _publications(store, encoder, http: Http) -> dict:
    started = _now()
    try:
        collection = tanapa_api.fetch_collection(http, "web-publications", {"populate": "*"})
    except Exception as exc:
        store.set_source_status("tanapa_publications", {"name": "TANAPA publications (PDF)", "status": "error", "error": str(exc)[:300], "last_attempt": started})
        return {"status": "error", "error": str(exc)}
    indexed, needs_ocr, failed = [], [], []
    for row in docs.publication_rows(collection):
        try:
            path = docs.download(http, row["file_url"], row["title"])
            if not read_document_file(path).strip():
                needs_ocr.append(row["title"])
                if store.get_document(row["metadata"]["document_id"]):
                    store.delete_document(row["metadata"]["document_id"])
                continue
            document = ingest_file(store, path, row["metadata"], encoder)
            indexed.append(document.document_id)
        except Exception as exc:
            failed.append(f"{row['title']}: {exc}"[:200])
    # Translations that v1 indexed by mistake.
    for document in store.list_documents():
        if document.document_id.startswith("tanapa_pub_") and docs.SKIP_TITLE.search(document.title):
            store.delete_document(document.document_id)
    status = {
        "name": "TANAPA publications (PDF)",
        "url": "https://www.tanzaniaparks.go.tz/corporate/publications",
        "status": "ok" if indexed else "error",
        "last_attempt": started,
        "records": {"indexed": len(indexed), "needs_ocr": len(needs_ocr), "failed": len(failed)},
        "needs_ocr": needs_ocr,
        "error": "; ".join(failed)[:500] or None,
    }
    if indexed:
        status["last_success"] = _now()
    store.set_source_status("tanapa_publications", status)
    return status


def _local_documents(store, encoder) -> dict:
    indexed = []
    for spec in docs.LOCAL_DOCUMENTS:
        path: Path = spec["path"]
        if not path.exists():
            continue
        metadata = {key: value for key, value in spec.items() if key != "path"}
        indexed.append(ingest_file(store, path, metadata, encoder).document_id)
    store.set_source_status(
        "official_pdfs",
        {"name": "Official PDFs on file (tariff 2023/24, visa)", "status": "ok", "last_success": _now(), "records": {"indexed": len(indexed)}},
    )
    return {"indexed": indexed}


def _pages(store, encoder, http: Http) -> dict:
    results = {}
    for page in docs.PAGES:
        started = _now()
        try:
            response = http.get(page.url)
            if not docs.same_site(page.url, str(response.url)):
                if store.get_document(page.document_id):
                    store.delete_document(page.document_id)
                raise ValueError(f"redirected off-site to {response.url.host}; not indexed")
            text = docs.page_text(response.text)
            if len(text) < 300:
                raise ValueError(f"only {len(text)} characters of content")
            ingest_text(
                store,
                text[:30000],
                {
                    "document_id": page.document_id,
                    "title": page.title,
                    "organization": page.organization,
                    "document_type": page.document_type,
                    "authority": page.authority,
                    "status": "current",
                    "source_url": page.url,
                    "language": "en",
                },
                encoder,
            )
            store.set_source_status(page.source_id, {"name": page.title, "url": page.url, "status": "ok", "error": None, "last_attempt": started, "last_success": _now(), "records": {"characters": len(text)}})
            results[page.source_id] = "ok"
        except Exception as exc:
            stale = store.get_document(page.document_id) is None
            store.set_source_status(
                page.source_id,
                {
                    "name": page.title,
                    "url": page.url,
                    "status": "error",
                    "error": str(exc)[:300],
                    "last_attempt": started,
                    # Nothing from this page is in the index, so its old counts no longer describe anything.
                    **({"records": None, "last_success": None} if stale else {}),
                },
            )
            results[page.source_id] = f"error: {exc}"[:200]
    return results


def _drop_empty_documents(store) -> None:
    for document in store.list_documents():
        if not document.text.strip():
            store.delete_document(document.document_id)


def _save_raw(snapshot: tanapa_api.ApiSnapshot) -> None:
    try:
        folder = load_settings().data_dir / "raw"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"tanapa_api_{snapshot.retrieved_at[:10]}.json"
        (folder / name).write_text(json.dumps(asdict(snapshot)), encoding="utf-8")
    except OSError as exc:
        log.warning("could not save raw snapshot: %s", exc)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
