from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from project_lens import LensClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from project_pm.config import settings
from project_pm.database import pm_engine
from project_pm.models.base import Base
from project_pm.models.contributor import Contributor  # noqa: F401 — register PM models

PROJECT_ROOT = Path(__file__).parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_lens_config()

    # Create PM tables on startup
    async with pm_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


    # Initialize Lens client (search, identity, PR data)
    app.state.lens = LensClient(config_dir=settings.lens_config_dir)

    yield

    await app.state.lens.close()


app = FastAPI(title="Project PM", version="0.1.0", lifespan=lifespan)


# Auth: redirect unauthenticated users to login
from urllib.parse import quote  # noqa: E402

from project_pm.auth import LoginRequiredError  # noqa: E402


@app.exception_handler(LoginRequiredError)
async def login_required_handler(request, exc: LoginRequiredError):
    from fastapi.responses import RedirectResponse

    next_url = quote(exc.next_url, safe="")
    return RedirectResponse(url=f"/auth/login?next={next_url}")


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie="pm_session",
    max_age=14 * 24 * 3600,  # 14 days
    same_site="lax",
    https_only=not settings.debug,
)

# Jinja2 templates
app.state.templates = Jinja2Templates(directory=PROJECT_ROOT / "templates")


import re  # noqa: E402


def split_summary(text: str) -> dict:
    """Split summary into first sentence (description) and remaining (updates)."""
    if not text:
        return {"description": "", "updates": []}
    # Split on sentence boundaries (period followed by space and any word char)
    parts = re.split(r"(?<=\.)\s+(?=\w)", text, maxsplit=1)
    description = parts[0]
    updates = []
    if len(parts) > 1:
        updates = re.split(r"(?<=\.)\s+(?=\w)", parts[1])
    return {"description": description, "updates": updates}


app.state.templates.env.filters["split_summary"] = split_summary


from datetime import datetime, timezone  # noqa: E402


def days_ago(date_val) -> str:
    """Convert a date string or datetime to 'N days ago' / 'today' / 'yesterday'."""
    if not date_val:
        return ""
    try:
        if isinstance(date_val, datetime):
            dt = date_val
        else:
            dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        days = delta.days
        if days == 0:
            return "today"
        elif days == 1:
            return "yesterday"
        elif days < 30:
            return f"{days} days ago"
        elif days < 365:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
    except (ValueError, TypeError):
        return str(date_val)[:10] if date_val else ""


app.state.templates.env.filters["days_ago"] = days_ago
app.state.templates.env.globals["admin_usernames"] = settings.admin_usernames_set


from fastapi.responses import RedirectResponse as _Redirect  # noqa: E402
from project_pm.auth import get_current_user  # noqa: E402


@app.get("/")
async def root(request):
    """Redirect logged-in users to their board, others to login."""
    user = get_current_user(request)
    if user:
        return _Redirect(url=f"/board/{user['github_username']}", status_code=302)
    return _Redirect(url="/auth/login", status_code=302)


# Static files
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

# Routes
from project_pm.api.activity import router as activity_router  # noqa: E402
from project_pm.api.admin import router as admin_router  # noqa: E402
from project_pm.api.auth import router as auth_router  # noqa: E402
from project_pm.api.board import router as board_router  # noqa: E402
from project_pm.api.profile import router as profile_router  # noqa: E402
from project_pm.api.search import router as search_router  # noqa: E402

app.include_router(auth_router)
app.include_router(activity_router)
app.include_router(admin_router)
app.include_router(board_router)
app.include_router(profile_router)
app.include_router(search_router)
