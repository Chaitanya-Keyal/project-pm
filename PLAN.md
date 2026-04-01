# Project PM — Plan

## Overview

**Project PM** is the human-facing UX layer — a general-purpose AI project management agent that provides per-person dashboards, a Telegram chatbot, and conversational interfaces. It consumes data from **Project Lens** (`~/dev/tools/project-lens/`), the master knowledge base that handles all data ingestion, AI digestion, and indexing.

Project PM never posts publicly, never merges, and never modifies external project boards directly.

### How They Connect

```
project-lens                        project-pm (this repo)
  scripts/github_scan.py              FastAPI + Uvicorn (systemd)
  scripts/telegram_ingest.py          Jinja2 + HTMX templates
  cron: AI digestion                   Telegram DM chatbot
       │                                      │
       ▼                                      │ reads from
  SQLite database  ◄──────────────────────────┘
  (raw data, AI digests, assessments,    (direct DB access, same machine)
   contributor profiles, chains, decisions)

  project-pm also has its own SQLite DB
  for contributor management and UX state
  (contributors, task actions, conversations)
```

### Directory Layout

```
~/dev/tools/
  project-lens/              # the knowledge base engine
    backend/                 # models, config, database
    scripts/                 # data ingestion + AI digestion scripts

  project-pm/                # the PM agent / UX layer (this repo)
    backend/                 # FastAPI app, services, models
    templates/               # Jinja2 + HTMX
```

Project-specific config lives in separate small public repos:

```
project-pm-seedsigner-config/      # public repo
  config.yaml                       # project settings, suggestion heuristics, Telegram bot config
  .env                              # secrets (gitignored)
```

---

## Responsibilities

- Contributor discovery from Lens data + admin UI for enabling/disabling boards
- Per-person task boards (web UI)
- Telegram DM chatbot
- Per-person state: task actions (accepted, deferred, etc.), conversation history, preferences
- Triggers the indexer to do on-demand updates (the "Update" button)
- Suggestion generation (filters/sorts indexer data by contributor activity profile)
- Release note drafting, call prep, digest generation
- Announcements and reminders (upcoming dev calls, deadlines, etc.)
- Its own SQLite database for contributor management and user-facing state

---

## Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Web framework | FastAPI | Already proven in meal-tracker |
| Frontend | Jinja2 templates + HTMX | No build step, no node_modules. HTMX adds interactivity via server-rendered HTML fragments. Polling (`hx-trigger="every 60s"`) keeps boards live without reload — SSE upgrade path for real-time later. |
| UI style | Dark mode default, minimal CSS | Clean, attractive dark theme. Light mode as future option. No CSS framework — hand-rolled for simplicity. |
| Database (own state) | SQLite (async SQLAlchemy + aiosqlite) | Contributors, task actions, conversations, preferences |
| Database (project data) | Project Lens SQLite (read-only) | Direct file access, same machine |
| Chatbot | python-telegram-bot (async) | Team already uses Telegram |
| Chat AI | Anthropic Python SDK (async, Haiku default) | Only needed for real-time DM/web chat responses — all background analysis runs through Claude Code on subscription |
| Deployment | systemd user service (web) + crontab (digest generation) | Web app as service |
| Public access | Cloudflare Tunnel + custom domain | `cloudflared` exposes local port via custom domain (e.g., `pm.seedsigner.com`). DNS managed by Cloudflare, auto TLS, no open ports, free tier. |

---

## Database Schema (PM-specific tables)

The PM agent has its own SQLite database for contributor management and user-facing state. Project data (PRs, issues, assessments, etc.) comes from the Project Lens database via read-only access.

```
contributors    — only created when admin enables a contributor's board
                  fields: github_username (PK), display_name, role (nullable — optional
                  admin override: "lead_maintainer", "lead_dev", etc.; if null, inferred
                  from activity), auth_token (generated on creation),
                  telegram_user_id (nullable), telegram_chat_id (nullable),
                  created_at, updated_at
                  Contributors are NOT pre-cached. The admin UI queries Lens live to
                  discover all unique GitHub usernames + activity stats, then left-joins
                  against this table to show enabled/not-enabled status. A record is
                  created here only when a contributor is enabled. Disabling deletes
                  the record (or soft-deletes if we want to preserve task history).
                  Roles default to inferred from activity but can be overridden by admin.

task_actions     — records user decisions on dynamically generated board items
                  fields: github_username (FK→contributors), source_ref ("PR#722",
                  "issue#43", "chain:translations"),
                  action (done|deferred|watching),
                  waiting_on (nullable — GitHub username of person whose response would re-trigger),
                  deferred_until (nullable datetime — item hidden until this date, then reappears),
                  note (optional user annotation),
                  created_at, updated_at
                  Board items are generated dynamically from PR assessments + contributor
                  activity profile; this table only stores the user's responses to those
                  suggestions. "waiting" items are monitored by the cron scanner — when
                  the waited-on person responds (new commits, comments), the item moves
                  back to suggested.

manual_tasks    — tasks created by users (via chat or web), not derived from GitHub data
                  fields: github_username (FK→contributors), title, description, status,
                  priority, created_at, updated_at

conversations   — per-person chat history with the bot
                  fields: github_username (FK→contributors), channel (telegram|web),
                  messages (JSON)
```

---

## Architecture: Local Server as Central Hub

```
  ┌──────────────────────────────────────────────────┐
  │  cron jobs (system crontab)                       │
  │                                                    │
  │  Weekly:   claude -p "generate digest, update DB"  │
  │                                                    │
  │  (GitHub scanning and Telegram ingestion are       │
  │   handled by project-lens, not project-pm)         │
  └──────────────────────┬─────────────────────────────┘
                         │ writes to
                         ▼
  ┌──────────────────────────────────────────────┐
  │   Project Lens DB      │   Project PM DB     │
  │   (read-only access)   │   (own state)       │
  │   pr_assessments,      │   contributors,      │
  │   github_prs, etc.     │   task_actions,      │
  │                        │   conversations,     │
  │                        │   manual_tasks       │
  └──────────┬──────────────────┬────────────────┘
             │ reads from       │ reads from
  ┌──────────▼───────┐  ┌──────▼──────────────┐
  │ FastAPI + Uvicorn │  │ Telegram Bot        │
  │ (systemd service) │  │ (systemd service or │
  │                   │  │  in FastAPI process) │
  │ Web UI:           │  │                     │
  │ /board/{person}   │  │ DM chatbot          │
  │ HTMX task boards  │  │ (Claude API for     │
  │                   │  │  real-time chat)     │
  └───────────────────┘  └─────────────────────┘
```

---

## Per-Person Task Boards

Each person gets a URL: `http://host:8420/board/newtonick`

**Board sections (left/main column):**

**ACTION NEEDED** — items where the ball is back in your court:
- `PR #636 — alvroble responded to your feedback` (SLIP-39 · addressed error handling concern)
- `PR #838 — securesigner pushed requested changes` (MicroSD toast · navigation fix)

**WATCHING** — compact one-liners, items where someone else is the blocker:
- `PR #884 · berlinxray: consolidate with #885 · 12d`
- `PR #878 · KaustubhPatange: add simulator docs · 22d`
- `PR #722 · Nick: merge (approved) · 35d`

**SUGGESTIONS** — new items to consider, with inline Accept/Defer:
- `PR #891 — BIP47 derivation, needs initial direction` [Accept] [Defer]
- `PR #868 — SeedQR template generator` [Accept] [Defer]
- `Triage: 3 stale milestones to close` [Accept] [Defer]

**RECENT CONTRIBUTIONS (sidebar)** — celebratory record of activity:
- 🎉 PR #849 merged! Scrolling performance is buttery smooth!
- 🐛 PR #636 — caught a bug in share validation; author fixed it
- 🔧 PR #838 — tested toast timer on Pi Zero hardware
- 💡 Issue #875 — proposed SeedQR resiliency testing approach
- [View all contributions →]

**Layout**: Two-column. Left column is the work focus (Action Needed → Watching → Suggestions). Right sidebar is the contributions feed. Board cards in Action Needed and Watching are clickable — they open the task detail page. All status controls (Watching, Defer, Done, Open on GitHub) live on the detail page. Suggestions have inline Accept/Defer since those are quick decisions.

The board has four sections with a clear flow:

- **Action Needed**: items you've **previously engaged with** where the ping-pong has come back to you. The reason why it needs your attention is stated (e.g., "alvroble responded to your feedback"). You're the current blocker on these. Clicking an item opens the **detail page** where you can review the full context and take action.
- **Watching**: compact one-line rows for items where you've engaged but the ball is in someone else's court. Shows who you're waiting on and how long. The cron scanner monitors these — when the waited-on person responds, the item moves up to Action Needed automatically with context about what changed.
- **Recent Contributions**: a record of all valuable project activity — not just merged PRs, but also reviews given, issues opened, issue responses, testing feedback. Reflects the full picture of someone's engagement with the project.
- **Suggestions**: separate section at the bottom — new items the agent recommends you engage with. Actions: **Accept** (take it on — goes to Watching after you engage), **Defer** (options: 1 week, 2 weeks, 1 month, or "back in the pool" — no fixed date, just return it to the suggestion pool for the agent to re-surface when it makes sense). Nothing is permanently dismissed.

The lifecycle:
```
Suggestions → you accept & engage → Watching (ball elsewhere)
                                         ↓
                              someone responds
                                         ↓
                               Action Needed (ball is yours)
                                         ↓
                              you act → back to Watching or Done
```

The "Recent Contributions" section captures all valuable project activity, **characterized by impact** rather than raw activity counts. Instead of "reviewed PR and left 4 comments," the agent describes what was actually accomplished: "caught a bug in share validation — author fixed it" or "tested on hardware, confirmed fix works" or "suggested approach that improved code clarity."

This characterization is generated by the indexer during the PR assessment cron — it reads the review comments and extracts the substance. The tone should be **celebratory and encouraging** — emojis, exclamation points, congratulations especially when someone's PR gets merged (🎉). Bug catches get 🐛, testing gets 🔧, ideas get 💡. The result should feel rewarding to read, not like a mechanical activity log. No time framing, no performance metric. Recent items shown on the board; older items age off.

A **"View all contributions"** link leads to a full history page (`/contributions/{github_username}`) showing the user's complete contribution record since the PM agent started tracking. This serves as a persistent, cumulative record of everything they've done for the project — useful for the contributor themselves, for release notes, and as a morale boost.

### Task Detail View

Clicking into any task on the board opens a **detail page** (`/task/{source_ref}`) that presents all the indexer's accumulated knowledge about that item in a structured, readable format — not a raw data dump, but a curated briefing:

```
┌──────────────────────────────────────────────────────┐
│ PR #636 — SLIP-39 Shamir's Secret Sharing Import ←link│
│ by alvroble · opened Dec 19, 2024 · seedsigner       │
│ (title is hyperlinked directly to the PR on GitHub)   │
├──────────────────────────────────────────────────────┤
│                                                       │
│ ASSESSMENT                                            │
│ ┌─────────┬────────────┬──────────┬────────────────┐ │
│ │ Tier: 2 │ Risk: Med  │ Size: L  │ Tests: partial │ │
│ │ Nick    │ Crypto     │ ~45 min  │                │ │
│ │ review  │ logic      │ review   │                │ │
│ └─────────┴────────────┴──────────┴────────────────┘ │
│                                                       │
│ SUMMARY                                               │
│ Implements SLIP-39 Shamir's secret sharing for seed   │
│ import. Significant feature — touches crypto paths.   │
│ alvroble addressed kdmukai's initial feedback on X.   │
│ One open question remains about Y.                    │
│                                                       │
│ WHAT HAPPENED                                         │
│ kdmukai reviewed and flagged the share validation     │
│ error handling and a missing edge case test.           │
│ alvroble reworked the error handling. kdmukai          │
│ confirmed that fix looks good.                         │
│                                                       │
│ WHERE THINGS STAND                                    │
│ One open question: how to handle edge case Z in       │
│ share reconstruction. kdmukai suggested an approach   │
│ but alvroble hasn't responded yet (14 days).          │
│                                                       │
│ DEPENDENCIES                                          │
│ · None — standalone feature                           │
│ · Part of chain: none                                 │
│                                                       │
│ RELATED DECISIONS                                     │
│ · Feb call: "Interesting but not blocking 0.8.7.      │
│   Can go into 0.9.0."                                 │
│                                                       │
│ BLOCKERS                                              │
│ · Author hasn't responded to last review comment      │
│ · Missing test for edge case Z                        │
│                                                       │
│ SUGGESTED NEXT ACTION                                 │
│ Nudge alvroble: "Hey, any update on the share         │
│ validation edge case? Happy to discuss if you're      │
│ stuck."                                               │
│                                                       │
│ ┌───────────────────────────────────────────────────┐ │
│ │         [Update]      [Defer]           │ │
│ └───────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

**The detail page is the primary workspace** — where you review context and take action. The PR/issue title at the top is hyperlinked directly to GitHub.

**Update flow** — at the bottom of the detail page, a guided instruction:

> *After you've completed some work on this task on GitHub, click below to update.*
>
> **[Update]**
>
> *We'll fetch the latest activity from GitHub, review what changed, and update your board accordingly.*

Clicking triggers the system to:
1. Trigger the indexer to fetch latest GitHub state for this PR (comments, reviews, commits, status)
2. Analyze what's new since the last fetch
3. Report findings in a dialog:

   > "I see you left a review on PR #636 addressing the error handling concern and pushed a commit with the fix. Are your changes complete and you're now waiting for alvroble's response, or are you planning further work?"
   >
   > [Waiting for response]  [Still working on it]

4. Based on the user's answer:
   - **"Waiting for response"** → moves to Watching with context about what was done and who's next
   - **"Still working on it"** → stays in Action Needed
   - If the PR was merged/closed → auto-moves to Recent Contributions with celebration

The detail page also has a **Defer** option — bring it back later (1 week, 2 weeks, 1 month, or back in the pool).

The indexer's cron scanner auto-detects activity every 4 hours as well — the Update button is just an immediate, on-demand version of that scan for a single item.

The detail view pulls from the indexer's data:
- **PR assessment** (tier, complexity, risk, summary)
- **GitHub review/comment history** (synthesized into a narrative timeline, not raw API data)
- **Dependency chains** (if this PR is part of one)
- **Decision log** (what was said about this in calls or Telegram)
- **Blockers** (derived from review state, author responsiveness, CI status)
- **Suggested next action** (what the agent recommends you do)

The narrative digest is the key — not a timeline of events, but a brief summary of the main discussion points, the major changes made, and then quickly: **where things currently stand**. The reader should be able to glance at "What Happened" and "Where Things Stand" and know exactly what to do next without reading the full PR thread. This digest is generated by the indexer during the PR assessment cron and cached, so the detail page loads instantly.

### Dynamic Board Generation (not pre-materialized)

The board is assembled **on-access**, not pre-generated by cron:

1. **The indexer handles the expensive part**: syncing GitHub data and generating PR assessments (tier, complexity, risk, review status). This is cached in the indexer DB.
2. **On board load**: the app filters and sorts PR assessments based on the contributor's activity profile and role (if admin-assigned, otherwise inferred), then subtracts any tasks they've dismissed or deferred. No Claude API call needed — it's just SQL queries and activity-based filtering.
3. **User actions persist**: accepted, deferred (with `deferred_until` date), dismissed. These survive across board loads and cron refreshes.
4. **If a PR assessment updates** (e.g., someone left a new review), the board reflects it on the next page load.

**Task generation heuristics differ by role:**

- **Nick (lead_maintainer)**: Suggestions are PRs that have sufficient review and ACKs from trusted developers — things that are ready for his merge decision. Sorted by review time (shortest first) to maximize throughput. But **nothing auto-appears in Action Needed** — Nick explicitly accepts items from Suggestions when he has time. Same lifecycle: accept → review → Watching (if he has questions) or Done (if he merges). If he leaves feedback and the author responds, it moves to Action Needed.
- **kdmukai (lead_dev)**: Suggestions are PRs needing rework direction, contributor nudges, dependency chain coordination, triage. Things that move PRs toward Nick-ready state. Same explicit accept flow.
- **Contributors**: their own open PRs and what's needed to get them merged. Same flow.

**Everyone uses the same board mechanics.** The only difference is what the agent surfaces in Suggestions based on role and what's relevant to each person.

**Any contributor can have a board.** Since the data is indexed across all repos (PRs, issues, reviews, activity), the board is just a filtered view.

**Contributor discovery and board activation:**
- Contributors are **automatically discovered** from Project Lens data — anyone who appears as a PR author, committer, or reviewer across the tracked repos
- The **admin UI** (`/admin/contributors`) lists all discovered contributors ranked by activity (PR count, review count, commit count, last activity date)
- A maintainer **enables** a contributor's board with a single click — this generates an auth token and activates their board at `/board/{github_username}?token=xxx`
- Roles (lead_maintainer, lead_dev, contributor) can optionally be set by the admin; if not set, the suggestion algorithm infers expertise and activity level from the Lens data
- Telegram DM access is configured per-contributor in the admin UI (set their Telegram user ID to enable)

**Onboarding new contributors:**
- When new contributors (including students) begin interacting with the project, their activity is automatically picked up by the Lens scanner
- A maintainer enables their board, and the system immediately has context from whatever activity they've had
- The suggestion algorithm is complexity-aware: new contributors with limited history get tier 0/1 suggestions (trivial/straightforward), with complexity gradually increasing as they demonstrate capability through merged PRs and accepted reviews
- The "Recent Contributions" section serves as a visible record of their growth

### Intelligent Suggestion Generation

Suggestions are not just "your own PRs that need attention." The agent also encourages **cross-pollination** — suggesting PRs for contributors to review, not just their own work. The suggestion algorithm considers:

**For a contributor's own PRs:**
- PRs with review feedback they haven't addressed
- PRs with merge conflicts that need rebasing
- PRs that have gone stale and might need a ping

**For issues:**
- Stale issues that may be obsolete (feature was implemented, problem was fixed, direction changed)
- Issues with robust discussion that have stalled — may need a decision or summary
- Issues where a PR exists that addresses them but isn't linked
- Issues that could be closed with a brief explanation
- Issues worth responding to (new, unanswered, from a known contributor)

**For review suggestions (encouraging the review culture):**
- **Neglected PRs**: PRs with zero reviews or reviews from only non-maintainers. "PR #868 has been open for 2 months with no reviews — could use a first look."
- **Interest matching**: infer areas of interest from the contributor's past work. If alvroble has contributed l10n and PSBT-related PRs, suggest they review other l10n or PSBT PRs. If Chaitanya-Keyal has worked on screenshots and UI, suggest UI-related PRs.
- **Proximity**: suggest reviewing PRs that touch files the contributor has modified before — they have context that makes their review more valuable.
- **Complexity matching**: don't suggest a crypto-heavy PR to someone who's only done docs/cleanup work. Match the PR's complexity to the contributor's demonstrated expertise level.

**Signals for interest/expertise inference** (from indexer data):
- Files modified in past PRs (strongest signal)
- Labels on past PRs (if labeled)
- PR categories (l10n, testing, CI, GUI, hardware, crypto)
- Review history — what have they reviewed before?

This builds a review culture organically. Instead of asking "who can review this?", the system proactively routes PRs to people most likely to give a useful review. Over time, it learns from who actually engages with suggestions.

**Web auth**: token-in-URL for a trusted small group (`/board/newtonick?token=abc123`). Adequate for localhost or private network.

**Telegram DM auth**: allowlist-based. Only approved Telegram user IDs can interact with the bot via DM. The PM `contributors` table maps each allowed Telegram user to their GitHub account, so the bot knows who it's talking to and can personalize responses accordingly. Telegram user IDs are configured per-contributor in the admin UI. Unknown Telegram users get no response (or a brief "this bot is not open for public use" message).

---

## Announcements and Reminders

The dashboard displays timely announcements and reminders — recurring events, deadlines, and time-sensitive information that the board sections don't cover.

**Examples:**
- "Dev call in 3 days (Saturday April 5, 2pm ET)" → shows as a banner
- "Dev call starts in 1 hour — [Join link]" → prominent with join link
- "Merge freeze begins tomorrow for v0.8.7 release branch" → warning banner
- "v0.8.7 release target: April 15" → persistent reminder

**Implementation:**
- `announcements` table in the PM database: title, body, display_start, display_end, priority, link (optional), recurring (cron expression for repeating events like monthly dev calls)
- Displayed as a banner section at the top of the dashboard, above Action Needed
- Recurring events auto-generate the next instance when the current one expires
- Also surfaced via Telegram DM when someone asks "what's coming up?"
- Managed by maintainers via a simple admin interface or chat command ("schedule dev call for April 5 at 2pm ET, link: https://...")

**Recurring events config** (in project-pm config YAML):
```yaml
recurring_events:
  - name: Dev Call
    schedule: "0 14 1st-saturday * *"  # or explicit dates
    duration_hours: 1
    reminder_days_before: [3, 1]
    link: "https://meet.example.com/seedsigner-dev"
    note: "Monthly SeedSigner developer call"
```

---

## Telegram Chatbot

The same Telegram bot serves two roles:

1. **Group chat reader** (read-only): passively ingests messages from the dev group, extracts decisions and action items — **this is handled by the indexer**, not the PM agent
2. **DM chatbot** (per-person, pull-only): maintainers DM the bot when they want information. **The bot never initiates contact** — no push notifications, no unsolicited messages, no daily reminders. Users come to it when they're ready.

### DM Flow
```
Nick: "hey, what should I focus on?"
  → bot checks telegram_user_id against PM contributors table
  → if not found or not enabled: ignore or send brief "not authorized" message
  → if enabled: look up contributor, map to GitHub username
  → build context from indexer DB: PR assessments, decisions, chains
  → call Claude Sonnet with person-specific system prompt
  → return prioritized suggestions
  → Nick: "I'm not interested in any of those, got anything else?"
  → bot generates alternatives from lower-priority items
```

The Telegram→GitHub mapping in the PM `contributors` table ensures the bot knows that Telegram user "nick_telegram" is GitHub user "newtonick" and can personalize accordingly (show his PRs, his merge queue, etc.).

**Strictly pull-based**: The bot has the data ready at all times (refreshed by the indexer's cron), but only surfaces it when someone asks. This respects contributors' time and avoids the bot feeling like a nag. If we ever want opt-in push notifications in the future, that would be a separate, explicit per-user preference — not the default.

### Chat ↔ Board Integration

Chat interactions modify board state in real-time. The board and the bot are two interfaces to the same data:

- **"I'll look at PR #891"** → accepts from Suggestions, moves to Watching after you engage
- **"Done with PR #636"** → moves to Recent Contributions
- **"Defer the SeedXOR stuff for two weeks"** → disappears, reappears in Suggestions after 2 weeks
- **"I've gone through all the suggestions, got anything else?"** → bot generates new lower-priority suggestions
- **"Add a task for me to draft 0.8.7 release notes"** → creates a manual item in Action Needed
- **"What's waiting on me?"** → lists Action Needed items
- **"What am I watching?"** → lists Watching items with status

The bot parses intent from natural language and maps it to task actions (accept, done, dismiss, defer, create). Claude handles the NLU — no rigid command syntax needed.

---

## Bootstrap Plan

**Prerequisite**: Project Lens Phase 2 (AI assessments) must be complete before Phase 1 here can deliver meaningful task boards.

### Phase 1: Web Framework + Contributor Management + Task Boards
**Goal**: Per-person web dashboards dynamically assembled from indexer data, with admin-managed contributor activation.

- Project setup following meal-tracker pattern (FastAPI, async SQLAlchemy, aiosqlite)
- Own SQLite database for PM state (contributors, task_actions, manual_tasks, conversations)
- Read-only connection to Project Lens SQLite database
- **Contributor discovery**: admin UI queries Lens DB live to extract all unique GitHub usernames + activity stats (PR count, review count, commit count, last activity date). No caching — new contributors appear automatically after each Lens scan.
- **Admin UI** (`/admin/contributors`): list discovered contributors ranked by activity, enable/disable toggles, optional role assignment, Telegram user ID config. Enabling creates a PM record with generated auth token. No sync jobs needed.
- Per-person board pages: `/board/{github_username}?token=xxx` — dynamically assembled from PR assessments + activity-inferred heuristics
- Board subtracts items the user has dismissed or deferred (from `task_actions` table)
- Task actions: accept, dismiss, done, **defer** (HTMX `hx-post` endpoints)
- Defer: hides item until chosen date (1 week, 2 weeks, 1 month, custom). Reappears when defer expires.
- Task card templates showing priority, category, estimated time, context
- Task detail pages pulling from indexer data
- systemd service for FastAPI
- Token-in-URL auth for web boards

**Deliverable**: Admin-managed contributor boards with AI-suggested items, dynamically generated from indexer data.

### Phase 2: Telegram Integration
**Goal**: DM chatbot for maintainers.

- DM chatbot: person lookup → context from indexer DB → Claude API for real-time response
- Structured actions in chat (accept/dismiss tasks)
- Chat ↔ board state integration
- Runs as asyncio task in FastAPI process (or separate systemd service)

**Deliverable**: Working Telegram DM chatbot with board state integration.

### Phase 3: Digests, Release Notes, Polish
**Goal**: Automated briefings and the full interactive capability set.

- Weekly digest cron: generates per-person briefings, stored in DB. Users pull via web or Telegram — **no push notifications**.
- Release notes drafting from merged PRs + contributor census + review credit heuristic (data from indexer)
- Call prep generation
- Cost tracking dashboard
- Web chat pane as Telegram alternative (optional)
- Contribution history pages

**Deliverable**: Full PM feature set with automated briefings and release note generation.

---

## Key Files to Reference During Implementation

These existing files in meal-tracker provide the exact patterns to follow:

- `meal-tracker/backend/main.py` — FastAPI app structure, lifespan hook, router org
- `meal-tracker/backend/database.py` — async SQLAlchemy + aiosqlite setup
- `meal-tracker/backend/services/claude_service.py` — Anthropic SDK async wrapper with cost tracking
- `meal-tracker/backend/services/conversation_service.py` — Chat conversation flow
- `meal-tracker/backend/api/deps.py` — Dependency injection pattern (PM uses token-in-URL instead of headers)

---

## Claude Usage Strategy

| Component | Mechanism | Billing |
|---|---|---|
| Weekly digest generation | `claude -p` cron jobs | Subscription quota |
| **Telegram DM chatbot (real-time)** | **Anthropic API (Haiku)** | **API billing (~$5-10/mo)** |
| **Web chat (real-time)** | **Anthropic API (Haiku/Sonnet)** | **API billing (~$5-10/mo)** |

Only real-time chat uses direct API calls. Digest generation runs through Claude Code on the subscription. API cost is minimal since interactive chat is infrequent and can default to Haiku for most queries.

---

## Verification

### After Phase 1
- Admin UI shows discovered contributors from Lens data, ranked by activity
- Enabling a contributor generates an auth token and activates their board
- Per-person task boards show relevant suggestions from indexer data
- Task accept/dismiss/done/defer actions work via HTMX
- Ask "what PRs are ready for Nick?" and verify against board
- Deferred items reappear after their defer period

### After Phase 2
- Telegram DM: Nick asks "what should I review?" and gets a prioritized list
- Chat actions (accept, defer, done) sync with board state
- Bot only responds to allowlisted users

### After Phase 3
- Weekly digest covers all repos, matches manual assessment
- Release notes draft for 0.8.7 matches hand-crafted version in quality
- Contribution history pages show complete per-person record
