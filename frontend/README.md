# Lumora Frontend (placeholder)

The dashboard will be a **React + Recharts** single-page app that visualizes
brand visibility over time from the Lumora API.

## Planned

- **Projects view** — manage brands, aliases, and competitors.
- **Prompts view** — author and toggle the monitored prompts.
- **Snapshots / trends** — Recharts time-series of:
  - share-of-voice (mention rate) per provider
  - average mention position
  - sentiment breakdown over time
- **Export** — download the per-answer CSV (`/projects/{id}/export.csv`).

## Intended stack

- React (Vite)
- Recharts for charts
- A thin fetch client against the FastAPI backend (default `http://localhost:8000`)

Scaffolding (`npm create vite@latest`) lands in a later task — this directory is
a placeholder for the MVP.
