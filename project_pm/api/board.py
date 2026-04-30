from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_pm.auth import require_board_access
from project_pm.database import get_pm_db
from project_pm.models.contributor import Contributor
from project_pm.services.board_service import build_board, build_pr_detail

router = APIRouter(tags=["board"])


async def _get_role(pm_db: AsyncSession, github_username: str) -> str | None:
    """Look up optional role override from Contributor record."""
    result = await pm_db.execute(
        select(Contributor.role).where(Contributor.github_username == github_username)
    )
    row = result.first()
    return row[0] if row else None


@router.get("/board/{github_username}", response_class=HTMLResponse)
async def board_page(
    request: Request,
    github_username: str = Depends(require_board_access),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    lens = request.app.state.lens
    role = await _get_role(pm_db, github_username)
    board = await build_board(lens, github_username, role=role)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="board.html",
        context={"board": board},
    )


@router.get(
    "/board/{github_username}/pr/{repo_owner}/{repo_name}/{pr_number:int}",
    response_class=HTMLResponse,
)
async def pr_detail_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    github_username: str = Depends(require_board_access),
):
    lens = request.app.state.lens
    repo = f"{repo_owner}/{repo_name}"
    detail = await build_pr_detail(lens, repo, pr_number)
    if not detail:
        raise HTTPException(status_code=404, detail="PR not found")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="pr_detail.html",
        context={
            "detail": detail,
            "back_url": f"/board/{github_username}",
            "back_label": "Back to board",
        },
    )
