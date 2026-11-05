"""Visa rule for a passport, from the immigration PDFs on file."""

from __future__ import annotations

from services.planning.entry import APPLY_URL, entry_lines, lookup_passport
from services.planning.briefing import starting_place

GUIDELINES_URL = "https://visa.immigration.go.tz/guidelines"


def visa_block(passport: str, origin: str = "") -> dict | None:
    passport = (passport or "").strip()
    if not passport:
        return None
    record = lookup_passport(passport)
    return {
        "type": "visa",
        "passport": passport,
        "country": record["country"] if record else passport,
        "visa": record["visa"] if record else "Not on the loaded eligibility list",
        "fee": (record or {}).get("fee") or "",
        "found": record is not None,
        "lines": entry_lines(passport, starting_place(origin) if origin else "outside"),
        "apply_url": APPLY_URL,
        "source_url": GUIDELINES_URL,
    }
