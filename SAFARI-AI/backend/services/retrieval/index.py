"""A cached hybrid index over the store's chunks.

v1 re-tokenized every chunk on every question. This index builds BM25 statistics once per
store version and reuses them, so a question costs one pass of arithmetic, not of parsing.
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from datetime import date

from services.common.embeddings import HashEmbedder
from services.common.models import Chunk, ScoredChunk
from services.common.scoring import HybridWeights, cosine, freshness_score, hybrid_score
from services.common.text import tokenize
from services.conversation.understand import UnderstoodQuery
from services.ranking.rerank import rerank

SEARCHABLE_LANGUAGES = {"en", "sw"}


class HybridIndex:
    def __init__(self, store, embedder: HashEmbedder | None = None, weights: HybridWeights | None = None) -> None:
        self.store = store
        self.embedder = embedder or HashEmbedder()
        self.weights = weights or HybridWeights()
        self._version = -1
        self._lock = threading.Lock()
        self.chunks: list[Chunk] = []
        self._tf: list[Counter] = []
        self._lengths: list[int] = []
        self._df: Counter = Counter()
        self._average = 1.0

    def _ensure(self) -> None:
        version = getattr(self.store, "version", 0)
        if version == self._version and self.chunks:
            return
        with self._lock:
            if version == self._version and self.chunks:
                return
            chunks = [chunk for chunk in self.store.all_chunks() if chunk.text.strip() and chunk.language in SEARCHABLE_LANGUAGES]
            tf, lengths, df = [], [], Counter()
            for chunk in chunks:
                tokens = tokenize(f"{chunk.title} {chunk.text}")
                counts = Counter(tokens)
                tf.append(counts)
                lengths.append(len(tokens) or 1)
                df.update(counts.keys())
            self.chunks, self._tf, self._lengths, self._df = chunks, tf, lengths, df
            self._average = (sum(lengths) / len(lengths)) if lengths else 1.0
            self._version = version

    def search(self, query: UnderstoodQuery, as_of: date, *, top_k: int = 24, exclude_types: set[str] | None = None, park_slug: str | None = None) -> list[ScoredChunk]:
        self._ensure()
        if not self.chunks:
            return []
        query_tokens = tokenize(query.retrieval_query)
        keyword = self._bm25(query_tokens)
        peak = max(keyword) if keyword else 0.0
        query_vector = self.embedder.embed(query.retrieval_query)
        scored: list[ScoredChunk] = []
        for index, chunk in enumerate(self.chunks):
            if exclude_types and chunk.document_type in exclude_types:
                continue
            if park_slug and chunk.park_slug not in (None, park_slug):
                continue
            kw = keyword[index] / peak if peak > 0 else 0.0
            semantic = cosine(query_vector, chunk.embedding) if chunk.embedding else 0.0
            if kw == 0.0 and semantic < 0.12:
                continue
            fresh = freshness_score(chunk, as_of)
            scored.append(
                ScoredChunk(
                    chunk=chunk,
                    semantic=semantic,
                    keyword=kw,
                    reranker=0.0,
                    authority=chunk.authority_score,
                    freshness=fresh,
                    score=hybrid_score(semantic, kw, 0.0, chunk.authority_score, fresh, self.weights),
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        ranked = rerank(query, scored[: top_k * 4], as_of, self.weights)
        return _diverse(ranked, top_k)

    def _bm25(self, query_tokens: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
        count = len(self.chunks)
        query_counts = Counter(query_tokens)
        idf = {token: math.log(1 + (count - self._df.get(token, 0) + 0.5) / (self._df.get(token, 0) + 0.5)) for token in query_counts if self._df.get(token)}
        scores = []
        for counts, length in zip(self._tf, self._lengths):
            score = 0.0
            for token, weight in idf.items():
                freq = counts.get(token)
                if freq:
                    score += weight * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * length / self._average)) * query_counts[token]
            scores.append(score)
        return scores


def _diverse(ranked: list[ScoredChunk], top_k: int, per_document: int = 2) -> list[ScoredChunk]:
    """At most two chunks from one document, so one long PDF cannot fill the context."""
    seen: Counter = Counter()
    kept = []
    for item in ranked:
        if seen[item.chunk.document_id] >= per_document:
            continue
        seen[item.chunk.document_id] += 1
        kept.append(item)
        if len(kept) >= top_k:
            break
    return kept
