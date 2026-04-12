from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from project_pm.auth import require_board_access
from project_pm.models.contributor import Contributor
from project_pm.services.board_service import build_board, build_pr_detail

router = APIRouter(tags=["board"])


@router.get("/board/{github_username}", response_class=HTMLResponse)
async def board_page(
    request: Request,
    contributor: Contributor = Depends(require_board_access),
):
    lens = request.app.state.lens
    board = await build_board(lens, contributor)

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
    contributor: Contributor = Depends(require_board_access),
):
    lens = request.app.state.lens
    repo = f"{repo_owner}/{repo_name}"
    detail = await build_pr_detail(lens, repo, pr_number, contributor=contributor)
    if not detail:
        raise HTTPException(status_code=404, detail="PR not found")

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="board/pr_detail.html",
        context={
            "detail": detail,
            "contributor": contributor,
        },
    )
