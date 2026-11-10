<div align="center">

<img src="SAFARI-AI/backend/assets/brand/logo.png" alt="SafariAI logo" width="80" />

# SafariAI Tanzania

A helper for anyone planning a visit to Tanzania's national parks.

</div>

You ask a question, like *"How much is it to enter Serengeti?"* or *"Where can I see chimpanzees?"*, and SafariAI answers in English or Kiswahili. Every answer shows where its information came from, so you can check it yourself.

![The SafariAI home page](SAFARI-AI/docs/screenshots/visitor-desk.jpg)

## What it helps with

- Park entry fees for your travel dates, and what your whole group will pay
- Picking a park for the animals and scenery you want to see
- Visa rules for your passport
- Activities, places to stay and park contacts
- A trip summary you can download as a PDF

## Where the information comes from

All answers come from official sources:

- **TANAPA** (Tanzania National Parks Authority): park fees, park pages, activities, accommodation and their published guides
- **Tanzania Immigration**: the visa list for each country

SafariAI checks TANAPA for new information twice a day. It is an independent project, not run by TANAPA or the government, so please confirm fees with the park authority before you pay or travel.

## How it works

SafariAI is a **RAG agent**. RAG stands for *retrieval-augmented generation*, which means it looks up the facts first and only then writes the answer.

When you ask something, SafariAI searches the official fee tables, park pages and documents for what applies to you. Then an AI model (DeepSeek) writes the answer using only what was found. Before you see it, every price is checked against the official data and the sources are attached. If the official information doesn't cover your question, SafariAI tells you so and points you to the right office instead of guessing.

Think of a park desk officer who opens the official rate book before quoting you a price.

![An answer with its sources](SAFARI-AI/docs/screenshots/answer-with-sources.jpg)

## Where it runs

| Part | Service |
|---|---|
| The website | Cloudflare Pages |
| The assistant behind it | Render |
| The database | Supabase |
| The AI model | DeepSeek |

Everything runs on free plans while SafariAI is being tested.

## For developers

Installation, settings and deployment are in the [technical guide](SAFARI-AI/README.md). For a closer look at how answers are put together, read [how it works](SAFARI-AI/docs/how-it-works.md).

---

<div align="center">

Made with ❤️ by [aselvicta](https://github.com/aselvicta) for Tanzania's national parks and everyone on their way to see them.

</div>
