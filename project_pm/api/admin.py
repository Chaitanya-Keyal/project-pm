from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from project_pm.auth import require_admin
from project_pm.database import get_pm_db
from project_pm.services.contributor_service import discover_contributors

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/contributors", response_class=HTMLResponse)
async def contributors_page(
    request: Request,
    user: dict = Depends(require_admin),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    lens = request.app.state.lens
    contributors = await discover_contributors(lens, pm_db)
    groups = [
        ("Key Contributors",         [c for c in contributors if c.group_tier == "high"]),
        ("Significant Contributors", [c for c in contributors if c.group_tier == "moderate"]),
        ("Notable Contributors",     [c for c in contributors if c.group_tier == "regular"]),
        ("Contributors",             [c for c in contributors if c.group_tier == "low"]),
        ("Minimal Activity",         [c for c in contributors if c.group_tier == "none"]),
    ]
    # Drop empty groups
    groups = [(label, members) for label, members in groups if members]
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="admin/contributors.html",
        context={"contributors": contributors, "groups": groups},
    )
