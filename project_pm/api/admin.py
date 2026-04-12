from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from project_pm.auth import require_admin
from project_pm.database import get_pm_db
from project_pm.services.contributor_service import (
    discover_contributors,
    disable_contributor,
    enable_contributor,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/contributors", response_class=HTMLResponse)
async def contributors_page(
    request: Request,
    user: dict = Depends(require_admin),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    lens = request.app.state.lens
    contributors = await discover_contributors(lens, pm_db)
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="admin/contributors.html",
        context={"contributors": contributors},
    )


@router.post("/contributors/{github_username}/enable", response_class=HTMLResponse)
async def enable_contributor_route(
    request: Request,
    github_username: str,
    user: dict = Depends(require_admin),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    await enable_contributor(pm_db, github_username)

    lens = request.app.state.lens
    contributors = await discover_contributors(lens, pm_db)
    contributor = next(
        (c for c in contributors if c.github_username == github_username), None
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="admin/_contributor_row.html",
        context={"c": contributor},
    )


@router.post("/contributors/{github_username}/disable", response_class=HTMLResponse)
async def disable_contributor_route(
    request: Request,
    github_username: str,
    user: dict = Depends(require_admin),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    await disable_contributor(pm_db, github_username)

    lens = request.app.state.lens
    contributors = await discover_contributors(lens, pm_db)
    contributor = next(
        (c for c in contributors if c.github_username == github_username), None
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="admin/_contributor_row.html",
        context={"c": contributor},
    )
