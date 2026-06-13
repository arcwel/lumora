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

| Layer      | Choice                                              |
| ---------- | --------------------------------------------------- |
| Backend    | Python + FastAPI                                    |
| ORM / DB   | SQLAlchemy 2.0 · Postgres (primary) / SQLite (fallback) |
| Driver     | psycopg 3 (`postgresql+psycopg://…`)                |
| Scheduling | APScheduler (cron-style runs)                       |
| Migrations | Alembic (auto-applied on startup)                   |
| Frontend   | React + Recharts (placeholder for now)              |
| Deploy     | Docker Compose **or** bare metal / VPS (systemd)    |

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
│   ├── docker-entrypoint.sh # Runs `alembic upgrade head`, then the CMD
│   └── Dockerfile
├── deploy/                  # Bare-metal / VPS: systemd unit + install script
│   ├── install.sh
│   └── lumora.service
├── frontend/                # React + Recharts (placeholder)
├── docker-compose.yml       # app + Postgres 16 (production)
├── .env.example
└── pyproject.toml
```

## Quick start (local dev / SQLite)

The fastest way to kick the tyres — no database server required. SQLite is the
zero-infra fallback; set `DATABASE_URL` to a `sqlite://` path (or leave it unset
entirely) and the app creates the schema for you on startup.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp ../.env.example ../.env                 # then fill in your API keys
# .env.example defaults to Postgres — for the SQLite quick start, set:
#   DATABASE_URL=sqlite:///./lumora.db

uvicorn app.main:app --reload
```

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

On a SQLite database the tables are created automatically on startup. On
Postgres the schema is owned by **Alembic** — run `alembic upgrade head` (the
Docker and systemd deployment paths below do this for you on every boot):

```bash
cd backend
alembic upgrade head        # migrations already live in alembic/versions/
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

## Deployment

Lumora ships two production paths. **Both** auto-run Alembic migrations on
startup, run the in-process APScheduler (so cron jobs fire while the service is
up), and expose the same `lumora` CLI alongside the web server.

### Option A — Docker Compose (app + Postgres 16)

One command brings up the FastAPI app and a Postgres 16 database with health
checks on both containers:

```bash
cp .env.example .env       # add your provider API keys (DATABASE_URL is
                           # overridden to the bundled Postgres by compose)
docker compose up --build
```

- The app container's entrypoint (`backend/docker-entrypoint.sh`) waits for
  Postgres, runs `alembic upgrade head`, then starts uvicorn — so the schema is
  created/migrated automatically.
- Health checks: Postgres uses `pg_isready`; the app polls `/health`. The app
  only starts once the database reports healthy (`depends_on: service_healthy`).
- `.env` is optional at boot (compose marks it `required: false`), so a bare
  `docker compose up` works out of the box — though providers without a key are
  skipped at run time.

Run **CLI** commands against the same stack:

```bash
docker compose run --rm app lumora project create --name "Acme" --brand "Acme"
docker compose run --rm app lumora run --all
docker compose run --rm app lumora status --project-id 1
```

### Option B — Bare metal / VPS (systemd)

Install into a virtualenv, point at your Postgres server, and run under systemd.

```bash
# 1. Clone to /opt/lumora (or anywhere; adjust paths in the unit file to match)
git clone https://github.com/arcwel/lumora.git /opt/lumora
cd /opt/lumora

# 2. Create the venv, install deps + the `lumora` CLI, seed .env, migrate.
#    Edit .env afterwards: set DATABASE_URL to your Postgres DSN and API keys.
./deploy/install.sh

# 3. Install and start the daemon
sudo cp deploy/lumora.service /etc/systemd/system/lumora.service
sudo systemctl daemon-reload
sudo systemctl enable --now lumora
journalctl -u lumora -f       # follow logs
```

What the unit does (`deploy/lumora.service`):

- `ExecStartPre` runs `alembic upgrade head` — **auto-migrate on every start**.
- `ExecStart` runs gunicorn with a **single** UvicornWorker. APScheduler runs
  in-process, so a single worker avoids duplicate cron registrations; scale
  request throughput with a reverse proxy / more hosts rather than more workers.
- `EnvironmentFile=/opt/lumora/.env` supplies `DATABASE_URL` and provider keys.

Manual run without systemd (also valid):

```bash
cd /opt/lumora/backend
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The `lumora` CLI is on PATH inside the venv (`/opt/lumora/.venv/bin/lumora`) and
shares the same database, so you can script snapshots and exports from cron, SSH,
or CI independently of the web process.

### Database configuration

`DATABASE_URL` selects the backend (psycopg 3 driver for Postgres):

| Backend  | `DATABASE_URL`                                            | Schema management        |
| -------- | -------------------------------------------------------- | ------------------------ |
| Postgres | `postgresql+psycopg://user:pass@host:5432/lumora`        | Alembic (`upgrade head`) |
| SQLite   | `sqlite:///./lumora.db` (or unset → automatic fallback)  | `create_all` on startup  |

The models are backend-agnostic (`JSON` columns, string-backed enums, timezone-
aware timestamps), so the same migrations apply cleanly to both.

## Status

Phase 1 (Tasks 1–6) delivered the project structure, data models, API skeleton,
**live provider adapters** (OpenAI, Anthropic, Gemini via the `google-genai`
SDK), the **LLM-as-judge scoring pipeline**, the **scheduled snapshot runner**,
and the **`lumora` CLI**.

Since then: **Postgres is the primary database** (psycopg 3, Alembic-managed,
with the SQLite fallback retained), and Lumora ships **two deployment paths** —
Docker Compose and bare metal / VPS via systemd — both auto-migrating on startup
and exposing the CLI alongside the web server (Tasks 8 & 12).

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
