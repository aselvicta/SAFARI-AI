# How SafariAI works

This page explains, without too much jargon, how SafariAI turns a question into an answer and what it does to stay accurate.

## From question to answer

When someone asks a question, SafariAI first works out what they want: which park, whether it's about fees, wildlife, visas or planning, and whether they wrote in English or Kiswahili. It also uses any trip details they've given, such as their passport and the ages of their children.

Next, the AI model (DeepSeek) looks things up. It can't answer from its own memory. Instead it has a small set of lookups to choose from: the official fee table, the trip cost calculator, park pages, the visa list, and a search over official documents. It picks the ones it needs, reads what they return, and writes the answer from that.

Before the answer is shown, SafariAI checks it. Every price or number in the answer has to appear in the information that was looked up, and an answer based on that information has to say which source each fact came from. If the draft fails the check, the model is asked to rewrite it once. If it fails again, or if DeepSeek isn't reachable, SafariAI answers with a simpler built-in template that uses the same official information, so the visitor still gets a correct answer.

## Rules it follows

- A fee is only quoted if TANAPA's table says it applies on the visitor's travel date.
- Trip totals are worked out by the calculator, never by the AI model, because language models are bad at arithmetic.
- The fee class comes from the passport: Tanzanian and East African citizens, foreign residents, and everyone else pay different rates.
- Ngorongoro, the game reserves and Zanzibar are run by other authorities, so questions about them are pointed to the right office.
- When the official sources don't cover a question, SafariAI says so and gives the official page to check, instead of guessing.

## Where the information comes from

Most of it comes from TANAPA's website, which has a public data feed with every fee, its validity dates, the 21 park pages, activities, accommodation and contacts. SafariAI also reads TANAPA's published PDFs (guidelines, regulations and brochures) and the Tanzania Immigration visa list.

The fees and park pages are fetched again every 12 hours. If a source can't be reached, the last good copy stays in use, and the admin dashboard shows the problem.

## Trip budgets from anywhere in Tanzania

When a visitor says where they start (Dar es Salaam, Mwanza, Mbeya and about 30 other towns), SafariAI can cost the whole trip, not just park entry. Every line says where its number comes from:

- **Live:** hotel rates near the park gate for the travel dates, from booking sites via Xotelo, and today's Bank of Tanzania exchange rate. That rate comes from Driftmark's feed, or straight from the bank's own page when the feed is down.
- **Official:** TANAPA park and vehicle fees, EWURA's monthly fuel cap price for the visitor's town (about 190 towns), and LATRA's per-kilometre bus fare cap.
- **Estimate:** only the fuel a car uses (road distance from OpenStreetMap × 12 litres per 100 km).

A 10% buffer is added on the live and estimated lines, because those prices move. Costs that have no reliable source, such as safari vehicle hire, food, NCAA transit fees or the boat to Gombe, are listed as not included instead of being guessed.

USD amounts for non-resident fees are TANAPA's own USD prices (TANAPA bills them at 2,555 TZS per USD). Every other conversion uses the live Bank of Tanzania rate.

The exchange rate is refreshed hourly. Fuel prices and the hotel list are checked daily and weekly, and hotel rates are fetched when someone asks, then kept for six hours.

## How search works

To find the right passage in hundreds of pages of documents, SafariAI scores every passage in two ways: how many of the question's words it contains, and how similar its wording is overall. It then gives extra weight to official sources and to documents that are currently in force, so an old tariff never beats the current one. Only the best few passages from each document are passed to the AI model, so one long PDF can't crowd out everything else.

## Adding documents

New PDFs or text files are split into short passages and added to the search. If a document has a validity period or is an official tariff, a small file beside it can say so. See [`backend/knowledge/documents/README.md`](../backend/knowledge/documents/README.md).

## Checking quality

A set of test questions in `backend/evaluation/questions.json` covers fees, trip costs, wildlife, visas, Kiswahili and questions SafariAI should refuse. Running `services.cli evaluate`, or **System & quality** in the admin dashboard, scores the answers against them. The automated tests in `backend/tests/` run without an internet connection, using a saved copy of TANAPA's data.
