"""Hybrid candidate scoring and the current-document version gate."""

from __future__ import annotations

from datetime import date

from services.common.embeddings import HashEmbedder
from services.common.models import Chunk, ScoredChunk
from services.common.scoring import HybridWeights, bm25_scores, cosine, freshness_score, hybrid_score, in_force
from services.common.text import tokenize
from services.conversation.understand import UnderstoodQuery


def score_chunks(
    query: UnderstoodQuery,
    chunks: list[Chunk],
    embedder: HashEmbedder,
    as_of: date,
    weights: HybridWeights | None = None,
) -> list[ScoredChunk]:
    chosen = weights or HybridWeights()
    if not chunks:
        return []
    query_embedding = embedder.embed(query.retrieval_query)
    query_tokens = tokenize(query.retrieval_query)
    document_tokens = [tokenize(f"{chunk.title} {chunk.text}") for chunk in chunks]
    keyword_scores = bm25_scores(query_tokens, document_tokens)
    scored: list[ScoredChunk] = []
    for chunk, keyword in zip(chunks, keyword_scores):
        semantic = cosine(query_embedding, chunk.embedding) if chunk.embedding else 0.0
        fresh = freshness_score(chunk, as_of)
        reranker = 0.0
        scored.append(
            ScoredChunk(
                chunk=chunk,
                semantic=semantic,
                keyword=keyword,
                reranker=reranker,
                authority=chunk.authority_score,
                freshness=fresh,
                score=hybrid_score(semantic, keyword, reranker, chunk.authority_score, fresh, chosen),
            )
        )
    return scored


def apply_version_gate(scored: list[ScoredChunk], as_of: date) -> list[ScoredChunk]:
    """If a current in-force document exists for the same park and type, sink older copies."""
    current_keys = {
        (item.chunk.park_slug, item.chunk.document_type)
        for item in scored
        if in_force(item.chunk, as_of)
    }
    for item in scored:
        key = (item.chunk.park_slug, item.chunk.document_type)
        if key in current_keys and not in_force(item.chunk, as_of):
            item.score *= 0.25
            item.version_penalized = True
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored
