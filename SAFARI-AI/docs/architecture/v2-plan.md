# SafariAI v2 — plan

## What was wrong in v1

| Area | Finding | Effect on visitors |
|---|---|---|
| Sources | TANAPA's site is a Next.js app. v1 scraped rendered HTML and got navigation text ("View Full Tariff", emoji). | Fee, park and activity facts never reached the index. |
| Fees | Only the 2023/24 PDF tariff was parsed; it is out of force. | Every fee question abstained. |
| Species | Wildlife answers looked only at the first 320 characters of the top 8 chunks. | "Can I see elephants in Mikumi?" abstained although the brochure says yes. |
| Index | 4 scanned PDFs indexed with 0 characters; Spanish/Russian/German/French brochures indexed although meant to be skipped. | Noise in retrieval. |
| Generation | Templated strings plus an LLM rewrite that is discarded whenever a validator trips. | Stiff, repetitive answers. |
| Sessions | The web app sends `session_id: "desk"` for everyone. | Every visitor shares one conversation memory. |
| UI | A plain chat with a form row and animal buttons; answers are plain text; citations are never shown. | No trust signals, no structure. |
| Ops | No source freshness tracking, no refresh schedule, admin page links a stylesheet that does not exist, upload endpoint is open. | Stale data and an open write endpoint. |
| Secrets | `.env.example` holds a live DeepSeek key. | Key leak if the repo is shared. |

## Sources (verified 2026-10-15)

TANAPA's site is backed by a Strapi API at `https://tanzaniaparks.go.tz/api/*`:

| Endpoint | Records | Used for |
|---|---|---|
| `tariff-items` | 2,625 rows, valid 2026-07-01 → 2027-06-30 (entrance high season 2026-05-16 → 2027-03-14) | Entrance, vehicle, walking safari, ranger, crew, camping, rescue fees |
| `web-national-parks` | 26 (21 parks + 5 heritage sites) | Description, zone, slogan, area, temperature, elevation, image |
| `activities` | 29 | Activity descriptions, gear, FAQ |
| `attractions` | 25 | Attractions and the parks they belong to |
| `accommodation-options` | 9 | Lodging types and price bands |
| `park-contacts` | 26 | Phone, email, address per park |
| `web-publications` | 28 | PDF publications (acts, guidelines, brochures) |

Other sources stay as HTML or PDF: immigration visa guideline + eligibility list (PDF), NCAA, TAWA, TTB pages.

All amounts in `tariff-items` are TZS. The TZS figures are exact multiples of 2,555 (178,850 = 70 × 2,555), so a USD
equivalent is shown as an approximation at a configurable rate (`SAFARI_TZS_PER_USD`, default 2555) and is labelled as such.

## Target architecture

```text
services/
  sources/            connectors: one per source, all through one HTTP client (retry, backoff, timeout, UA)
    http.py           shared client
    tanapa_api.py     Strapi connector -> TariffItem, ParkProfile, Activity, Attraction, Contact, Publication
    documents.py      PDF publications, local official PDFs, HTML pages (boilerplate stripped)
    harvest.py        orchestrator: snapshots raw JSON, upserts structured records + chunks, records per-source status
  knowledge/          structured lookups over the store
    tariffs.py        fee rows by park / visitor class / age / date; trip estimate
    parks.py          merged park profile (GIS map facts + live TANAPA profile + contacts + activities)
    visa.py           passport -> visa rule (from the immigration PDFs)
  retrieval/          hybrid BM25 + vector, precomputed index, language + empty-doc filters
  agent/
    tools.py          search_knowledge, get_park, get_fees, estimate_trip_cost, check_visa, list_parks
    runner.py         LLM tool-calling loop (DeepSeek, OpenAI-compatible), streaming, grounding check
    fallback.py       deterministic composer using the same tools when no LLM is configured or it fails
    prompts.py        system prompt + policy
  conversation/       understanding (intent, language, entities), per-session memory with TTL
apps/api              FastAPI: /v1/ask, /v1/ask/stream (SSE), /v1/parks, /v1/fees, /v1/status, /v1/feedback, admin
apps/web              React app: hero, chat with rich answer cards, trip panel, park explorer, sources drawer, admin
```

### Answer policy (kept from v1, made precise)

1. A fee is quoted only from a structured official row whose validity window covers the travel date. Each fee shows the row's validity dates and source.
2. Every factual sentence must come from a tool result. Numbers in the final answer must appear in tool output; otherwise the agent retries once and then falls back to the deterministic composer.
3. Questions about Ngorongoro (NCAA), game reserves (TAWA), Zanzibar and visa rules that the index does not hold are pointed to the owning authority.
4. Answers are in the visitor's language (English or Swahili).

### Response contract

`POST /v1/ask` and the `final` event of `POST /v1/ask/stream` return:

```json
{
  "answer": "markdown subset: paragraphs, **bold**, - lists, [links](url), [1] citation markers",
  "language": "en|sw",
  "intent": "fee|planning|park_fact|wildlife|activity|visa|rules|scope|general|greeting",
  "abstained": false,
  "confidence": 0.82,
  "confidence_label": "HIGH|MEDIUM|LOW",
  "generator": "agent|composer",
  "citations": [{"n": 1, "document_id": "", "title": "", "organization": "", "authority": "", "status": "",
                  "effective_from": null, "effective_until": null, "source_url": "", "excerpt": "", "kind": "document|api|pointer"}],
  "blocks": [
    {"type": "fees", "park_slug": "", "park_name": "", "as_of": "", "valid_from": "", "valid_until": "", "in_force": true,
     "rows": [{"category": "Entrance", "item": "", "visitor": "non_resident|resident|expatriate|eac", "visitor_label": "",
               "age": "adult|child_5_15|student|any", "season": "high|low|all", "amount_tzs": 0, "amount_usd": 0}],
     "notes": [""], "source_url": ""},
    {"type": "parks", "parks": ["ParkCard"]},
    {"type": "estimate", "park_slug": "", "days": 0, "lines": [{"label": "", "qty": 0, "unit_tzs": 0, "total_tzs": 0}],
     "total_tzs": 0, "total_usd": 0, "excludes": [""]},
    {"type": "visa", "passport": "", "country": "", "visa": "", "fee": "", "lines": [{"label": "", "value": ""}], "source_url": ""}
  ],
  "recommended_parks": [{"slug": "", "name": "", "reason": ""}],
  "follow_ups": ["short suggested next questions"],
  "understood": {},
  "as_of": "YYYY-MM-DD"
}
```

`ParkCard`: `slug, name, zone, circuit, area_km2, established_year, slogan, summary, image_url, temperature, elevation,
activities[], contact{phone,email,address}, source_url`.

SSE events from `/v1/ask/stream`: `status` `{"label": "Checking TANAPA tariffs"}`, `delta` `{"text": "..."}`, `final` (payload above), `error` `{"message": ""}`.

Other endpoints: `GET /v1/parks`, `GET /v1/parks/{slug}`, `GET /v1/fees?park=&as_of=`, `GET /v1/status`
(per-source last sync, record counts, LLM on/off), `POST /v1/feedback`, `POST /v1/briefing[?download=true]`,
`POST /v1/admin/harvest` and `POST /v1/documents` (both require `X-Admin-Token` when `SAFARI_ADMIN_TOKEN` is set).

## UI direction

Taken from the reference in `docs/design/reference`: deep forest green, electric yellow accent, a heavy serif display face in
capitals, editorial photo cards. The visitor sees:

- A hero with live park photography and one input ("Where do you want to go?").
- A chat workspace whose answers render as cards: fee tables with validity dates, park cards with photos, a trip-cost
  estimate, a visa card, numbered citations that open a sources drawer, and follow-up chips.
- Live status while the agent works ("Checking TANAPA tariffs 2026/27…") and streamed text.
- A trip panel (passport, start, days, adults, child ages) that feeds every question and the PDF briefing.
- A park explorer (21 parks, filter by zone/activity).
- A freshness badge ("Fees synced from TANAPA · 15 Oct 2026").
- EN/SW toggle, keyboard and screen-reader support, mobile layout.

## Evaluation

`evaluation/questions.json` grows to cover answered fees, species from official text, activities, contacts, visa by
passport, scope boundaries, Swahili, and follow-ups. Offline tests run against snapshot fixtures in `tests/fixtures`
so they do not need the network.
