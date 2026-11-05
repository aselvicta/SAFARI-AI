"""Hybrid retrieval score, freshness, and confidence bands.

Score(d, q) = α S_semantic + β S_keyword + γ S_reranker + δ S_authority + ε S_freshness

Confidence = 0.35 retrieval + 0.25 reranker + 0.20 authority + 0.20 freshness
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date

from services.common.models import Chunk, Document
from services.common.text import parse_date


@dataclass(frozen=True)
class HybridWeights:
    semantic: float = 0.34
    keyword: float = 0.24
    reranker: float = 0.18
    authority: float = 0.14
    freshness: float = 0.10

    def as_formula(self) -> str:
        return (
            f"{self.semantic:.2f}*semantic + {self.keyword:.2f}*keyword + "
            f"{self.reranker:.2f}*reranker + {self.authority:.2f}*authority + "
            f"{self.freshness:.2f}*freshness"
        )


def hybrid_score(
    semantic: float,
    keyword: float,
    reranker: float,
    authority: float,
    freshness: float,
    weights: HybridWeights | None = None,
) -> float:
    chosen = weights or HybridWeights()
    return (
        chosen.semantic * semantic
        + chosen.keyword * keyword
        + chosen.reranker * reranker
        + chosen.authority * authority
        + chosen.freshness * freshness
    )


def confidence_score(retrieval: float, reranker: float, authority: float, freshness: float) -> float:
    return 0.35 * retrieval + 0.25 * reranker + 0.20 * authority + 0.20 * freshness


def confidence_label(score: float) -> str:
    if score >= 0.72:
        return "HIGH"
    if score >= 0.45:
        return "MEDIUM"
    return "LOW"


def in_force(record: Document | Chunk, as_of: date) -> bool:
    if record.status != "current":
        return False
    start = parse_date(record.effective_from)
    end = parse_date(record.effective_until)
    if start and as_of < start:
        return False
    if end and as_of > end:
        return False
    return True


def freshness_score(record: Document | Chunk, as_of: date) -> float:
    """Prefer a document whose effective window covers the question date."""
    start = parse_date(record.effective_from)
    end = parse_date(record.effective_until)
    if record.status == "superseded":
        return 0.05
    if start and as_of < start:
        return 0.20
    if end and as_of > end:
        return 0.05
    if record.status == "current" and (start or end):
        return 1.0
    if record.status == "current":
        return 0.75
    return 0.40


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def bm25_scores(query_tokens: list[str], documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25 normalized to the 0–1 range inside this candidate set."""
    count = len(documents)
    if count == 0:
        return []
    average_length = sum(len(tokens) for tokens in documents) / count or 1.0
    document_frequency: dict[str, int] = {}
    for tokens in documents:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    query_counts = Counter(query_tokens)
    raw_scores: list[float] = []
    for tokens in documents:
        term_frequency = Counter(tokens)
        length = len(tokens) or 1
        score = 0.0
        for token, query_frequency in query_counts.items():
            if token not in term_frequency:
                continue
            df = document_frequency.get(token, 0)
            idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
            freq = term_frequency[token]
            denominator = freq + k1 * (1 - b + b * length / average_length)
            score += idf * (freq * (k1 + 1) / denominator) * query_frequency
        raw_scores.append(score)
    peak = max(raw_scores) if raw_scores else 0.0
    if peak <= 0:
        return [0.0] * count
    return [min(1.0, score / peak) for score in raw_scores]
