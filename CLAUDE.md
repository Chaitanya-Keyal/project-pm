# Project PM

AI project management agent — per-person dashboards, task boards, and Telegram chatbot. Consumes data from Project Lens (`~/dev/tools/project-lens/`), the master knowledge base.

## Architecture

- **FastAPI + Jinja2 + HTMX** — server-rendered HTML with live updates
- **PM SQLite database** (read-write): contributors, task_actions, manual_tasks, conversations
- **Project Lens** (via `project_lens` package): search, PR data, identity resolution
- **Dark mode UI** with generous font sizes, mobile-friendly responsive layout

## Running

```bash
cd ~/dev/tools/project-pm
source .venv/bin/activate
uvicorn project_pm.main:app --host 0.0.0.0 --port 8420 --reload
```

## Key Decisions

- Contributors are **discovered from Lens data**, not predefined. The admin UI queries Lens via `LensClient` for all unique GitHub usernames + activity stats.
- PM's `contributors` table only stores **enabled** contributors. A record is created when an admin enables a board.
- Board pages are **assembled on-access** from Lens data, not pre-generated.
- HTMX polling keeps boards live without page reload.
- All Lens data access goes through the `project_lens.LensClient` API — PM never queries Lens's database directly.

## Project Layout

```
project_pm/
  main.py          — FastAPI app, lifespan, router registration
  config.py        — Settings (pydantic-settings, loads .env)
  database.py      — PM async SQLAlchemy engine setup
  models/          — SQLAlchemy ORM models (PM DB)
  services/        — Business logic (contributor discovery, board generation)
  api/             — Route modules (admin, board, search)
templates/         — Jinja2 + HTMX templates
static/css/        — Dark theme stylesheet
```
