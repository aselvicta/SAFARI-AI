# Retrieval

A question is rewritten (Swahili markers expand into English search terms; a follow-up can reuse a park from the session). Each chunk then receives:

```text
Score = 0.34*S_semantic + 0.24*S_keyword + 0.18*S_reranker + 0.14*S_authority + 0.10*S_freshness
```

- Semantic: cosine similarity of hashed embeddings.
- Keyword: BM25, normalized by the best score in the candidate set.
- Reranker: share of query tokens found in the chunk, plus a bonus when the park or the document type matches the intent. A cross-encoder can replace this function without changing the formula.
- Authority: official 1.0, official brochure or newsletter 0.95, curated park profile 0.85, expert 0.80, operator 0.60, unverified upload 0.50, system scope note 0.45, blog 0.30, sample 0.20.
- Freshness: 1.0 when `status=current` and `as_of` sits inside the effective window; 0.05 when the document is superseded or past `effective_until`.

If any in-force document exists for the same park and document type, superseded candidates are multiplied by 0.25. They remain available to inspect. They are not eligible to supply a quoted fee.

```text
Recall@K = relevant documents in the top K / all relevant documents
Precision@K = relevant documents in the top K / K
```

`services/retrieval/index.py` caches token statistics per store version, so a question does not re-tokenize the corpus. At most two chunks per document reach the agent, so one long PDF cannot crowd out the rest.

`services/evaluation/metrics.py` computes F1@K, reciprocal rank, and nDCG. `evaluation/questions.json` checks fees, estimates, species, visas, contacts, scope boundaries and Swahili.
