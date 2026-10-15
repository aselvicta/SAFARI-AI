# PostgreSQL for structured facts, JSON for the first runnable index

Fee questions are table lookups. Park area is a column. Prose guidelines are chunks. Putting both in one undifferentiated vector index makes an old tariff and a current tariff look the same.

Phase 1 keeps one engine and two stores. The default store is a JSON file so the assistant runs without Docker. PostgreSQL with pgvector is the store behind `docker compose up`: parks, fees, documents, versions, and `vector(384)` chunks. Hybrid scoring stays in Python so the weights on an answer can be shown. `PostgresStore.semantic_candidates` is the nearest-neighbour query for when a full scan is no longer enough.
