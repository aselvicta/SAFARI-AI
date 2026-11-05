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

The JSON store (`backend/services/common/store.py`) and the PostgreSQL store (`backend/services/common/postgres_store.py`, `backend/postgres/init.sql`) implement the same operations.

`backend/services/sources/harvest.py` writes each source in one batch and records its status. `refresh_api` is the quick path the server runs on a schedule.

The v2 plan, with the problems it fixed, is in `docs/architecture/v2-plan.md`.

Every question and rating is appended to `backend/.data/events.jsonl` and `feedback.jsonl` (`backend/services/analytics/`). The admin API (`backend/api/admin.py`) turns those logs and the store into the dashboard at `/admin` (`frontend/src/admin/`).
