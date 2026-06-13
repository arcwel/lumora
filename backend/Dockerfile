# Lumora backend image.
#
# IMPORTANT: build with the repository root as the context so pyproject.toml is
# visible and the package (plus the `lumora` console script) can be installed:
#
#     docker build -f backend/Dockerfile -t lumora .
#
# docker-compose.yml already sets `context: .` / `dockerfile: backend/Dockerfile`.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r backend/requirements.txt

# Install the project itself so both `uvicorn app.main:app` and the `lumora`
# console script are on PATH. --no-deps because requirements.txt above already
# pinned everything.
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-deps -e .

# Run from the backend dir so Alembic resolves alembic.ini / alembic/.
WORKDIR /app/backend

EXPOSE 8000

# Entrypoint runs `alembic upgrade head`, then execs the command below.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
