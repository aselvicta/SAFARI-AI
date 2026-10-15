# SafariAI Tanzania

A visitor assistant for Tanzania's 21 national parks. Ask about entry fees, parks, wildlife, activities, accommodation or visas, and get an answer drawn from official TANAPA and Immigration sources. Every fact is cited, and the assistant says so when the sources don't cover a question.

## Features

- **Live official fees.** Reads TANAPA's tariff API and quotes only rates valid on your travel date (TZS, with an approximate USD figure).
- **Trip cost estimates.** Computed from the fee table by code, not by the LLM, with resident (R), expatriate (EX) and non-resident (NR) rates chosen from your passport.
- **Park guide.** Park profiles, activities, accommodation and contacts, plus park recommendations by wildlife and interest.
- **Visa check.** Visa rule and fee for a given passport.
- **Grounded answers.** Each number in an answer must appear in a tool result. If an answer fails that check, a deterministic composer writes it instead.
- **English and Kiswahili.** Answers stream to a React web app that also has an admin view and downloadable PDF trip briefings.

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python 3.11+, FastAPI, Server-Sent Events |
| Agent | DeepSeek (OpenAI-compatible tool calling); runs without an LLM using the deterministic composer |
| Retrieval | BM25 + hashed vectors, reranked by intent, authority and freshness |
| Storage | JSON file store, or PostgreSQL + pgvector |
| Frontend | React 19, Vite |

## Quick start

```bash
cd SAFARI-AI
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env                        # optional: set DEEPSEEK_API_KEY
.venv/bin/python -m services.cli harvest    # fetch official data (~1 min)
(cd apps/web && npm install && npm run build)
.venv/bin/uvicorn apps.api.main:app --reload
```

Open http://127.0.0.1:8000. The admin view is at `/admin`.

**Docker** (PostgreSQL + API): `cd SAFARI-AI && docker compose up --build`

## Usage

```bash
.venv/bin/python -m services.cli ask "Plan 3 days in Tarangire" --passport Germany --adults 2
.venv/bin/python -m services.cli ask "Can I see elephants in Mikumi?" --no-llm
.venv/bin/python -m services.cli status      # source sync status
.venv/bin/python -m services.cli evaluate    # score the evaluation question set
.venv/bin/pytest                             # offline test suite
```

The main endpoint is `POST /v1/ask`, with a streaming version at `POST /v1/ask/stream`. For the full API, see the [SafariAI README](SAFARI-AI/README.md#api).

## Configuration

Settings go in `SAFARI-AI/.env`. Every variable is listed in [`.env.example`](SAFARI-AI/.env.example).

| Variable | Purpose | Default |
|---|---|---|
| `DEEPSEEK_API_KEY` | Enables the LLM agent | empty (deterministic mode) |
| `SAFARI_STORE` | `memory` or `postgres` | `memory` |
| `SAFARI_REFRESH_HOURS` | How often the server re-syncs the TANAPA API | `12` |
| `SAFARI_TZS_PER_USD` | Rate for the approximate USD figures | `2555` |
| `SAFARI_ADMIN_TOKEN` | Protects admin endpoints | empty (localhost only) |

## Repository layout

```text
SAFARI-AI/
├── apps/api         FastAPI server, streaming, scheduled refresh
├── apps/web         React visitor app and admin view
├── services/        Sources, knowledge, agent, retrieval, planning, evaluation
├── knowledge/       Park catalog, source registry, official PDFs
├── evaluation/      Evaluation question set
├── tests/           Offline tests with an API snapshot fixture
├── docs/            Architecture, design decisions, pipeline notes
└── infrastructure/  Dockerfile, Postgres init script
```

The PDFs and the saved TANAPA publications page at the repository root are the original downloads. Copies used by the app are in `SAFARI-AI/knowledge/documents/`.

## Documentation

- [SafariAI README](SAFARI-AI/README.md): sources, answering rules, full API
- [Architecture overview](SAFARI-AI/docs/architecture/overview.md)
- [Hybrid retrieval](SAFARI-AI/docs/retrieval/hybrid.md)
- [Ingestion pipeline](SAFARI-AI/docs/ingestion/pipeline.md)
- Decisions: [Postgres and memory store](SAFARI-AI/docs/decisions/001-postgres-and-memory.md), [authority, freshness and abstaining](SAFARI-AI/docs/decisions/002-authority-freshness-abstain.md)

## Data sources

Data comes from the Tanzania National Parks Authority (TANAPA) website API and publications, and from Tanzania Immigration. Fees and rules change, so confirm with the official authority before you travel. Ngorongoro (NCAA), game reserves (TAWA) and Zanzibar are outside TANAPA, and the assistant refers those questions to the authority responsible for them.
