"""GitHub OAuth login/logout routes."""

import secrets

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from project_pm.config import settings
from project_pm.database import get_pm_db_context
from project_pm.models.contributor import Contributor

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    """Show login page, or redirect home if already logged in."""
    if request.session.get("github_username"):
        return RedirectResponse(url=next, status_code=302)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="auth/login.html",
        context={"next": next},
    )


@router.get("/github")
async def github_redirect(request: Request, next: str = "/"):
    """Redirect to GitHub OAuth authorize page."""
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = next

    callback_url = f"{settings.base_url}/auth/callback"
    params = (
        f"client_id={settings.github_client_id}"
        f"&redirect_uri={callback_url}"
        f"&state={state}"
    )
    return RedirectResponse(url=f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle GitHub OAuth callback."""
    # User denied authorization
    if error:
        return RedirectResponse(url="/auth/denied")

    # Validate state
    expected_state = request.session.pop("oauth_state", None)
    if not state or state != expected_state:
        return RedirectResponse(url="/auth/denied")

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            return RedirectResponse(url="/auth/denied")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return RedirectResponse(url="/auth/denied")

        # Fetch user profile
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if user_resp.status_code != 200:
            return RedirectResponse(url="/auth/denied")

        user_data = user_resp.json()

    github_username = user_data.get("login", "")
    avatar_url = user_data.get("avatar_url", "")

    # Check authorization: admin config OR Lens activity
    is_admin = github_username.lower() in settings.admin_usernames_set
    if not is_admin:
        lens = request.app.state.lens
        contributors = await lens.discover_contributors()
        known_usernames = {c.github_username.lower() for c in contributors}
        if github_username.lower() not in known_usernames:
            return RedirectResponse(url="/auth/denied")

    # Set session
    request.session["github_username"] = github_username
    request.session["github_avatar_url"] = avatar_url

    # Auto-create Contributor record on first login (for Telegram linking)
    next_url = request.session.pop("oauth_next", "/")

    async with get_pm_db_context() as pm_db:
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
            await pm_db.commit()

        if not contributor.telegram_confirmed:
            request.session["post_profile_next"] = next_url
            return RedirectResponse(url="/profile")

    return RedirectResponse(url=next_url)


@router.post("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=303)


@router.get("/denied", response_class=HTMLResponse)
async def denied(request: Request):
    """Show access denied page."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="auth/denied.html",
    )
