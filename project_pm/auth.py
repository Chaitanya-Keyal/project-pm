"""Auth dependencies for route protection."""

from urllib.parse import quote

from fastapi import Request
from starlette.exceptions import HTTPException

from project_pm.config import settings


class LoginRequiredError(HTTPException):
    """Raised when an unauthenticated user hits a protected route."""

    def __init__(self, next_url: str):
        self.next_url = next_url
        super().__init__(status_code=401)


def get_current_user(request: Request) -> dict | None:
    """Read session and return user info, or None if not logged in."""
    username = request.session.get("github_username")
    if not username:
        return None
    return {
        "github_username": username,
        "avatar_url": request.session.get("github_avatar_url", ""),
        "is_admin": username.lower() in settings.admin_usernames_set,
    }


def require_login(request: Request) -> dict:
    """Return current user or redirect to login."""
    user = get_current_user(request)
    if not user:
        raise LoginRequiredError(next_url=str(request.url))
    return user


def require_admin(request: Request) -> dict:
    """Require login + admin role."""
    user = require_login(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_board_access(
    request: Request,
    github_username: str,
) -> str:
    """Require login + (username match OR admin). Returns the github_username."""
    user = require_login(request)
    if user["github_username"].lower() != github_username.lower() and not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Access denied")
    return github_username
