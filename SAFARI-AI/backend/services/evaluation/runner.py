"""Run the expert-question file against the assistant."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from services.common.settings import ROOT
from services.engine import Assistant


def load_questions(path: Path | None = None) -> list[dict]:
    question_path = path or (ROOT / "evaluation" / "questions.json")
    return json.loads(question_path.read_text(encoding="utf-8"))


def evaluate(assistant: Assistant, questions: list[dict], as_of: date | None = None, use_llm: bool | None = False) -> dict:
    question_date = as_of or date.today()
    rows = []
    abstain_hits = 0
    abstain_total = 0
    citation_hits = 0
    park_recalls = []
    latencies = []
    for item in questions:
        started = time.perf_counter()
        result = assistant.ask(item["question"], as_of=question_date, profile=item.get("profile"), use_llm=use_llm)
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        recommended = [park["slug"] for park in result["recommended_parks"]]
        expected = item.get("expect_parks", [])
        park_recall = None
        if expected:
            park_recall = len(set(recommended) & set(expected)) / len(expected)
            park_recalls.append(park_recall)
        abstain_ok = None
        if "expect_abstain" in item:
            abstain_total += 1
            abstain_ok = result["abstained"] is item["expect_abstain"]
            abstain_hits += int(abstain_ok)
        cited = len(result["citations"]) > 0
        contains_ok = None
        if item.get("expect_contains") or item.get("expect_block"):
            contains_ok = all(needle.lower() in result["answer"].lower() for needle in item.get("expect_contains", []))
            if item.get("expect_block"):
                contains_ok = contains_ok and any(block["type"] == item["expect_block"] for block in result.get("blocks", []))
        if item.get("expect_citation", True):
            citation_hits += int(cited)
        else:
            citation_hits += 1
        rows.append(
            {
                "id": item["id"],
                "intent": result["intent"],
                "abstained": result["abstained"],
                "abstain_ok": abstain_ok,
                "park_recall": park_recall,
                "cited": cited,
                "contains_ok": contains_ok,
                "confidence_label": result["confidence_label"],
                "latency_ms": round(elapsed, 2),
            }
        )
    return {
        "questions": len(questions),
        "abstain_accuracy": (abstain_hits / abstain_total) if abstain_total else None,
        "mean_park_recall": (sum(park_recalls) / len(park_recalls)) if park_recalls else None,
        "citation_rate": citation_hits / len(questions) if questions else None,
        "contains_accuracy": (
            sum(1 for row in rows if row["contains_ok"]) / sum(1 for row in rows if row["contains_ok"] is not None)
            if any(row["contains_ok"] is not None for row in rows)
            else None
        ),
        "mean_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        "rows": rows,
    }
