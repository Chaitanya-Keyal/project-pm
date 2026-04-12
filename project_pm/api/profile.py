"""Profile page — Telegram linking flow."""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_pm.auth import require_login
from project_pm.database import get_pm_db
from project_pm.models.contributor import Contributor

router = APIRouter(tags=["profile"])


def _normalize(name: str) -> str:
    """Normalize a name for fuzzy matching (same logic as Lens identity)."""
    return re.sub(r"[\s\-_.]", "", name.lower())


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: dict = Depends(require_login),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    """Show profile page with Telegram linking form."""
    lens = request.app.state.lens
    github_username = user["github_username"]

    # Get current contributor record
    result = await pm_db.execute(
        select(Contributor).where(Contributor.github_username == github_username)
    )
    contributor = result.scalar_one_or_none()

    # Get Lens profile for auto-detected display names
    suggested_names = []
    profiles = await lens.list_contributor_profiles()
    for p in profiles:
        if p.github_login.lower() == github_username.lower():
            # Filter out the GitHub username itself — user already knows that
            suggested_names = [
                n for n in p.display_names
                if _normalize(n) != _normalize(github_username)
            ]
            break

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "user": user,
            "contributor": contributor,
            "suggested_names": suggested_names,
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/profile/telegram")
async def save_telegram(
    request: Request,
    user: dict = Depends(require_login),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    """Validate and save Telegram display name."""
    form = await request.form()
    telegram_name = str(form.get("telegram_name", "")).strip()
    github_username = user["github_username"]

    if not telegram_name:
        return RedirectResponse(url="/profile?error=Please+enter+a+name", status_code=303)

    # Validate against known Telegram participants (if data is available)
    lens = request.app.state.lens
    participants = await lens.list_telegram_participants()
    matched_name = telegram_name  # Default: accept as-is

    if participants:
        # We have Telegram message data — validate the name
        normalized_input = _normalize(telegram_name)
        found = None
        for p in participants:
            if _normalize(p) == normalized_input:
                found = p  # Use the canonical form from the database
                break
        if not found:
            return RedirectResponse(
                url="/profile?error=Name+not+found+in+Telegram+history.+Enter+your+exact+display+name.",
                status_code=303,
            )
        matched_name = found

    # Update contributor record (auto-create if missing)
    result = await pm_db.execute(
        select(Contributor).where(Contributor.github_username == github_username)
    )
    contributor = result.scalar_one_or_none()
    if not contributor:
        contributor = Contributor(
            github_username=github_username,
            display_name=github_username,
        )
        pm_db.add(contributor)
    contributor.telegram_display_name = matched_name
    contributor.telegram_confirmed = True
    await pm_db.commit()

    # Redirect to stored next URL or home
    next_url = request.session.pop("post_profile_next", "/")
    return RedirectResponse(url=next_url, status_code=303)
