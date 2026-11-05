"""Retrieval and answer metrics."""

from __future__ import annotations

import math


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    if not relevant:
        return None
    found = set(retrieved[:k]) & set(relevant)
    return len(found) / len(relevant)


def precision_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    if k <= 0:
        return None
    found = set(retrieved[:k]) & set(relevant)
    return len(found) / k


def f1_at_k(retrieved: list[str], relevant: list[str], k: int) -> float | None:
    precision = precision_at_k(retrieved, relevant, k)
    recall = recall_at_k(retrieved, relevant, k)
    if precision is None or recall is None or precision + recall == 0:
        return 0.0 if precision is not None else None
    return 2 * precision * recall / (precision + recall)


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    wanted = set(relevant)
    for index, document_id in enumerate(retrieved, start=1):
        if document_id in wanted:
            return 1 / index
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    wanted = set(relevant)
    gains = [1.0 if document_id in wanted else 0.0 for document_id in retrieved[:k]]
    ideal = [1.0] * min(k, len(wanted))
    ideal_dcg = _dcg(ideal)
    if ideal_dcg == 0:
        return 0.0
    return _dcg(gains) / ideal_dcg


def _dcg(gains: list[float]) -> float:
    return sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
