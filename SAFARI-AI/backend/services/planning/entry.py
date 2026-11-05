"""Entry lines taken from the official immigration PDFs and the TANAPA plan page.

The live eVisa page fails certificate verification from this host, so visa
lines come from the guideline and eligibility list already saved from
immigration.go.tz. Nothing is filled in when a country is not on that list.
"""

from __future__ import annotations

import html
import re

import httpx
from pypdf import PdfReader

from services.common.settings import ROOT

GUIDELINE = ROOT / "knowledge" / "documents" / "Visa-guideline.pdf"
ELIGIBILITY = ROOT / "knowledge" / "documents" / "List_of_Countries_with_VISA_Eligibility.pdf"
PLAN_URL = "https://www.tanzaniaparks.go.tz/plan-a-trip"
APPLY_URL = "https://www.immigration.go.tz"

_ALIASES = {
    "usa": "united states of america",
    "us": "united states of america",
    "u.s.": "united states of america",
    "u.s.a.": "united states of america",
    "america": "united states of america",
    "united states": "united states of america",
    "uk": "united kingdom",
    "britain": "united kingdom",
    "england": "united kingdom",
    "uae": "united arab emirates",
    "korea": "korea (south) republic",
    "south korea": "korea (south) republic",
}

_RECORD = re.compile(
    r"\b\d{1,3}\s+([A-Za-z][A-Za-z'().\- ]{1,48}?)\s+"
    r"(No Visa Requirements?|Yes\s+No\s+(\d+)\s+USD|No\s+Yes\s+(\d+)\s+USD)\b",
    re.IGNORECASE,
)

_records: list[dict] | None = None
_plan_rows: list[dict] | None = None


def entry_lines(passport: str, location: str) -> list[dict]:
    """Short receipt rows for entering Tanzania. No advisory paragraphs."""
    if location == "inside" and not (passport or "").strip():
        return [
            {"label": "Country entry", "value": "Inside Tanzania"},
            {"label": "Park fees", "value": "Still apply"},
        ]
    lines: list[dict] = []
    record = lookup_passport(passport) if (passport or "").strip() else None
    referral = bool(record and record["visa"] == "Referral")
    if (passport or "").strip() and record is None:
        lines.append({"label": "Passport", "value": f"{passport.strip()} — not on the loaded eligibility list"})
    elif record:
        lines.append({"label": "Passport", "value": record["country"]})
        lines.append({"label": "Visa", "value": record["visa"]})
        if record.get("fee"):
            lines.append({"label": "Visa fee", "value": record["fee"]})
        if record["visa"] == "Not required":
            lines.append({"label": "Bring", "value": "Return ticket"})
            lines.append({"label": "Source", "value": "List of countries with visa eligibility; Tanzania visa guideline"})
            return lines
    else:
        lines.append({"label": "Passport", "value": "Not written"})
    lines.append({"label": "Apply", "value": APPLY_URL})
    if referral:
        lines.append({"label": "Apply by", "value": "At least 2 months before travel"})
        lines.append({"label": "Visa on arrival", "value": "Not available without Commissioner General approval"})
    else:
        lines.append({"label": "Visa on arrival", "value": "Official entry point"})
    lines.extend(
        [
            {"label": "Official site only", "value": "immigration.go.tz"},
            {"label": "Passport validity", "value": "At least 6 months, and one unused page"},
            {"label": "Bring", "value": "Return ticket"},
            {"label": "Processing", "value": "10 days, except referral visas"},
            {"label": "Who applies", "value": "Each passport, including children"},
            {"label": "Payment", "value": "Visa or Mastercard"},
            {"label": "Grant notice", "value": "Not final permission to enter"},
            {"label": "Source", "value": "Tanzania visa guideline; list of countries with visa eligibility"},
        ]
    )
    return lines


def lookup_passport(passport: str) -> dict | None:
    wanted = _ALIASES.get(passport.strip().lower(), passport.strip().lower())
    hits = [
        record
        for record in _load_records()
        if record["key"] == wanted or record["key"].startswith(wanted + " ")
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def plan_rows() -> list[dict]:
    """Steps and seasons copied from the live TANAPA plan-a-trip page."""
    global _plan_rows
    if _plan_rows is not None:
        return list(_plan_rows)
    text = _fetch_plan()
    rows: list[dict] = []
    if not text:
        _plan_rows = []
        return []
    for label in (
        "Choose a park",
        "Pick the season",
        "Permits and bookings",
        "Travel and stay",
        "Safety and rules",
        "Fees and payments",
    ):
        if label.lower().replace(" and ", " & ") in text.lower() or label.lower() in text.lower():
            rows.append({"label": "Plan step", "value": label})
    for label, window in (("Dry season", "Jun–Oct"), ("Short rains", "Nov–Dec"), ("Long rains", "Mar–May")):
        if window in text or window.replace("–", "-") in text:
            rows.append({"label": label, "value": window})
    if rows:
        rows.append({"label": "Source", "value": PLAN_URL})
    _plan_rows = rows
    return list(rows)


def _load_records() -> list[dict]:
    global _records
    if _records is not None:
        return _records
    if not ELIGIBILITY.exists():
        _records = []
        return _records
    text = re.sub(r"\s+", " ", "\n".join(page.extract_text() or "" for page in PdfReader(str(ELIGIBILITY)).pages))
    found: list[dict] = []
    seen: set[str] = set()
    for match in _RECORD.finditer(text):
        country = re.sub(r"\s+", " ", match.group(1)).strip(" .")
        key = country.lower()
        if key in seen or len(country) < 3:
            continue
        seen.add(key)
        status = match.group(2)
        ordinary_fee = match.group(3)
        referral_fee = match.group(4)
        if status.lower().startswith("no visa"):
            visa, fee = "Not required", ""
        elif referral_fee:
            visa, fee = "Referral", f"{referral_fee} USD"
        else:
            visa, fee = "Ordinary", f"{ordinary_fee} USD"
        if "united states" in key:
            visa, fee = "Multiple entry", fee or "100 USD"
        found.append({"country": country, "key": key, "visa": visa, "fee": fee})
    _records = found
    return _records


def _fetch_plan() -> str:
    try:
        response = httpx.get(PLAN_URL, timeout=8, follow_redirects=True, headers={"User-Agent": "SafariAI/0.1"})
        response.raise_for_status()
    except Exception:
        return ""
    text = re.sub(r"<script[\s\S]*?</script>", " ", response.text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text))
