#!/usr/bin/env bash
# Bare-metal / VPS installer for Lumora.
#
# Creates a virtualenv, installs Lumora and its dependencies (including the
# `lumora` CLI), seeds a .env file, and runs database migrations. Run it from a
# checkout of the repo:
#
#     ./deploy/install.sh
#
# Then start the server (foreground) with:
#
#     ( cd backend && ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 )
#
# ...or install the systemd unit for a managed daemon (see deploy/lumora.service
# and the README "Bare metal / VPS" section).
set -euo pipefail

PYTHON="${PYTHON:-python3}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Lumora install (repo: $REPO_ROOT)"

# 1. Virtualenv ------------------------------------------------------------
if [ ! -d .venv ]; then
    echo "==> Creating virtualenv at .venv"
    "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate

# 2. Dependencies + the lumora console script ------------------------------
echo "==> Installing dependencies"
pip install --upgrade pip setuptools wheel
pip install -r backend/requirements.txt
pip install -e .   # installs the `lumora` CLI and the `app` package

# 3. Environment -----------------------------------------------------------
if [ ! -f .env ]; then
    echo "==> Creating .env from .env.example"
    cp .env.example .env
    echo "    !! Edit .env: set DATABASE_URL to your Postgres DSN and add API keys."
else
    echo "==> .env already exists; leaving it untouched"
fi

# 4. Database migrations ---------------------------------------------------
# Honors DATABASE_URL from the environment if exported, else falls back to the
# value in .env (read by Alembic via app.config). Idempotent.
echo "==> Running database migrations (alembic upgrade head)"
( cd backend && alembic upgrade head )

cat <<'DONE'

==> Install complete.

Start the server (foreground):
    ( cd backend && ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 )

Or run as a managed daemon:
    sudo cp deploy/lumora.service /etc/systemd/system/lumora.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now lumora

Use the CLI:
    .venv/bin/lumora project list
    .venv/bin/lumora run --all

The in-process APScheduler starts with the web server, so any cron schedules set
via `lumora schedule ...` fire while the service is running.
DONE
