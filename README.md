# Lumora

**Open-source, self-hosted AI visibility tracker.** Lumora monitors how a brand
appears in AI assistant answers — ChatGPT, Claude, Gemini, and Perplexity — and
tracks that visibility over time. It's built for marketing agencies running
GEO/AEO (Generative / Answer Engine Optimization) services for their clients.

> Working name: Lumora · License: AGPL-3.0-or-later

## How it works

1. **Projects** define a brand, its aliases, and competitors.
2. **Prompts** are the natural-language questions you want to monitor (e.g.
   _"What are the best project management tools for agencies?"_).
3. A scheduled **snapshot run** sends each prompt to **every** configured AI
   provider and repeats it `N` times (default 3) to account for answer
   non-determinism, storing the raw **answers**.
4. An **LLM-as-judge** pipeline scores each answer: was the brand mentioned, at
   what position, with what sentiment, and which sources were cited.
5. Because each prompt is asked `N` times, visibility is reported as a **mention
   rate** (e.g. _"mentioned in 2/3 runs = 67%"_) rather than a binary flag.
6. Results are charted over time and exportable to **CSV**.

## Tech stack

| Layer      | Choice                                            |
| ---------- | ------------------------------------------------- |
| Backend    | Python + FastAPI                                  |
| ORM / DB   | SQLAlchemy 2.0 · SQLite (MVP) / Postgres (prod)   |
| Scheduling | APScheduler (cron-style runs)                     |
| Migrations | Alembic                                           |
| Frontend   | React + Recharts (placeholder for now)            |
| Deploy     | Docker Compose (app + Postgres)                   |

## Project layout

```
lumora/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI entry + health check + lifespan
│   │   ├── config.py        # Settings from .env (pydantic-settings)
│   │   ├── db.py            # Engine, session, DeclarativeBase, init_db
│   │   ├── models/          # Project, Prompt, SnapshotRun, Answer, Score
│   │   ├── providers/       # OpenAI / Anthropic / Gemini adapters
│   │   ├── judge/           # LLM-as-judge scorer + pinned rubric
│   │   ├── scheduler/       # APScheduler config + snapshot job (N runs, cron)
│   │   ├── aggregate.py     # Mention-rate aggregation across N runs
│   │   ├── exporter.py      # CSV export (one row per answer)
│   │   ├── cli.py           # `lumora` command-line interface
│   │   └── api/             # projects, prompts, snapshots, CSV export
│   ├── alembic/             # Migrations
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                # React + Recharts (placeholder)
├── docker-compose.yml       # app + Postgres (production)
├── .env.example
└── pyproject.toml
```

## Quick start (MVP / SQLite)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env   # then fill in your API keys

uvicorn app.main:app --reload
```

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

The database tables are created automatically on startup for the SQLite MVP. For
Postgres, use Alembic:

```bash
cd backend
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

## Command-line interface

Install the package to get the `lumora` command (operates Lumora without the web
dashboard):

```bash
pip install -e .          # from the repo root; installs the `lumora` script
```

```bash
lumora init                                            # create the database tables
lumora project create --name "Acme" --brand "Acme" \
    --aliases "AcmeCo,Acme Inc" --competitors "Globex,Initech"
lumora project list
lumora prompt add --project-id 1 --text "What is the best widget company?"
lumora prompt list --project-id 1
lumora run --project-id 1                               # on-demand snapshot (streams progress)
lumora run --all                                        # run every active project
lumora status --project-id 1                            # latest results + mention rates
lumora export --project-id 1 --format csv -o out.csv    # one row per answer
lumora schedule --project-id 1 --cron "0 9 * * 1"       # weekly, Mondays 09:00
```

A snapshot run fans out across every model in `SNAPSHOT_MODELS` that has an API
key configured, asking each prompt `RUNS_PER_PROMPT` times. `lumora status` then
reports per-(prompt, model) mention rates. Cron schedules set via `lumora
schedule` are stored on the project and registered automatically whenever the
app's in-process scheduler starts.

## Production (Docker Compose + Postgres)

```bash
# provider keys are read from your shell environment / .env
docker compose up --build
```

This brings up the FastAPI app against a Postgres database.

## Status

Phase 1 is complete (Tasks 1–6): project structure, data models, API skeleton,
**live provider adapters** (OpenAI, Anthropic, Gemini via the `google-genai`
SDK), the **LLM-as-judge scoring pipeline**, the **scheduled snapshot runner**,
and the **`lumora` CLI**.

The runner executes each prompt across **all** configured providers and repeats
it `N` times (default 3) per snapshot, tagging every answer with its provider,
model, and `run_index` so visibility reads as a mention rate. Runs walk a
`pending → running → completed/failed` lifecycle with timestamps, respect each
project's monthly token budget, and can be triggered on demand (`lumora run`, the
API, or `BackgroundTasks`) or on a per-project **cron schedule** via APScheduler.

Smoke-test the providers (skips any without a key configured)::

```bash
cd backend
python scripts/smoke_providers.py --judge
```

## License

Licensed under the [GNU Affero General Public License v3.0 or later](./LICENSE).
