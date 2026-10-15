# Architecture

```text
Visitor (web, CLI)
  -> FastAPI (/v1/ask, /v1/ask/stream)
  -> understand: intent, language, parks, animal, fee category, follow-up park from session
  -> agent (DeepSeek tool calls)  or  composer (same tools, deterministic)
       tools read: fee rows (records), park cards (GIS map + live page), visa list, hybrid index
  -> grounding check on numbers -> answer + citations + blocks
```

Data lives in one store with three shapes:

- **Records**: structured rows from the TANAPA API (`tariff`, `park_profile`, `activity`, `accommodation`, `fee_note`). Fee questions are table lookups against these, filtered by the travel date.
- **Documents and chunks**: prose for retrieval (park pages, activity FAQs, PDFs, official pages), each with authority, status and an effective window.
- **Parks**: the 21-park catalog from the 2024 GIS map. It supplies slugs, aliases and the area/establishment facts.

The JSON store (`services/common/store.py`) and the PostgreSQL store (`services/common/postgres_store.py`, `infrastructure/postgres/init.sql`) implement the same operations.

`services/sources/harvest.py` writes each source in one batch and records its status. `refresh_api` is the quick path the server runs on a schedule.

The v2 plan, with the problems it fixed, is in `docs/architecture/v2-plan.md`.
