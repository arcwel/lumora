#!/usr/bin/env sh
# Container entrypoint for Lumora.
#
# Brings the database schema up to date with Alembic, then hands off to the
# container command (uvicorn by default, or any `lumora ...` CLI invocation).
# Migrations are idempotent — re-running `alembic upgrade head` is a no-op when
# the schema is already current — so this is safe on every container start.
set -e

# The compose stack gates the app on a healthy Postgres (`depends_on:
# condition: service_healthy`), but retry anyway so a slow/cold database, or a
# `docker run` without compose, doesn't crash-loop the container.
attempts=0
max_attempts="${MIGRATION_MAX_ATTEMPTS:-15}"
until alembic upgrade head; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge "$max_attempts" ]; then
        echo "lumora: migrations failed after ${attempts} attempts; giving up." >&2
        exit 1
    fi
    echo "lumora: database not ready, retrying migrations in 2s (${attempts}/${max_attempts})..."
    sleep 2
done

echo "lumora: migrations applied; starting: $*"
exec "$@"
