# SafariAI Tanzania

A visitor agent for Tanzania's 21 national parks. It answers from official sources: live TANAPA fees for the travel date, park pages, activities, accommodation, contacts, and the immigration visa list. Every fact carries a citation, and it says so plainly when the sources don't cover a question.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env                       # add DEEPSEEK_API_KEY for the LLM agent
.venv/bin/python -m services.cli harvest   # TANAPA API + publications + official pages (~1 min)
cd apps/web && npm install && npm run build && cd ../..
.venv/bin/uvicorn apps.api.main:app --reload
```

Open http://127.0.0.1:8000. The admin view is at `/admin`. `/?q=Serengeti%20entry%20fees` opens with a question already asked.

```bash
.venv/bin/python -m services.cli ask "Plan 3 days in Tarangire" --passport Germany --adults 2 --child-ages 7,3
.venv/bin/python -m services.cli ask "Can I see elephants in Mikumi?" --no-llm
.venv/bin/python -m services.cli harvest --api-only   # fees and parks only (~2 s)
.venv/bin/python -m services.cli status
.venv/bin/python -m services.cli evaluate
.venv/bin/pytest
```

While it runs, the server refreshes the TANAPA API data every `SAFARI_REFRESH_HOURS` (default 12).

## Sources

| Source | How | Gives |
|---|---|---|
| TANAPA website API (`tanzaniaparks.go.tz/api`) | JSON, paginated | 2,600+ fee rows with validity dates, 21 park pages with photos, 29 activities, accommodation types, park contacts, fee notes and FAQ |
| TANAPA publications | PDF | Regulations, guidelines, acts, the English and Kiswahili brochures |
| TANAPA GIS map (2024) | curated in `knowledge/metadata/parks.json` | Area, year established, gazette notice |
| Tanzania Immigration | PDF on file | Visa rule and fee by passport |
| TANAPA plan-a-trip, TAWA, NCAA | HTML, boilerplate stripped | Seasons, rules, scope pointers |

Raw API snapshots are saved to `.data/raw/` for audit. Every source's last sync, record counts and errors appear at `/v1/status` and in the admin view. If a source fails, its previous data stays in place.

A redirect to another domain is rejected. At the time of writing, `ncaa.go.tz` sends non-browser clients to an unrelated site. Scanned PDFs with no text layer are listed as `needs_ocr` instead of being indexed empty.

## How an answer is made

```text
question + trip details
  -> understand (intent, language, parks, animal, fee category)
  -> agent: DeepSeek with tools                  | composer: same tools, no LLM
       get_fees, estimate_trip_cost, get_park,    |   (used when no key is set, the
       recommend_parks, check_visa,               |    LLM fails, or a draft fails
       search_knowledge                           |    the grounding check)
  -> grounding check: every number in the answer must appear in a tool result
  -> answer (markdown, [n] citations) + UI blocks (fee table, estimate, park cards, visa)
```

Answering rules:

- A fee is quoted only from an official row whose validity window covers the travel date. Amounts are official TZS figures; the USD figure is approximate, at `SAFARI_TZS_PER_USD` (TANAPA prices at 2,555).
- Totals come from `estimate_trip_cost`, never from model arithmetic. Children under 5 enter free; ages 5–15 pay the child rate.
- Fee class follows the passport: East African Community (R), expatriate/permit holder (EX), non-resident (NR).
- Ngorongoro (NCAA), game reserves (TAWA) and Zanzibar are pointed to their own authority.
- English and Kiswahili.

Retrieval is BM25 plus hashed vectors over a cached index, reranked by intent, authority and freshness. See `docs/retrieval/hybrid.md`.

## API

| Endpoint | |
|---|---|
| `POST /v1/ask` | `{question, session_id, as_of?, language?, profile}` → answer, citations, blocks, follow-ups |
| `POST /v1/ask/stream` | Same, as Server-Sent Events: `status`, `delta`, `reset`, `final`, `error` |
| `GET /v1/parks`, `GET /v1/parks/{slug}` | Park cards, and one park with its fee table |
| `GET /v1/fees?park=&category=&as_of=` | Fee rows in force |
| `POST /v1/briefing[?download=true]` | Trip briefing as JSON or a PDF |
| `GET /v1/status` | Source sync status, counts, LLM on or off |
| `POST /v1/feedback` | Thumbs up or down, appended to `.data/feedback.jsonl` |
| `POST /v1/admin/harvest[?full=true]`, `POST /v1/documents` | Admin. Needs `X-Admin-Token` when `SAFARI_ADMIN_TOKEN` is set; without one, only localhost may call |

`/v1/ask` is rate-limited to 30 questions per minute per client.

## Layout

```text
apps/api          FastAPI, SSE streaming, scheduled refresh
apps/web          React visitor app and admin view
services/sources  Connectors: TANAPA API, PDFs, pages, harvest orchestration
services/knowledge  Fee lookup and estimates, park cards, visa rules
services/agent    Tools, LLM loop, grounding check, deterministic composer, prompts
services/retrieval, ranking, conversation, ingestion, planning (PDF briefing), evaluation
knowledge/        Park catalog (GIS map), source registry, official PDFs
evaluation/       Questions scored by `services.cli evaluate` and the test suite
tests/            Offline tests against tests/fixtures/tanapa_api_snapshot.json
docs/             Architecture, decisions, v2 plan, design reference
```

`SAFARI_STORE=memory` keeps the index in `.data/knowledge.json`. `SAFARI_STORE=postgres` uses PostgreSQL with pgvector (`docker compose up`).
