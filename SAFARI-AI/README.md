# SafariAI technical guide

This guide is for developers who want to run, change or deploy SafariAI. If you just want to know what the project is, read the [main README](../README.md) first.

The project has two parts. `backend/` is the Python server that answers questions, and `frontend/` is the website, including the admin dashboard.

## What you need

- Python 3.11 or newer
- Node.js 20 or newer
- A DeepSeek API key, if you want the AI model to write the answers. Without one, SafariAI still works and answers from fixed templates.

## Running it on your computer

Start the backend:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env                       # put your DEEPSEEK_API_KEY in this file
.venv/bin/python -m services.cli harvest   # downloads the official TANAPA data, takes about a minute
.venv/bin/uvicorn api.main:app --reload
```

Then start the website in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173 to use it. The admin dashboard is at http://127.0.0.1:5173/admin.

## Running it with Docker

If you have Docker, this starts the database, the backend and the website together:

```bash
cp backend/.env.example backend/.env       # set DEEPSEEK_API_KEY, SAFARI_ADMIN_USERNAME and SAFARI_ADMIN_PASSWORD
docker compose up -d --build
docker compose exec api python -m services.cli harvest   # only needed the first time
```

The site is then at http://127.0.0.1:8080. Stop it with `docker compose down`.

## Settings

All settings live in `backend/.env`. The ones you will most likely change:

| Setting | What it does |
|---|---|
| `DEEPSEEK_API_KEY` | Turns on the AI model. Leave it empty to use templates only. |
| `SAFARI_ADMIN_USERNAME`, `SAFARI_ADMIN_PASSWORD` | The login for `/admin`. Set these before putting the site online. |
| `SAFARI_STORE` | `memory` keeps data in a local file, `postgres` uses a database (needs `DATABASE_URL`). |
| `SAFARI_REFRESH_HOURS` | How often fees and park data are fetched again from TANAPA. The default is 12. |
| `SAFARI_TZS_PER_USD` | The exchange rate used for the rough USD amounts shown next to TZS prices. |

The full list, with notes, is in [`backend/.env.example`](backend/.env.example).

## Useful commands

Run these from `backend/`:

```bash
.venv/bin/python -m services.cli ask "Plan 3 days in Tarangire" --passport Germany --adults 2
.venv/bin/python -m services.cli status      # when each source was last updated
.venv/bin/python -m services.cli evaluate    # score the answers against a set of test questions
.venv/bin/pytest                             # run the tests
```

## Putting it online

SafariAI runs on three free services. The website is on Cloudflare Pages, the backend on Render, and the database on Supabase.

1. **Supabase.** Create a project in the Frankfurt region and keep the database password somewhere safe. Click **Connect**, copy the **Session pooler** connection string, add `?sslmode=require` to the end, and keep it for the next step. The other connection strings don't work from Render.
2. **Render.** Choose **New → Blueprint** and pick this repository. It reads `render.yaml` and sets up the backend. Paste in the Supabase connection string as `DATABASE_URL`, your DeepSeek key, an admin username and password, and a long random `SAFARI_PROXY_SECRET`. When it's live, `https://your-service.onrender.com/v1/health` should answer.
3. **Cloudflare Pages.** Choose **Workers & Pages → Create → Pages → Connect to Git** and pick this repository. Set the root directory to `SAFARI-AI/frontend`, the build command to `npm run build` and the output directory to `dist`. Add three variables: `API_ORIGIN` (your Render address), `PROXY_SECRET` (the same value as on Render) and `NODE_VERSION` set to `22`.
4. **First run.** Open `/admin` on your new site, sign in, and run **Sources & sync → Full harvest** once to load the TANAPA publications.

Render's free plan goes to sleep after 15 minutes without visitors, and the first visit afterwards is slow. A free uptime monitor such as UptimeRobot, checking `/v1/health` every 5 minutes, keeps it awake.

After that, every push to `main` updates the site.

## The admin dashboard

`/admin` is for the people looking after the site. It shows how many questions come in, how well they are answered, which parks and topics people ask about, and when they ask. It also lists questions the official sources couldn't answer, so you know what information is missing. From there you can read visitor feedback, check fees and park data, add or remove documents, and refresh the data from TANAPA.

## Adding documents

You can add official PDFs or text files from the **Documents** page in the admin dashboard, or from the command line as explained in [`backend/knowledge/documents/README.md`](backend/knowledge/documents/README.md).

## More detail

[How it works](docs/how-it-works.md) explains how a question becomes an answer, how search works, and the rules SafariAI follows to stay accurate.
