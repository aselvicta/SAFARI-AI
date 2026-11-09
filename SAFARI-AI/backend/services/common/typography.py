"""House style for every piece of text visitors and admins see: no em dashes or en dashes.

They arrive from three places: our own copy, the official sources we index (TANAPA pages, PDFs), and the
LLM, which uses them freely. `clean_dashes` rewrites them by role so the sentence still reads well:

    the park — famous for X — is        →  the park, famous for X, is
    16 May 2026 – 14 Mar 2027           →  16 May 2026 to 14 Mar 2027
    children 5–15, Jun–Oct              →  children 5-15, Jun-Oct
    — a bullet                          →  - a bullet

A hyphen with a space on each side reads as a dash too, so it gets the same treatment ("Children 5 - 15"
→ "Children 5 to 15", "Brochure - English" → "Brochure, English"). Tight hyphens (5-15, well-known) and
"- " bullets at the start of a line are left alone.

`clean` applies it to every string inside a JSON-like value; `DashStream` applies it to streamed text.
"""

from __future__ import annotations

import re

DASHES = "—–‒―"  # em, en, figure dash, horizontal bar
_D = f"[{DASHES}]"

_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"(?m)^([ \t]*){_D}+[ \t]+"), r"\1- "),  # a dash used as a bullet
    (re.compile(rf"(\d)[ \t]+{_D}[ \t]+(?=\d)"), r"\1 to "),  # spaced range between figures or dates
    (re.compile(r"(\d)[ \t]+-[ \t]+(?=\d)"), r"\1 to "),  # the same written with a spaced hyphen
    (re.compile(r"(?<=[^\s|])[ \t]+-[ \t]+(?=[^\s|])"), ", "),  # a spaced hyphen standing in for a dash (not a table cell)
    (re.compile(r"(\w)[\u2013\u2012](?=\w)"), r"\1-"),  # tight en-dash range: 5–15, Jun–Oct, 2026–27
    (re.compile(rf"[ \t]*{_D}+[ \t]*"), ", "),  # any other dash joins two parts of a sentence
]
_TIDY: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?m)^, "), ""),  # a dash that opened a line or the text
    (re.compile(r",(?:[ \t]*,)+"), ","),  # ", ," from two dashes in a row
    (re.compile(r",[ \t]*([.;:!?)\]])"), r"\1"),  # ", ." / ", )" from a dash before punctuation
    (re.compile(r"([(\[])[ \t]*,[ \t]*"), r"\1"),  # "( , " from a dash after an opening bracket
    (re.compile(r":[ \t]*,[ \t]*"), ": "),
    (re.compile(r",[ \t]*$", re.MULTILINE), ""),  # a dash that ended a line
]
_ANY = re.compile(rf"{_D}|[ \t]-[ \t]")


def clean_dashes(text: str) -> str:
    if not text or not _ANY.search(text):
        return text
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    for pattern, replacement in _TIDY:
        text = pattern.sub(replacement, text)
    return text


def clean(value):
    """`clean_dashes` on every string in a dict / list / tuple structure (keys are left alone)."""
    if isinstance(value, str):
        return clean_dashes(value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


class DashStream:
    """Cleans text that arrives in pieces, giving the same result as cleaning the whole text at once.
    The tail a later piece could change is held back: the last dash run with the character and whitespace
    before it and everything after it up to one word character, or else the last character and any
    whitespace after it."""

    _TAIL = re.compile(rf"(?:\S?\s*[{DASHES}-]+[^\w{DASHES}-]*\w?|\S?\s*)$")

    def __init__(self) -> None:
        self.held = ""
        self.started = False

    def feed(self, text: str) -> str:
        buffer = self.held + text
        cut = self._TAIL.search(buffer).start()
        ready, self.held = buffer[:cut], buffer[cut:]
        return self._emit(ready, final=False)

    def flush(self) -> str:
        ready, self.held = self.held, ""
        return self._emit(ready, final=True)

    def _emit(self, text: str, final: bool) -> str:
        if not text:
            return ""
        # Stand-in characters on each side make the piece's edges read as mid-sentence, not as the start
        # or end of a line, unless it really is the start of the text or the end of the stream.
        before = "x" if self.started else ""
        after = "" if final else "x"
        cleaned = clean_dashes(before + text + after)
        self.started = True
        return cleaned[len(before) : len(cleaned) - len(after)]
