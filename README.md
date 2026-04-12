# Project PM

AI project management agent -- per-person dashboards, task boards, and search across GitHub PRs, issues, and Telegram discussions. Consumes data from [Project Lens](https://github.com/kdmukai/project-lens), the master knowledge base that handles all data ingestion, AI assessment, and semantic indexing.

Project PM is the human-facing UX layer. It never posts publicly, never merges, and never modifies external project boards directly.

## How It Works

```
Project Lens                         Project PM (this repo)
  GitHub scan + AI assessment          FastAPI + Jinja2 + HTMX
  Telegram ingestion + digestion       Per-person task boards
  Semantic embeddings (ChromaDB)       Search across all data sources
       |                                      |
       v                                      | reads via LensClient API
  SQLite + ChromaDB  <------------------------+
  (PRs, issues, assessments,
   Telegram threads, profiles)       PM also has its own SQLite DB
                                     for contributor management
                                     and UX state
```

## Features

**Authentication** -- GitHub OAuth login required for all access:
- Users are gated by Lens contributor activity data -- only recognized project participants can sign in
- Admin access is config-based (`ADMIN_GITHUB_USERNAMES`)
- Post-login Telegram profile linking with validation against known chat participants
- Session management via signed cookies (Starlette SessionMiddleware)

**Activity Feed** -- Home page showing all open PRs sorted by recency:
- Author avatar and username, PR state badges (open/merged/closed)
- Tier, complexity, and risk indicators
- Pending action indicators showing who has outstanding items, with "You" highlighting for the current user
- Default repo suppressed (only shows repo name for non-primary repos)

**Search** -- Hybrid semantic + keyword search across three data sources:
- PR assessments with tier, complexity, risk, state, and merge readiness
- GitHub issue assessments with category, discussion state, and impact
- Telegram discussion digests with participant perspectives

Search results link to detail pages within PM showing the full AI assessment, participant contributions, related context, and a link out to the original source on GitHub or Telegram.

**Contributor Boards** -- Per-person dashboards assembled on-access from Lens data:
- Action Needed, Watching, and Suggestions sections
- Personalized based on contributor role and activity
- PR detail pages with viewer-specific action items
- Session-based access control (own board or admin)

**Admin UI** -- Contributor discovery and board management:
- Discovers contributors automatically from Lens activity data
- Enable/disable boards with one click
- Optional role assignment (lead_maintainer, lead_dev, etc.)
- Admin-only access enforced via `require_admin` dependency

## Setup

**Prerequisites:**
- Python 3.11+
- A configured [Project Lens](https://github.com/kdmukai/project-lens) instance with ingested data
- A GitHub OAuth App (for authentication)

**Install:**
```bash
cd ~/dev/tools/project-pm
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ../project-lens   # local editable install of Lens
```

**Configure:**
```bash
cp .env.example .env
# Edit .env:
#   LENS_CONFIG_DIR     — path to your Lens config directory
#   GITHUB_CLIENT_ID    — from GitHub OAuth App
#   GITHUB_CLIENT_SECRET
#   SESSION_SECRET_KEY  — random string for signing session cookies
#   BASE_URL            — public URL (e.g. https://pm.example.com)
#   ADMIN_GITHUB_USERNAMES — comma-separated admin GitHub usernames
```

**GitHub OAuth App:**
1. Go to https://github.com/settings/developers → New OAuth App
2. Homepage URL: your `BASE_URL`
3. Authorization callback URL: `{BASE_URL}/auth/callback`
4. Copy Client ID and Client Secret to `.env`

**Run:**
```bash
uvicorn project_pm.main:app --host 0.0.0.0 --port 8420 --reload
```

## External Access (Cloudflare Tunnel)

PM can be exposed to the internet via a Cloudflare tunnel. The tunnel runs on the same machine and proxies HTTPS → localhost:8420. See the [Cloudflare tunnel docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) for setup.

Key configuration:
- `BASE_URL` in `.env` must be the public `https://` URL
- Session cookie `Secure` flag is enabled in production (`https_only=not settings.debug`)
- `same_site="lax"` is required for the OAuth callback redirect from GitHub

## Project Layout

```
project_pm/
  main.py              FastAPI app, lifespan, session middleware, Jinja2 filters
  config.py            Settings (pydantic-settings, loads .env)
  database.py          PM async SQLAlchemy engine setup
  auth.py              Auth dependencies (require_login, require_admin, require_board_access)
  models/              SQLAlchemy ORM models (PM DB)
  services/
    board_service.py   Board assembly, PR detail builder
    contributor_service.py   Discovery, enable/disable
  api/
    auth.py            GitHub OAuth login/logout, callback, denied page
    profile.py         Telegram profile linking
    admin.py           Contributor management routes (admin-only)
    board.py           Board and PR detail routes (session auth)
    activity.py        Activity feed (home page)
    search.py          Search, issue/PR/Telegram detail routes
templates/             Jinja2 + HTMX templates
static/css/            Dark theme stylesheet
```

## Architecture

- **FastAPI + Jinja2 + HTMX** -- server-rendered HTML, no build step, no JS framework
- **GitHub OAuth** -- all routes require authentication; Lens activity data serves as the user allowlist
- **PM SQLite database** (read-write) -- contributors table with Telegram linking state
- **Project Lens** (via `project_lens.LensClient`) -- all project data access: search, PRs, issues, identity resolution, Telegram participants
- **Dark mode UI** -- generous font sizes, mobile-friendly responsive layout
- **HTMX** -- live search with keystroke debounce, lazy-loaded related context, inline admin actions

### Key Design Decisions

- Contributors are **discovered from Lens data**, not predefined. The admin UI queries Lens for all unique GitHub usernames + activity stats.
- PM's `contributors` table only stores **enabled** contributors. A record is created when an admin enables a board.
- Board pages are **assembled on-access** from Lens data, not pre-generated.
- All Lens data access goes through `LensClient` -- PM never queries Lens's database directly.
- Authentication gates on Lens activity -- if you have project contributions recorded in Lens, you can sign in.
- Admin designation is config-based (`ADMIN_GITHUB_USERNAMES`), not stored in the database.

---

## Roadmap

The following features are planned but not yet implemented.

### Per-Person Task Boards (full lifecycle)

The current board shows Suggestions based on PR assessments. The full vision includes:

**Action Needed** -- items where the ball is back in your court. The reason for attention is stated (e.g., "alvroble responded to your feedback"). You're the current blocker.

**Watching** -- compact one-line rows for items where you've engaged but the ball is in someone else's court. Shows who you're waiting on and how long. A background scanner monitors these -- when the waited-on person responds, the item moves up to Action Needed with context about what changed.

**Suggestions** -- new items the agent recommends you engage with. Accept (moves to Watching after you engage) or Defer (1 week, 2 weeks, 1 month, or back in the pool).

**Recent Contributions** -- a celebratory record of activity, characterized by impact rather than raw counts. "Caught a bug in share validation -- author fixed it" rather than "left 4 review comments."

The lifecycle:
```
Suggestions --> accept & engage --> Watching (ball elsewhere)
                                        |
                                   someone responds
                                        |
                                   Action Needed (ball is yours)
                                        |
                                   you act --> Watching or Done
```

Task generation heuristics differ by role:
- **lead_maintainer**: PRs ready for merge decision, sorted by review time
- **lead_dev**: PRs needing rework direction, contributor nudges, dependency coordination
- **Contributors**: their own open PRs and what's needed to get them merged

### Issue Suggestions

The agent surfaces issues for contributor attention:
- Stale issues that may be obsolete
- Issues with robust discussion that have stalled
- Issues where a PR exists that addresses them but isn't linked
- Issues worth responding to (new, unanswered, from a known contributor)

### Review Culture

Suggestions encourage cross-pollination -- recommending PRs for contributors to review based on:
- **Interest matching**: infer areas from past work (l10n, crypto, UI, etc.)
- **Proximity**: PRs touching files the contributor has modified before
- **Complexity matching**: match PR difficulty to demonstrated expertise
- **Neglected PRs**: PRs with zero reviews that need a first look

### Telegram DM Chatbot

A pull-based chatbot for maintainers. The bot never initiates contact -- users come to it when they want information.

```
Nick: "what should I focus on?"
Bot: [builds context from Lens data, returns prioritized suggestions]
Nick: "I'll look at PR #891"
Bot: [accepts from Suggestions, updates board state]
```

Chat interactions modify board state in real-time. The board and the bot are two interfaces to the same data.

### Announcements and Reminders

Dashboard banners for recurring events, deadlines, and time-sensitive information:
- "Dev call in 3 days (Saturday April 5, 2pm ET)"
- "Merge freeze begins tomorrow for v0.8.7 release branch"
- Recurring events auto-generate the next instance when the current one expires

### Digests and Release Notes

- Weekly per-person briefings (pull-based, no push notifications)
- Release notes drafted from merged PRs + contributor census + review credit
- Call prep generation
- Contribution history pages showing complete per-person record
