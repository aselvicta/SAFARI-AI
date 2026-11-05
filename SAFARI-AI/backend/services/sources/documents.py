"""PDF publications and HTML pages that have no structured API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from services.common.settings import ROOT
from services.sources.http import Http
from services.sources.tanapa_api import ORIGIN

OFFICIAL_DIR = ROOT / "knowledge" / "documents" / "official"
MAX_PDF_BYTES = 15_000_000

# Translations of the English brochure, and newsletters (Nature's Voice alone is ~100 MB).
SKIP_TITLE = re.compile(r"\b(spanish|russian|german|french|news ?letter)\b", re.IGNORECASE)

PUBLICATION_TYPES = {
    "park-fees-and-regulations": "tariff",
    "procedures": "procedure",
    "guidelines": "guideline",
    "manuals": "manual",
    "brochure": "brochure",
    "the-tanzania-national-parks-acts": "act",
    "national-policies-for-national-parks": "policy",
    "arrival-trends": "statistics",
}

LOCAL_DOCUMENTS = [
    {
        "path": ROOT / "knowledge/documents/en-1688147569-TARIFFS Design 202324.pdf",
        "document_id": "tanapa_tariff_2023_24",
        "title": "TANAPA Park Tariffs 2023/24",
        "organization": "TANAPA",
        "document_type": "tariff",
        "authority": "official",
        "status": "superseded",
        "effective_from": "2023-07-01",
        "effective_until": "2024-06-30",
        "published_date": "2023-07-01",
        "source_url": "https://www.tanzaniaparks.go.tz/tourism/visitor-information/tariff",
        "version": 2023,
    },
    {
        "path": ROOT / "knowledge/documents/en-1583574424-TANAPA TOURISM INVESTMENT MANUAL_04032020.pdf",
        "document_id": "tanapa_investment_manual_2020",
        "title": "TANAPA Tourism Investment Manual (4 March 2020)",
        "organization": "TANAPA",
        "document_type": "manual",
        "authority": "official",
        "status": "current",
        "published_date": "2020-03-04",
        "source_url": "https://www.tanzaniaparks.go.tz/corporate/publications",
        "version": 2020,
    },
    {
        "path": ROOT / "knowledge/documents/Visa-guideline.pdf",
        "document_id": "immigration_visa_guideline",
        "title": "Tanzania visa guideline",
        "organization": "Tanzania Immigration",
        "document_type": "visa",
        "authority": "official",
        "status": "current",
        "source_url": "https://visa.immigration.go.tz/guidelines",
        "version": 1,
    },
    {
        "path": ROOT / "knowledge/documents/List_of_Countries_with_VISA_Eligibility.pdf",
        "document_id": "immigration_visa_eligibility",
        "title": "List of countries with visa eligibility",
        "organization": "Tanzania Immigration",
        "document_type": "visa",
        "authority": "official",
        "status": "current",
        "source_url": "https://visa.immigration.go.tz/guidelines",
        "version": 1,
    },
]


@dataclass(frozen=True)
class PageSource:
    source_id: str
    document_id: str
    title: str
    organization: str
    document_type: str
    url: str
    authority: str = "official"


PAGES = [
    PageSource("tanapa_plan", "tanapa_plan_a_trip", "Plan a trip — TANAPA", "TANAPA", "guideline", "https://www.tanzaniaparks.go.tz/plan-a-trip"),
    PageSource("immigration", "immigration_guidelines_page", "Tanzania eVisa guidelines", "Tanzania Immigration", "visa", "https://visa.immigration.go.tz/guidelines"),
    PageSource("ncaa", "ncaa_about", "About the Ngorongoro Conservation Area Authority", "NCAA", "authority", "https://www.ncaa.go.tz/about-ncaa/"),
    PageSource("tawa", "tawa_home", "Tanzania Wildlife Management Authority", "TAWA", "authority", "https://www.tawa.go.tz/"),
    PageSource("ttb", "ttb_home", "Tanzania Tourist Board", "Tanzania Tourist Board", "authority", "https://www.tanzaniatourism.go.tz/"),
]

# Ids written by v1 that v2 replaces with API data. Harvest removes them.
OBSOLETE_DOCUMENT_IDS = ["tanapa_tariff_page", "tanapa_national_parks_page"]


def publication_rows(collection: list[dict]) -> list[dict]:
    """Downloadable PDFs from the web-publications collection, minus translations and huge files."""
    rows = []
    for item in collection:
        if item.get("isActive") is False:
            continue
        file_attrs = (((item.get("file") or {}).get("data")) or {})
        file_attrs = file_attrs.get("attributes") or file_attrs
        category = ((((item.get("web_publications_category") or {}).get("data")) or {}).get("attributes")) or {}
        url = file_attrs.get("url") or ""
        title = re.sub(r"\s+", " ", str(item.get("title") or "TANAPA publication")).strip()
        if not url or SKIP_TITLE.search(title) or category.get("slug") == "news-letter":
            continue
        if float(file_attrs.get("size") or 0) * 1000 > MAX_PDF_BYTES or "202324" in url:
            continue
        slug = category.get("slug") or ""
        document_type = PUBLICATION_TYPES.get(slug, "publication")
        if "regulation" in title.lower():
            document_type = "regulation"
        rows.append(
            {
                "id": item.get("id"),
                "title": title,
                "file_url": url if url.startswith("http") else ORIGIN + url,
                "metadata": {
                    "document_id": f"tanapa_pub_{item.get('id')}",
                    "title": title.title() if title.isupper() else title,
                    "organization": "TANAPA",
                    "document_type": document_type,
                    "authority": "official",
                    "status": "current",
                    "published_date": (item.get("publishedDate") or "")[:10] or None,
                    "source_url": url if url.startswith("http") else ORIGIN + url,
                    "language": "sw" if "kiswahili" in title.lower() else "en",
                    "version": 1,
                },
            }
        )
    return rows


def download(http: Http, url: str, title: str) -> Path:
    OFFICIAL_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or "publication"
    path = OFFICIAL_DIR / f"{safe}.pdf"
    if path.exists() and path.stat().st_size > 1000:
        return path
    response = http.get(url)
    if not response.content.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    path.write_bytes(response.content)
    return path


class _MainText(HTMLParser):
    """Visible text with scripts, styles, navigation, headers, footers, and forms removed."""

    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "form", "svg", "button", "select", "iframe"}
    BLOCK = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "h5", "tr", "br", "main"}

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK and not self._skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip() + " ")


def same_site(requested: str, final: str) -> bool:
    """A redirect must stay on the same registrable domain (ncaa.go.tz -> www.ncaa.go.tz is fine)."""
    from urllib.parse import urlparse

    def base(url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        parts = host.split(".")
        keep = 3 if len(parts) >= 3 and parts[-2] in {"go", "co", "or", "ac"} else 2
        return ".".join(parts[-keep:])

    return base(requested) == base(final)


def page_text(html: str) -> str:
    parser = _MainText()
    parser.feed(html)
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).split("\n")]
    # Drop button-sized fragments ("View details →", single letters of a month strip).
    kept = [line for line in lines if len(line) >= 25 or (len(line) >= 12 and line.endswith((".", ":")))]
    return "\n\n".join(dict.fromkeys(kept))
