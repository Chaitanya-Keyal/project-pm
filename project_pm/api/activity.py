"""Recent Activity — home page showing open PRs by recency."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from project_lens import LensClient, PRWithAssessment

router = APIRouter(tags=["activity"])


def _recency_label(dt: datetime | None, now: datetime, boundaries: dict) -> str:
    """Return a human-friendly time bucket label for a datetime."""
    if not dt:
        return "Older"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt >= boundaries["today"]:
        return "Today"
    if dt >= boundaries["yesterday"]:
        return "Yesterday"
    if dt >= boundaries["this_week"]:
        return "This week"
    if dt >= boundaries["last_week"]:
        return "Last week"
    if dt >= boundaries["this_month"]:
        return "This month"
    return "Older"


def _group_by_recency(
    prs: list[PRWithAssessment],
) -> list[tuple[str, list[PRWithAssessment]]]:
    """Group already-sorted PRs into time buckets. Returns [(label, prs), ...]."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    boundaries = {
        "today": today_start,
        "yesterday": today_start - timedelta(days=1),
        "this_week": today_start - timedelta(days=today_start.weekday()),
        "last_week": today_start - timedelta(days=today_start.weekday() + 7),
        "this_month": today_start.replace(day=1),
    }

    groups: list[tuple[str, list[PRWithAssessment]]] = []
    current_label = None
    current_prs: list[PRWithAssessment] = []

    for pr in prs:
        label = _recency_label(pr.updated_at or pr.created_at, now, boundaries)
        if label != current_label:
            if current_prs:
                groups.append((current_label, current_prs))
            current_label = label
            current_prs = [pr]
        else:
            current_prs.append(pr)

    if current_prs:
        groups.append((current_label, current_prs))

    return groups


async def _get_grouped_prs(lens: LensClient):
    """Fetch open PRs, sort by recency, and group into time buckets."""
    prs = await lens.get_open_prs_with_assessments()
    prs.sort(key=lambda p: p.updated_at or p.created_at or datetime.min, reverse=True)
    return _group_by_recency(prs)


@router.get("/", response_class=HTMLResponse)
async def activity_page(request: Request):
    """Home page — all open PRs sorted by most recent activity."""
    templates = request.app.state.templates
    lens = request.app.state.lens
    groups = await _get_grouped_prs(lens)

    return templates.TemplateResponse(
        request=request,
        name="activity.html",
        context={"groups": groups},
    )


@router.get("/activity/cards", response_class=HTMLResponse)
async def activity_cards_partial(request: Request):
    """HTMX partial — returns just the card list for polling updates."""
    templates = request.app.state.templates
    lens = request.app.state.lens
    groups = await _get_grouped_prs(lens)

    return templates.TemplateResponse(
        request=request,
        name="activity/_card_list.html",
        context={"groups": groups},
    )
