"""Check that each cited figure comes from the source the answer cites for it.

The figures check in the runner only asks whether a number appears in *some* tool result. This module
asks the stricter question: in "Fuel costs TZS 740,048 [2]", is 740,048 part of what source [2] said?

Facts are collected from tool results: every dict that carries a cite number ("cite", "cite_*" or
"*_cite") vouches for the numbers inside it. Dicts marked `"derived": true` hold SafariAI's own
arithmetic (trip totals). A total that no source states may sit next to any cite, but a figure that a
source does state must carry that source's cite, even when it is also a subtotal. Strings under `not_included`
and `notes` are SafariAI's planning notes and should carry no cite at all.

An answer is split into segments, each ending in a run of cites. A segment is miscited when one of its
figures belongs to another source and to none of the ones it cites, or when it is a planning note
with a cite. `repair` rewrites those cite runs to the sources that do hold the figures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_NUMBER = re.compile(r"(?<![\w\[])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w\]])")
_CITE_RUN = re.compile(r"(?:\s*\[\d{1,2}\])+")
_CITE = re.compile(r"\[(\d{1,2})\]")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NOTE_KEYS = ("not_included", "notes")


@dataclass
class Facts:
    by_cite: dict[int, set[str]] = field(default_factory=dict)
    derived: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def owners(self, number: str) -> set[int]:
        return {cite for cite, numbers in self.by_cite.items() if _matches(number, numbers)}


@dataclass
class Miscite:
    segment: str
    cited: list[int]
    should_be: list[int]
    reason: str


def collect(results: list[dict]) -> Facts:
    facts = Facts()
    for result in results:
        _walk(result, facts)
    return facts


def check(text: str, facts: Facts) -> list[Miscite]:
    problems = []
    for body, cites, _start, _end in _segments(text):
        if not cites:
            continue
        figures = _figures(body)
        cited_numbers = set().union(*(facts.by_cite.get(cite, set()) for cite in cites))
        wrong = [number for number in figures if not _matches(number, cited_numbers) and facts.owners(number)]
        if wrong:
            should = sorted(set().union(*(facts.owners(number) for number in wrong)) | {cite for cite in cites if _supports(cite, figures, facts)})
            problems.append(Miscite(body.strip(), cites, should, "figures " + ", ".join(wrong) + " come from " + ", ".join(f"[{n}]" for n in sorted(set().union(*(facts.owners(number) for number in wrong))))))
            continue
        if not figures and _is_note(body, facts):
            problems.append(Miscite(body.strip(), cites, [], "this is SafariAI's own planning note, not something a source said"))
    return problems


def repair(text: str, facts: Facts) -> str:
    """Rewrite each miscited segment's cite run to the sources that hold its figures (none for notes)."""
    out, cursor = [], 0
    for body, cites, start, end in _segments(text):
        if not cites:
            continue
        figures = _figures(body)
        cited_numbers = set().union(*(facts.by_cite.get(cite, set()) for cite in cites))
        wrong = [number for number in figures if not _matches(number, cited_numbers) and facts.owners(number)]
        if wrong:
            keep = [cite for cite in cites if _supports(cite, figures, facts)]
            fixed = sorted(set(keep) | set().union(*(facts.owners(number) for number in wrong)))
        elif not figures and _is_note(body, facts):
            fixed = []
        else:
            continue
        run_start = start + len(body)
        out.append(text[cursor:run_start].rstrip() if not fixed else text[cursor:run_start])
        spacing = re.match(r"\s*", text[run_start:end]).group(0)
        out.append(spacing + "".join(f"[{cite}]" for cite in fixed) if fixed else "")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def describe(problems: list[Miscite], citations: list[dict]) -> str:
    titles = {citation["n"]: citation["title"] for citation in citations}
    lines = []
    for item in problems[:6]:
        cited = ", ".join(f"[{n}] {titles.get(n, '?')}" for n in item.cited)
        target = ", ".join(f"[{n}] {titles.get(n, '?')}" for n in item.should_be) or "no cite"
        lines.append(f'"{item.segment[:140]}" cites {cited}, but {item.reason}; use {target}')
    return "; ".join(lines)


# Internals -----------------------------------------------------------------


def _walk(node, facts: Facts) -> None:
    if isinstance(node, dict):
        cites = [value for key, value in node.items() if _is_cite_key(key) and isinstance(value, int)]
        if cites or node.get("derived") is True:
            numbers = _numbers_in({key: value for key, value in node.items() if not _is_cite_key(key) and key not in NOTE_KEYS})
            for cite in cites:
                facts.by_cite.setdefault(cite, set()).update(numbers)
            if node.get("derived") is True:
                facts.derived.update(numbers)
        for key, value in node.items():
            if key in NOTE_KEYS and isinstance(value, list):
                facts.notes.extend(str(item) for item in value)
            elif not _is_cite_key(key):
                _walk(value, facts)
    elif isinstance(node, list):
        for item in node:
            _walk(item, facts)


def _is_cite_key(key: str) -> bool:
    return key == "cite" or key.startswith("cite_") or key.endswith("_cite")


def _numbers_in(value) -> set[str]:
    text = json.dumps(value, ensure_ascii=False)
    return {_norm(item) for item in _NUMBER.findall(text)} | {_norm(item) for item in re.findall(r"\d+(?:\.\d+)?", text)}


def _segments(text: str):
    """(body, cites, start, end) per segment: text up to and including one run of cites.
    Segments never cross a line break, so a cite never vouches for an earlier bullet."""
    offset = 0
    for line in text.splitlines(keepends=True):
        cursor = 0
        for run in _CITE_RUN.finditer(line):
            body = line[cursor:run.start()]
            yield body, [int(n) for n in _CITE.findall(run.group(0))], offset + cursor, offset + run.end()
            cursor = run.end()
        offset += len(line)


def _figures(body: str) -> list[str]:
    body = _DATE.sub(" ", body)
    body = re.sub(r"(?m)^\s*\d+\.\s", " ", body)
    figures = []
    for raw in _NUMBER.findall(body):
        value = _norm(raw)
        try:
            if float(value) <= 15:
                continue
        except ValueError:
            continue
        figures.append(value)
    return figures


def _supports(cite: int, figures: list[str], facts: Facts) -> bool:
    numbers = facts.by_cite.get(cite, set())
    return any(_matches(number, numbers) for number in figures)


def _is_note(body: str, facts: Facts) -> bool:
    lowered = body.lower()
    for note in facts.notes:
        words = re.findall(r"[a-z]+", note.lower())
        size = 3 if len(words) >= 3 else len(words)
        if size >= 2 and " ".join(words[:size]) in " ".join(re.findall(r"[a-z]+", lowered)):
            return True
    return False


def _matches(number: str, pool: set[str]) -> bool:
    if number in pool:
        return True
    try:
        value = float(number)
    except ValueError:
        return False
    for item in pool:
        try:
            other = float(item)
        except ValueError:
            continue
        if other >= 10 and abs(other - value) <= max(0.51, other * 0.002):
            return True
    return False


def _norm(number: str) -> str:
    number = number.replace(",", "")
    if "." in number:
        whole, frac = number.split(".", 1)
        frac = frac.rstrip("0")
        return (whole.lstrip("0") or "0") + (f".{frac}" if frac else "")
    return number.lstrip("0") or "0"
