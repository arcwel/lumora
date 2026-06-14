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
| Dashboard  | Server-rendered Jinja2 + HTMX + Alpine.js + Chart.js (custom "Dark Aurora" CSS, no build step) |
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
│   │   ├── alerting/        # Threshold checker + Slack/email/Telegram senders
│   │   ├── aggregate.py     # Mention-rate aggregation across N runs
│   │   ├── exporter.py      # CSV export (one row per answer)
│   │   ├── cli.py           # `lumora` command-line interface
│   │   ├── api/             # JSON API: CRUD + /api dashboard endpoints
│   │   ├── web.py           # Server-rendered dashboard (HTML pages + HTMX fragments)
│   │   ├── templates/       # Jinja2 templates (base, home, project, settings)
│   │   └── static/          # app.css ("Dark Aurora") + app.js (Chart.js wiring)
│   ├── alembic/             # Migrations
│   ├── requirements.txt
│   ├── docker-entrypoint.sh # Runs `alembic upgrade head`, then the CMD
│   └── Dockerfile
├── deploy/                  # Bare-metal / VPS: systemd unit + install script
│   ├── install.sh
│   └── lumora.service
├── frontend/                # Reserved for a future SPA (dashboard is server-rendered today)
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

## Web dashboard

Running the app serves a self-hosted dashboard at the site root — no separate
build step or Node toolchain. It's server-rendered with **Jinja2**, sprinkled
with **HTMX** for partial updates (add a prompt, trigger a run, refresh the
snapshot list without a full reload), **Alpine.js** for small interactions, and
**Chart.js** for the visualizations. Styling is a hand-rolled "Dark Aurora"
CSS theme with a built-in light/dark and color-accent switcher.

| Page | Route | What it shows |
| --- | --- | --- |
| **Dashboard** | `GET /` | All projects with current mention rate and run-over-run change |
| **New project** | `GET /projects/new` | Form to create a project (brand, aliases, competitors) |
| **Project detail** | `GET /projects/{id}/view` | Mention-rate trend chart, per-provider comparison, prompt breakdown, snapshot history |
| **Settings** | `GET /projects/{id}/settings` | Manage prompts (add / toggle active), cron schedule, project config |

The pages read from the same JSON API documented below; HTMX fragment routes
(`*/partial`, `/run`, `/prompts/add`, …) return just the changed markup.

## API reference

All routes are served by the FastAPI app; interactive docs live at `/docs`
(Swagger) and `/redoc`. The **`/api/*`** routes power the dashboard (read-only,
aggregated views); the unprefixed routes are the CRUD + action surface.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe (`{status, app, version, environment}`) |
| `POST` | `/projects` | Create a project |
| `GET` | `/projects` | List projects |
| `GET` | `/projects/{id}` | Get one project |
| `POST` | `/projects/{id}/prompts` | Add a prompt to a project |
| `GET` | `/projects/{id}/prompts` | List a project's prompts |
| `GET` | `/projects/{id}/snapshots` | List snapshot runs for a project |
| `POST` | `/projects/{id}/snapshots/run` | Trigger an on-demand snapshot run |
| `GET` | `/projects/{id}/export.csv` | Download results as CSV (one row per answer) |
| `GET` | `/api/projects` | Dashboard: projects with mention rate + change |
| `GET` | `/api/projects/{id}` | Dashboard: project summary + latest-run stats |
| `GET` | `/api/projects/{id}/trends` | Mention-rate time series per provider |
| `GET` | `/api/projects/{id}/comparison` | Per-provider mention rates for the latest run |
| `GET` | `/api/projects/{id}/prompts` | Per-prompt breakdown for the latest run |
| `GET` | `/api/projects/{id}/snapshots` | Snapshot run history (aggregated) |

## Alerting

After every snapshot run completes, Lumora compares the project's new overall
mention rate against the **previous completed run**. When the rate moves by at
least `ALERT_THRESHOLD` (a fraction — `0.10` = 10 percentage points) it fires an
alert. Both directions are reported: 📈 for a rise (good news) and 📉 for a drop.
The first run of a project has no baseline, so it never alerts.

Each message includes the project/brand, the old → new rate with the
percentage-point delta, the prompts that moved the most, a timestamp, and — when
`BASE_URL` is set — a deep link to the project's dashboard.

Three channels are supported, and **all are optional**: a channel is used only
when its environment variables are set, and skipped silently otherwise. A
failure in one channel is logged and never breaks the snapshot run or the other
channels.

| Channel | Required env vars |
| --- | --- |
| **Slack** | `SLACK_WEBHOOK_URL` (an [incoming webhook](https://api.slack.com/messaging/webhooks)) |
| **Email** | `SMTP_HOST`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` (plus optional `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`) |
| **Telegram** | `TELEGRAM_BOT_TOKEN` (from [@BotFather](https://t.me/BotFather)) and `TELEGRAM_CHAT_ID` |

```bash
# .env — tune the trigger and enable whichever channels you want
ALERT_THRESHOLD=0.10
BASE_URL=https://lumora.example.com

SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T000/B000/XXXX

SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=alerts@example.com
SMTP_PASSWORD=app-password
ALERT_EMAIL_FROM=alerts@example.com
ALERT_EMAIL_TO=team@example.com

TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-1001234567890
```

See [`.env.example`](.env.example) for the full annotated list. Slack and
Telegram use `httpx`; email uses the stdlib `smtplib`.

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
with the SQLite fallback retained, Tasks 8 & 12), Lumora ships **two deployment
paths** — Docker Compose and bare metal / VPS via systemd — both auto-migrating
on startup and exposing the CLI alongside the web server, and a **server-rendered
dashboard** (JSON API + Jinja2/HTMX/Alpine/Chart.js UI) charts visibility over
time (Tasks 9 & 10). The MVP is **feature-complete** and verified end-to-end
(CLI, API, dashboard, live snapshot pipeline, full test suite — Task 13).

The runner executes each prompt across **all** configured providers and repeats
it `N` times (default 3) per snapshot, tagging every answer with its provider,
model, and `run_index` so visibility reads as a mention rate. Runs walk a
`pending → running → completed/failed` lifecycle with timestamps, respect each
project's monthly token budget, and can be triggered on demand (`lumora run`, the
API, or `BackgroundTasks`) or on a per-project **cron schedule** via APScheduler.
Each completed run also feeds the **threshold alerting** pipeline (Task 11),
notifying Slack, email, and/or Telegram when a project's mention rate shifts past
`ALERT_THRESHOLD` — see [Alerting](#alerting).

Smoke-test the providers (skips any without a key configured)::

```bash
cd backend
python scripts/smoke_providers.py --judge
```

## Contributing

Contributions are welcome. The project is plain Python with a small dependency
surface and no frontend build step, so getting set up is quick:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # installs the `lumora` CLI in editable mode

pytest                      # run the test suite
ruff check .                # lint
```

- **Tests** live in `backend/tests/`. Most run against an in-memory/SQLite
  database and don't touch live provider APIs; please add coverage with new
  features. Note the suite skips dashboard tests automatically if Jinja2 isn't
  installed.
- **Style** is enforced with [ruff](https://docs.astral.sh/ruff/) — run
  `ruff check .` (and `ruff format .`) before opening a PR.
- **Database changes** must ship an Alembic migration (`alembic revision
  --autogenerate -m "…"`); both Postgres and SQLite must stay green.
- Open an issue to discuss larger changes first. By contributing you agree your
  work is licensed under the project's **AGPL-3.0-or-later** license.

## License

Licensed under the [GNU Affero General Public License v3.0 or later](./LICENSE).
