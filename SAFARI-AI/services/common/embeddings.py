"""Deterministic hashed embeddings.

The vectors make cosine search real and repeatable without a model download.
Swap in a sentence-transformer by implementing the same `embed` method; keep
EMBEDDING_DIM at 384 so PostgreSQL `vector(384)` stays valid, or migrate the column.
"""

from __future__ import annotations

import hashlib
import math
import re

from services.common.text import tokenize

EMBEDDING_DIM = 384
_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _bucket(token: str, buckets: int = EMBEDDING_DIM) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest, 16) % buckets


class HashEmbedder:
    dim = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = tokenize(text)
        if not tokens:
            tokens = [match.group(0).lower() for match in _TOKEN.finditer(text or "")]
        for token in tokens:
            vector[_bucket(token)] += 1.0
        for left, right in zip(tokens, tokens[1:]):
            vector[_bucket(f"{left}_{right}")] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]
