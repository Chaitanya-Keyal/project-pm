# Project PM

AI project management agent — per-person dashboards, task boards, and Telegram chatbot. Consumes data from Project Lens (`~/dev/tools/project-lens/`), the master knowledge base.

## Architecture

- **FastAPI + Jinja2 + HTMX** — server-rendered HTML with live updates
- **GitHub OAuth** — contributors log in via GitHub; any user with Lens activity is authorized
- **PM SQLite database** (read-write): contributors (role overrides, Telegram linking)
- **Project Lens** (via `project_lens` package): search, PR data, identity resolution
- **Dark mode UI** with generous font sizes, mobile-friendly responsive layout

## Running

Runs as a systemd user service:

```bash
# Status / logs
systemctl --user status project-pm
journalctl --user -u project-pm -f

# Restart after code changes
systemctl --user restart project-pm

# Enable/disable
systemctl --user enable --now project-pm
systemctl --user disable --now project-pm
```

Service file: `~/.config/systemd/user/project-pm.service`

For local development with auto-reload:
```bash
cd ~/dev/tools/project-pm
source .venv/bin/activate
uvicorn project_pm.main:app --host 0.0.0.0 --port 8420 --reload
```

## Key Decisions

- Contributors are **discovered from Lens data**, not predefined. The admin UI queries Lens via `LensClient` for all unique GitHub usernames + activity stats.
- **No enable/disable gating** — any contributor with Lens activity can log in via GitHub OAuth and see their board. A `Contributor` DB record is auto-created on first login for optional metadata (role override, Telegram linking).
- The **default landing page** for logged-in users is their personal board (`/board/{username}`). The activity feed is at `/activity`.
- Board pages are **assembled on-access** from Lens data, not pre-generated. No local DB record is required to view a board.
- HTMX polling keeps boards live without page reload.
- All Lens data access goes through the `project_lens.LensClient` API — PM never queries Lens's database directly.

## Project Layout

```
project_pm/
  main.py          — FastAPI app, lifespan, router registration
  config.py        — Settings (pydantic-settings, loads .env)
  database.py      — PM async SQLAlchemy engine setup
  auth.py          — Auth dependencies (login, admin, board access)
  models/          — SQLAlchemy ORM models (PM DB)
  services/        — Business logic (contributor discovery, board generation)
  api/             — Route modules (auth, activity, admin, board, profile, search)
templates/         — Jinja2 + HTMX templates
static/css/        — Dark theme stylesheet
```
