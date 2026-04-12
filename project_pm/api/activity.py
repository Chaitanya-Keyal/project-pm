"""Activity Feed — merged/closed PRs, open issues, and Telegram community discussions."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from project_pm.auth import require_login
from project_pm.services.feed_service import build_activity_feed

router = APIRouter(tags=["activity"])


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request, user: dict = Depends(require_login)):
    """Activity feed — mixed content sorted by most recent activity."""
    templates = request.app.state.templates
    lens = request.app.state.lens
    filter_type = request.query_params.get("type", "all")
    groups = await build_activity_feed(lens, days=90, filter_type=filter_type)

    return templates.TemplateResponse(
        request=request,
        name="activity.html",
        context={"groups": groups, "filter_type": filter_type},
    )


@router.get("/activity/cards", response_class=HTMLResponse)
async def activity_cards_partial(request: Request, user: dict = Depends(require_login)):
    """HTMX partial — returns just the card list for polling updates."""
    templates = request.app.state.templates
    lens = request.app.state.lens
    filter_type = request.query_params.get("type", "all")
    groups = await build_activity_feed(lens, days=90, filter_type=filter_type)

    return templates.TemplateResponse(
        request=request,
        name="activity/_card_list.html",
        context={"groups": groups, "filter_type": filter_type},
    )
