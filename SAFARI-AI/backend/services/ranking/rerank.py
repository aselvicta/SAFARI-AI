"""Lexical and metadata reranker.

A cross-encoder can replace `reranker_score` later. The hybrid formula stays the same.
"""

from __future__ import annotations

from datetime import date

from services.common.models import Chunk, ScoredChunk
from services.common.scoring import HybridWeights, hybrid_score
from services.common.text import tokenize
from services.conversation.understand import UnderstoodQuery
from services.retrieval.hybrid import apply_version_gate


INTENT_TYPES = {
    "wildlife": ("park_guide", "brochure", "attraction"),
    "park_fact": ("park_guide",),
    "planning": ("park_guide", "guideline"),
    "activity": ("activity", "park_guide"),
    "fee": ("fee_guide",),
    "rules": ("fee_guide", "guideline", "regulation", "procedure", "activity"),
    "safety": ("guideline", "activity", "regulation", "procedure"),
    "season": ("guideline", "park_guide", "brochure"),
    "accommodation": ("accommodation", "park_guide"),
    "visa": ("visa",),
    "contact": ("park_guide", "contact"),
}


def rerank(
    query: UnderstoodQuery,
    scored: list[ScoredChunk],
    as_of: date,
    weights: HybridWeights | None = None,
) -> list[ScoredChunk]:
    chosen = weights or HybridWeights()
    for item in scored:
        item.reranker = reranker_score(query, item.chunk)
        item.score = hybrid_score(
            item.semantic,
            item.keyword,
            item.reranker,
            item.authority,
            item.freshness,
            chosen,
        )
    return apply_version_gate(scored, as_of)


def reranker_score(query: UnderstoodQuery, chunk: Chunk) -> float:
    query_tokens = set(tokenize(query.retrieval_query))
    document_tokens = set(tokenize(f"{chunk.title} {chunk.text}"))
    overlap = 0.0
    if query_tokens:
        overlap = len(query_tokens & document_tokens) / len(query_tokens)
    bonus = 0.0
    if query.park_slugs and chunk.park_slug in query.park_slugs:
        bonus += 0.25
    if query.intent == "fee" and chunk.document_type == "tariff":
        bonus += 0.20
    if query.intent in {"planning", "park_fact"} and chunk.document_type == "park_profile":
        bonus += 0.12
    if query.intent == "scope" and chunk.document_type in {"scope", "authority"}:
        bonus += 0.30
    preferred = INTENT_TYPES.get(query.intent, ())
    if chunk.document_type in preferred:
        bonus += 0.18
    if query.animal and query.animal.rstrip("s") in chunk.text.lower():
        bonus += 0.15
    return min(1.0, 0.65 * overlap + bonus)
