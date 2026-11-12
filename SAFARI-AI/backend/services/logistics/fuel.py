"""EWURA monthly cap prices for petrol, diesel and kerosene in about 190 mainland towns.

EWURA publishes a PDF notice on the first Wednesday of each month. We read the newest English notice
from the petroleum-price page and parse Table 3 (retail cap price per town, TZS per litre). A notice
is only fetched again when its link changes, so the daily check costs one HTML request.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from urllib.parse import quote

from pypdf import PdfReader

from services.common.models import Record
from services.sources.http import Http

log = logging.getLogger("safari.fuel")

PAGE_URL = "https://www.ewura.go.tz/publications/petroleum-price"
SOURCE_ID = "ewura_fuel"
RECORD_KIND = "fuel_price"
_LINK = re.compile(r'href="(https://www\.ewura\.go\.tz/uploads/documents/en[^"]*?\.pdf)"', re.IGNORECASE)
_ROW = re.compile(r"^\s*(\d{1,3})\.?\s+(.+?)\s+(\d,\d{3})\s+(\d,\d{3})\s+(\d,\d{3}|-)\s*$")
_EFFECTIVE = re.compile(r"EFFECTIVE\s+(?:FROM\s+)?(?:\w+DAY,?\s+)?(\d{1,2})(?:ST|ND|RD|TH)?\s+([A-Z]+),?\s+(\d{4})", re.IGNORECASE)


def latest_notice_url(html: str) -> str | None:
    """The newest English cap-price PDF on the page, by the month and year in its file name (the page
    does not list them in order: the current notice sits in a separate card)."""
    links = [url for url in dict.fromkeys(_LINK.findall(html)) if re.search(r"cap", url, re.IGNORECASE)]
    return max(links, key=_notice_month, default=None)


def _notice_month(url: str) -> tuple[int, int, int]:
    name = url.rsplit("/", 1)[-1]
    stamp = re.search(r"en-(\d{9,})", name)
    year = re.search(r"(?<!\d)(20\d{2})(?!\d)", name[stamp.end():] if stamp else name)
    month = next((index for index, word in enumerate(_MONTHS, 1) if word in name.lower()), 0)
    if not month:
        numeric = re.search(r"_(\d{2})_(\d{2})_(20\d{2})", name)  # en_cap_01_07_2026.pdf
        month = int(numeric.group(2)) if numeric else 0
    return (int(year.group(1)) if year else 0, month, int(stamp.group(1)) if stamp else 0)


_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")


def parse_notice(text: str) -> tuple[str | None, list[dict]]:
    """(effective date ISO, [{town, petrol, diesel, kerosene}]) from the notice text."""
    effective = None
    match = _EFFECTIVE.search(re.sub(r"\s+", " ", text))
    if match:
        try:
            effective = datetime.strptime(f"{match.group(1)} {match.group(2).title()} {match.group(3)}", "%d %B %Y").date().isoformat()
        except ValueError:
            effective = None
    rows, seen = [], set()
    for line in text.splitlines():
        found = _ROW.match(line)
        if not found:
            continue
        town = re.sub(r"\s+", " ", found.group(2)).strip()
        if town.lower() in seen:
            continue
        seen.add(town.lower())
        rows.append(
            {
                "town": town,
                "petrol": _amount(found.group(3)),
                "diesel": _amount(found.group(4)),
                "kerosene": _amount(found.group(5)),
            }
        )
    return effective, rows


def refresh(store, http: Http | None = None, force: bool = False) -> dict:
    client = http or Http(timeout=60.0, retries=2)
    started = _now()
    try:
        page = client.get(PAGE_URL).text
        url = latest_notice_url(page)
        if not url:
            raise ValueError("no cap-price notice link on the EWURA page")
        current = store.list_records(RECORD_KIND)
        if current and not force and current[0].source_url == url:
            _status(store, {"status": "ok", "error": None, "last_attempt": started, "last_success": started})
            return {"status": "unchanged", "notice": url}
        pdf = client.get(_encode(url)).content
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
        effective, rows = parse_notice(text)
        if len(rows) < 50:
            raise ValueError(f"only {len(rows)} town rows parsed from {url}")
    except Exception as exc:
        log.warning("EWURA fuel refresh failed: %s", exc)
        _status(store, {"status": "error", "error": str(exc)[:300], "last_attempt": started})
        return {"status": "error", "error": str(exc)}
    finally:
        if http is None:
            client.close()
    records = [
        Record(RECORD_KIND, _key(row["town"]), {**row, "effective": effective, "notice_url": url}, SOURCE_ID, url, started)
        for row in rows
    ]
    store.replace_records(RECORD_KIND, records)
    _status(
        store,
        {"status": "ok", "error": None, "last_attempt": started, "last_success": started, "records": {"towns": len(rows), "effective": effective}, "notice_url": url},
    )
    return {"status": "ok", "towns": len(rows), "effective": effective, "notice": url}


def price(store, town: str, product: str = "diesel") -> dict | None:
    """The cap row for `town` (EWURA spelling), falling back to Dar es Salaam."""
    records = {record.key: record for record in store.list_records(RECORD_KIND)}
    record = records.get(_key(town)) or records.get(_key("Dar es Salaam"))
    if record is None:
        return None
    row = record.payload
    return {
        "town": row["town"],
        "requested_town": town,
        "product": product,
        "tzs_per_litre": row.get(product),
        "effective": row.get("effective"),
        "source_url": row.get("notice_url") or PAGE_URL,
        "exact_town": record.key == _key(town),
    }


def _status(store, status: dict) -> None:
    store.set_source_status(SOURCE_ID, {"name": "EWURA fuel cap prices", "url": PAGE_URL, **status})


def _key(town: str) -> str:
    return re.sub(r"[^a-z]+", "-", town.lower()).strip("-")


def _amount(text: str) -> float | None:
    return None if text == "-" else float(text.replace(",", ""))


def _encode(url: str) -> str:
    return quote(url, safe=":/?=&%")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
