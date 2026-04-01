from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from backend.config import settings
from backend.database import pm_engine
from backend.models import *  # noqa: F401, F403 — register all models
from backend.models.base import Base

PROJECT_ROOT = Path(__file__).parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_lens_path()

    # Create PM tables on startup
    async with pm_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield


app = FastAPI(title="Project PM", version="0.1.0", lifespan=lifespan)

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


def days_ago(date_str: str) -> str:
    """Convert a date string to 'N days ago' / 'today' / 'yesterday'."""
    if not date_str:
        return ""
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
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
        return date_str[:10] if date_str else ""


app.state.templates.env.filters["days_ago"] = days_ago

# Static files
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

# Routes
from backend.api.admin import router as admin_router  # noqa: E402
from backend.api.board import router as board_router  # noqa: E402

app.include_router(admin_router)
app.include_router(board_router)
