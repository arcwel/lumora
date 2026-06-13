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
3. A scheduled **snapshot run** sends each prompt to each configured AI provider
   and stores the raw **answers**.
4. An **LLM-as-judge** pipeline scores each answer: was the brand mentioned, at
   what position, with what sentiment, and which sources were cited.
5. Results are charted over time and exportable to **CSV**.

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
│   │   ├── scheduler/       # APScheduler config + snapshot job
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

## Production (Docker Compose + Postgres)

```bash
# provider keys are read from your shell environment / .env
docker compose up --build
```

This brings up the FastAPI app against a Postgres database.

## Status

Tasks 1–4 are complete: project structure, data models, API skeleton, and the
**live provider adapters** (OpenAI, Anthropic, Gemini via the `google-genai`
SDK) plus the **LLM-as-judge scoring pipeline**. The scheduler now runs the full
loop — query each active prompt, persist answers, judge them, and persist scores
— while respecting each project's monthly token budget.

Smoke-test the providers (skips any without a key configured)::

```bash
cd backend
python scripts/smoke_providers.py --judge
```

## License

Licensed under the [GNU Affero General Public License v3.0 or later](./LICENSE).
