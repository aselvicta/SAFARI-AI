"""Tokenization and date helpers shared by retrieval and generation."""

from __future__ import annotations

import re
from datetime import date

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN.finditer(text or "") if len(match.group(0)) > 1]


def parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def format_area(value: float | None) -> str:
    if value is None:
        return "not recorded in the loaded map extract"
    if float(value).is_integer():
        return f"{int(value):,}"
    rendered = f"{value:,.2f}".rstrip("0").rstrip(".")
    return rendered
