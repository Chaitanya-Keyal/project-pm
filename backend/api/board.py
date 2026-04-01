from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_lens_db, get_pm_db
from backend.models.contributor import Contributor
from backend.services.board_service import build_board, build_pr_detail

router = APIRouter(tags=["board"])


async def _get_contributor_by_token(
    github_username: str, token: str, pm_db: AsyncSession
) -> Contributor:
    """Validate token and return the contributor."""
    result = await pm_db.execute(
        select(Contributor).where(Contributor.github_username == github_username)
    )
    contributor = result.scalar_one_or_none()
    if not contributor:
        raise HTTPException(status_code=404, detail="Board not found")
    if contributor.auth_token != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    return contributor


@router.get("/board/{github_username}", response_class=HTMLResponse)
async def board_page(
    request: Request,
    github_username: str,
    token: str = "",
    lens_db: AsyncSession = Depends(get_lens_db),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    contributor = await _get_contributor_by_token(github_username, token, pm_db)
    board = await build_board(lens_db, pm_db, contributor)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="board.html",
        context={"board": board, "token": token},
    )


@router.get(
    "/board/{github_username}/pr/{repo_owner}/{repo_name}/{pr_number:int}",
    response_class=HTMLResponse,
)
async def pr_detail_page(
    request: Request,
    github_username: str,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    token: str = "",
    lens_db: AsyncSession = Depends(get_lens_db),
    pm_db: AsyncSession = Depends(get_pm_db),
):
    contributor = await _get_contributor_by_token(github_username, token, pm_db)
    repo = f"{repo_owner}/{repo_name}"
    detail = await build_pr_detail(lens_db, contributor, repo, pr_number)
    if not detail:
        raise HTTPException(status_code=404, detail="PR not found")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="board/pr_detail.html",
        context={
            "detail": detail,
            "contributor": contributor,
            "token": token,
        },
    )
