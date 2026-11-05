# SafariAI Tanzania

A visitor agent for Tanzania's 21 national parks. It answers from official sources: live TANAPA fees for the travel date, park pages, activities, accommodation, contacts, and the immigration visa list. Every fact carries a citation, and it says so plainly when the sources don't cover a question.

## Run

The project has two parts: `backend/` (Python API and agent) and `frontend/` (React app with the visitor desk and admin dashboard).

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env                       # add DEEPSEEK_API_KEY for the LLM agent
.venv/bin/python -m services.cli harvest   # TANAPA API + publications + official pages (~1 min)
.venv/bin/uvicorn api.main:app --reload    # http://127.0.0.1:8000

# Frontend, in a second terminal
cd frontend
npm install
npm run dev                                # http://127.0.0.1:5173, proxies /v1 to the backend
```

Open http://127.0.0.1:5173. The admin dashboard is at `/admin`. `/?q=Serengeti%20entry%20fees` opens with a question already asked.

To run one process instead, run `npm run build` in `frontend/`. The backend then serves `frontend/dist` at http://127.0.0.1:8000. Set `SAFARI_WEB_DIST` to serve a build from somewhere else.

### Docker

```bash
cp backend/.env.example backend/.env     # set DEEPSEEK_API_KEY, SAFARI_ADMIN_USERNAME and SAFARI_ADMIN_PASSWORD
docker compose up -d --build             # PostgreSQL, backend :8000, frontend (nginx) :8080
docker compose exec api python -m services.cli harvest   # first run only: publications and pages
```

Open http://127.0.0.1:8080, and sign in at http://127.0.0.1:8080/admin with the username and password from `backend/.env`. In Docker the admin requests reach the API from the nginx container rather than localhost, so admin needs those credentials set. On its first start the API syncs fees and parks from the TANAPA API by itself. Data lives in the `safari_pg` and `safari_data` volumes, so it survives restarts. Run `docker compose down` to stop; adding `-v` also deletes the data.

From `backend/`:

```bash
.venv/bin/python -m services.cli ask "Plan 3 days in Tarangire" --passport Germany --adults 2 --child-ages 7,3
.venv/bin/python -m services.cli ask "Can I see elephants in Mikumi?" --no-llm
.venv/bin/python -m services.cli harvest --api-only   # fees and parks only (~2 s)
.venv/bin/python -m services.cli status
.venv/bin/python -m services.cli evaluate
.venv/bin/pytest
```

While it runs, the server refreshes the TANAPA API data every `SAFARI_REFRESH_HOURS` (default 12).

## Admin dashboard

`/admin` is for the people who run the desk.

| Section | What it shows and does |
|---|---|
| Overview | Alerts that need action (failed or stale sources, expiring tariffs, unindexed PDFs, incomplete parks, falling answer rate, unreviewed negative ratings). Headline KPIs with change against the previous period. Questions per day, top parks and topics, data totals, source health |
| Insights | Sessions per day, knowledge gaps (declined or low-confidence questions, grouped), parks asked about against parks recommended, source markets by passport, fee class, language, trip length, group size, hour of day (EAT), wildlife, out-of-remit questions, confidence, agent tool use, response-time percentiles |
| Questions | The full question log with search and filters for intent, park and outcome, per-question detail, CSV export |
| Feedback | Visitor thumbs up and down with the answer they saw. Mark each one reviewed, resolved or dismissed, with a note |
| Parks | All 21 parks with data from tanzaniaparks.go.tz: photo, circuit, area, non-resident entrance fee in force, fee row counts, profile completeness |
| Fees & tariffs | Tariff validity windows and days left, plus a browser over every fee row filtered by park, category, visitor class and validity |
| Documents | Index breakdown by type, publisher and authority. Scanned PDFs that need OCR. Upload, search and remove documents |
| Sources & sync | Per-source status and errors, a quick API sync or a full harvest, and the history of scheduled and manual runs |
| System & quality | Runs the evaluation question set and shows per-question results. Configuration, uptime, data files |

The period selector (today, 7, 30, 90 or 365 days) scopes the Monitor sections. Every ask is appended to `.data/events.jsonl` with its intent, parks, outcome, latency and trip details. Session ids are hashed, and IP addresses are never stored. Set `SAFARI_ADMIN_USERNAME` and `SAFARI_ADMIN_PASSWORD` before exposing the server; the dashboard then asks admins to sign in. The visitor desk has no admin link; it appears in the header only for a signed-in admin.

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
| `GET /v1/admin/overview?days=` | KPIs, daily series, breakdowns, knowledge gaps, alerts |
| `GET /v1/admin/questions[.csv]?q=&intent=&park=&outcome=` | Question log, or the CSV export |
| `GET /v1/admin/feedback`, `POST /v1/admin/feedback/{id}` | Feedback list and its review state |
| `GET /v1/admin/inventory`, `GET /v1/admin/fees` | Park, tariff and document inventory; filtered fee rows |
| `GET /v1/admin/documents`, `DELETE /v1/admin/documents/{id}`, `POST /v1/documents` | Manage the index |
| `POST /v1/admin/harvest[?full=true]`, `GET /v1/admin/harvests` | Sync sources; sync history |
| `POST /v1/evaluate`, `GET /v1/admin/evaluation`, `GET /v1/admin/system` | Quality check, configuration and data files |

`POST /v1/admin/login` takes `{username, password}` and returns a session token. Every other `/v1/admin/*` endpoint, plus `POST /v1/documents` and `POST /v1/evaluate`, needs that session token, or `SAFARI_ADMIN_TOKEN`, in `X-Admin-Token`. With neither credentials nor a token set, only localhost may call them.

`/v1/ask` is rate-limited to 30 questions per minute per client.

## Layout

```text
backend/
  api/              FastAPI app (main.py), admin router (admin.py), admin auth (security.py)
  services/sources  Connectors: TANAPA API, PDFs, pages, harvest orchestration
  services/knowledge  Fee lookup and estimates, park cards, visa rules
  services/agent    Tools, LLM loop, grounding check, deterministic composer, prompts
  services/analytics  Question and feedback logs, dashboard insights, inventory, alerts
  services/retrieval, ranking, conversation, ingestion, planning (PDF briefing), evaluation
  knowledge/        Park catalog (GIS map), source registry, official PDFs
  evaluation/       Questions scored by `services.cli evaluate` and the dashboard quality check
  tests/            Offline tests against tests/fixtures/tanapa_api_snapshot.json
  postgres/         Schema for the PostgreSQL store
  assets/brand/     Logos used in the PDF briefing
frontend/
  src/              Visitor desk: hero, chat, answer cards, trip panel, park explorer
  src/admin/        Admin dashboard, loaded only on /admin
  nginx.conf        Static app + /v1 proxy for the Docker image
docs/               Architecture, decisions, v2 plan, design reference
```

`SAFARI_STORE=memory` keeps the index in `backend/.data/knowledge.json`. `SAFARI_STORE=postgres` uses PostgreSQL with pgvector (`docker compose up`).
