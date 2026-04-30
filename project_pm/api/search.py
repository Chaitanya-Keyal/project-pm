"""Search routes — general topic search, Telegram detail, and PR/issue detail pages."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from project_lens import (
    IssueWithAssessment,
    LensClient,
    PRWithAssessment,
    SearchResult,
)

from project_lens.api.telegram import _parse_digest_metadata

from project_pm.auth import require_login
from project_pm.services.board_service import build_pr_detail

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


def _get_lens(request: Request) -> LensClient:
    return request.app.state.lens


def _parse_filters(request: Request) -> tuple[bool, bool, bool]:
    """Derive checkbox state from query params.

    Checked checkboxes send their value; unchecked ones are absent.
    On initial page load (no query), all default to on.
    """
    params = request.query_params
    has_query = "q" in params and params["q"].strip()
    if not has_query:
        return True, True, True
    include_prs = "prs" in params
    include_issues = "issues" in params
    include_telegram = "telegram" in params
    if not include_prs and not include_issues and not include_telegram:
        return True, True, True
    return include_prs, include_issues, include_telegram


def _active_collections(include_prs: bool, include_issues: bool, include_telegram: bool) -> list[str] | None:
    """Map filter checkboxes to collection names. None = search all."""
    if include_prs and include_issues and include_telegram:
        return None
    cols = []
    if include_prs:
        cols.append("pr_assessments")
    if include_issues:
        cols.append("issue_assessments")
    if include_telegram:
        cols.append("telegram_threads")
    return cols or None


async def _enrich_prs_full(
    results: list[SearchResult], lens: LensClient,
) -> dict[str, PRWithAssessment]:
    """Batch-fetch full PR+assessment data for PR search results. Keyed by result.id."""
    pr_keys = [
        (r.metadata.get("repo"), r.metadata.get("pr_number"))
        for r in results
        if r.source_type == "pr_assessment"
        and r.metadata.get("repo")
        and r.metadata.get("pr_number")
    ]
    if not pr_keys:
        return {}
    by_key = await lens.get_prs_by_keys(pr_keys)
    out: dict[str, PRWithAssessment] = {}
    for r in results:
        if r.source_type == "pr_assessment":
            key = (r.metadata.get("repo"), r.metadata.get("pr_number"))
            if key in by_key:
                out[r.id] = by_key[key]
    return out


def _enrich_telegram_cards(results: list[SearchResult]) -> dict[str, dict]:
    """Normalize telegram search results into card-ready dicts keyed by result.id.

    Parses the raw digest text to strip header lines / bullets and derive a
    clean narrative summary, matching the shape that TelegramDigestSummary
    produces for the activity feed.
    """
    out: dict[str, dict] = {}
    for r in results:
        if r.source_type != "telegram_thread":
            continue
        meta = _parse_digest_metadata(r.text or "")
        md = r.metadata or {}
        out[r.id] = {
            "chroma_id": r.id,
            "topic": meta.get("topic") or md.get("topic") or "",
            "category": meta.get("category") or md.get("category") or "",
            "period": meta.get("period") or md.get("period") or "",
            "summary": meta.get("summary") or "",
        }
    return out


async def _enrich_issues_full(
    results: list[SearchResult], lens: LensClient,
) -> dict[str, IssueWithAssessment]:
    """Batch-fetch full issue+assessment data for issue search results. Keyed by result.id."""
    issue_keys = [
        (r.metadata.get("repo"), r.metadata.get("issue_number"))
        for r in results
        if r.source_type == "issue_assessment"
        and r.metadata.get("repo")
        and r.metadata.get("issue_number")
    ]
    if not issue_keys:
        return {}
    by_key = await lens.get_issues_by_keys(issue_keys)
    out: dict[str, IssueWithAssessment] = {}
    for r in results:
        if r.source_type == "issue_assessment":
            key = (r.metadata.get("repo"), r.metadata.get("issue_number"))
            if key in by_key:
                out[r.id] = by_key[key]
    return out


async def _run_search(
    lens: LensClient,
    query: str,
    include_prs: bool,
    include_issues: bool,
    include_telegram: bool,
    n_results: int = 15,
) -> tuple[
    list[SearchResult],
    dict[str, PRWithAssessment],
    dict[str, IssueWithAssessment],
    dict[str, dict],
]:
    """Run the hybrid search and enrich hits with card-ready data."""
    cols = _active_collections(include_prs, include_issues, include_telegram)
    results = await lens.search(query, n_results=n_results, collections=cols)
    prs_by_id = await _enrich_prs_full(results, lens)
    issues_by_id = await _enrich_issues_full(results, lens)
    telegram_by_id = _enrich_telegram_cards(results)
    return results, prs_by_id, issues_by_id, telegram_by_id


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, q: str = "", user: dict = Depends(require_login)):
    """Full search page — renders form + results."""
    templates = request.app.state.templates
    lens = _get_lens(request)
    results: list[SearchResult] = []
    prs_by_id: dict[str, PRWithAssessment] = {}
    issues_by_id: dict[str, IssueWithAssessment] = {}
    telegram_by_id: dict[str, dict] = {}
    error = None
    include_prs, include_issues, include_telegram = _parse_filters(request)

    if q.strip():
        try:
            results, prs_by_id, issues_by_id, telegram_by_id = await _run_search(
                lens, q.strip(), include_prs, include_issues, include_telegram,
            )
        except Exception as exc:
            error = str(exc)
            logger.warning("Search unavailable: %s", error)

    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "q": q,
            "results": results,
            "prs_by_id": prs_by_id,
            "issues_by_id": issues_by_id,
            "telegram_by_id": telegram_by_id,
            "error": error,
            "include_prs": include_prs,
            "include_issues": include_issues,
            "include_telegram": include_telegram,
        },
    )


@router.get("/search/results", response_class=HTMLResponse)
async def search_results_partial(request: Request, q: str = "", user: dict = Depends(require_login)):
    """HTMX partial — returns just the results list for live search."""
    templates = request.app.state.templates
    lens = _get_lens(request)
    results: list[SearchResult] = []
    prs_by_id: dict[str, PRWithAssessment] = {}
    issues_by_id: dict[str, IssueWithAssessment] = {}
    telegram_by_id: dict[str, dict] = {}
    error = None
    include_prs, include_issues, include_telegram = _parse_filters(request)

    if q.strip():
        try:
            results, prs_by_id, issues_by_id, telegram_by_id = await _run_search(
                lens, q.strip(), include_prs, include_issues, include_telegram,
            )
        except Exception as exc:
            error = str(exc)

    return templates.TemplateResponse(
        request=request,
        name="search/_results.html",
        context={
            "q": q,
            "results": results,
            "prs_by_id": prs_by_id,
            "issues_by_id": issues_by_id,
            "telegram_by_id": telegram_by_id,
            "error": error,
        },
    )


def _parse_telegram_text(raw: str) -> dict:
    """Parse structured telegram digest text into sections."""
    lines = raw.split("\n")

    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "" and i > 0:
            body_start = i + 1
            break

    narrative_lines = []
    highlight_bullets = []
    person_bullets = []

    person_pattern = re.compile(r"^- ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*): (.+)$")

    in_bullets = False
    for line in lines[body_start:]:
        stripped = line.strip()
        if stripped.startswith("- "):
            in_bullets = True
            m = person_pattern.match(stripped)
            if m:
                person_bullets.append({"name": m.group(1), "text": m.group(2)})
            else:
                highlight_bullets.append(stripped[2:])
        elif not in_bullets and stripped:
            narrative_lines.append(stripped)

    full_narrative = " ".join(narrative_lines)
    summary = ""
    remainder = ""
    if full_narrative:
        m = re.match(r"^(.+?\.)\s+(.+)$", full_narrative, re.DOTALL)
        if m:
            summary = m.group(1)
            remainder = m.group(2)
        else:
            summary = full_narrative

    return {
        "summary": summary,
        "narrative": remainder,
        "highlights": highlight_bullets,
        "person_takes": person_bullets,
    }


async def _get_telegram_link(lens: LensClient, chroma_id: str) -> str | None:
    """Build a Telegram deep link for a thread digest.

    Queries first_message_id from Lens's ai_digests table and constructs
    https://t.me/c/{chat_id}/{message_id}.

    TODO: Move this into LensClient API so PM doesn't query Lens DB directly.
    """
    from sqlalchemy import text as sa_text

    # ChromaDB ID: tg_chat_1829170082/2023-11-16_to_2023-11-23/thread_2
    # ai_digests source_ref: chat_1829170082/2023-11-16_to_2023-11-23/thread_2
    source_ref = chroma_id.removeprefix("tg_")

    parts = source_ref.split("/")
    chat_id_str = parts[0].removeprefix("chat_")

    async with lens._config.async_session() as session:
        result = await session.execute(
            sa_text(
                "SELECT first_message_id FROM ai_digests "
                "WHERE source_type = 'telegram_thread' AND source_ref = :ref"
            ),
            {"ref": source_ref},
        )
        row = result.fetchone()

    if not row or not row[0]:
        return None

    # chat_id in source_ref may be positive (1829170082) or negative (-1001829170082).
    # t.me/c/ needs the raw number without the -100 prefix.
    chat_id = chat_id_str.lstrip("-")
    if chat_id.startswith("100"):
        chat_id = chat_id[3:]

    return f"https://t.me/c/{chat_id}/{row[0]}"


@router.get("/search/telegram/{chroma_id:path}", response_class=HTMLResponse)
async def telegram_detail_page(request: Request, chroma_id: str, user: dict = Depends(require_login)):
    """Full detail page for a Telegram thread digest."""
    templates = request.app.state.templates
    lens = _get_lens(request)
    try:
        thread = await lens.get_document("telegram_threads", chroma_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    parsed = _parse_telegram_text(thread.text)

    person_names = [t["name"] for t in parsed["person_takes"]]
    github_map = await lens.resolve_display_names(person_names)
    for take in parsed["person_takes"]:
        take["github_login"] = github_map.get(take["name"])

    telegram_link = await _get_telegram_link(lens, chroma_id)

    return templates.TemplateResponse(
        request=request,
        name="telegram_detail.html",
        context={
            "thread": thread,
            "parsed": parsed,
            "telegram_link": telegram_link,
            "back_url": "javascript:history.back()",
            "back_label": "Back",
        },
    )


@router.get("/search/pr/{repo_owner}/{repo_name}/{pr_number:int}", response_class=HTMLResponse)
async def pr_detail_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    user: dict = Depends(require_login),
):
    """Full detail page for a PR assessment, accessed from search results."""
    templates = request.app.state.templates
    lens = _get_lens(request)
    repo = f"{repo_owner}/{repo_name}"

    detail = await build_pr_detail(lens, repo, pr_number)
    if not detail:
        raise HTTPException(status_code=404, detail="PR not found")

    return templates.TemplateResponse(
        request=request,
        name="pr_detail.html",
        context={
            "detail": detail,
            "back_url": "javascript:history.back()",
            "back_label": "Back",
        },
    )


@router.get("/search/issue/{repo_owner}/{repo_name}/{issue_number:int}", response_class=HTMLResponse)
async def issue_detail_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    issue_number: int,
    user: dict = Depends(require_login),
):
    """Full detail page for a GitHub issue assessment."""
    templates = request.app.state.templates
    lens = _get_lens(request)
    repo = f"{repo_owner}/{repo_name}"

    try:
        detail = await lens.get_issue_detail(repo, issue_number)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if not detail:
        raise HTTPException(status_code=404, detail="Issue not found")

    return templates.TemplateResponse(
        request=request,
        name="issue_detail.html",
        context={
            "detail": detail,
            "back_url": "javascript:history.back()",
            "back_label": "Back",
        },
    )


@router.get("/search/pr-context/{repo_owner}/{repo_name}/{number:int}", response_class=HTMLResponse)
async def related_context(
    request: Request,
    repo_owner: str,
    repo_name: str,
    number: int,
    summary: str = "",
    source: str = "pr",
    user: dict = Depends(require_login),
):
    """HTMX partial — related context for a PR or issue detail page."""
    templates = request.app.state.templates
    lens = _get_lens(request)
    results: list[SearchResult] = []
    prs_by_id: dict[str, PRWithAssessment] = {}
    issues_by_id: dict[str, IssueWithAssessment] = {}
    telegram_by_id: dict[str, dict] = {}
    error = None
    repo = f"{repo_owner}/{repo_name}"

    if summary.strip():
        try:
            if source == "issue":
                query = f"Issue #{number} ({repo}): {summary}"
                exclude_id = f"issue_{repo}_{number}"
            else:
                query = f"PR #{number} ({repo}): {summary}"
                exclude_id = f"pr_{repo}_{number}"
            results = await lens.search_related(query, exclude_id=exclude_id, n_results=5)
            prs_by_id = await _enrich_prs_full(results, lens)
            issues_by_id = await _enrich_issues_full(results, lens)
            telegram_by_id = _enrich_telegram_cards(results)
        except Exception as exc:
            error = str(exc)
            logger.warning("Related context search unavailable: %s", error)

    return templates.TemplateResponse(
        request=request,
        name="search/_pr_context.html",
        context={
            "results": results,
            "prs_by_id": prs_by_id,
            "issues_by_id": issues_by_id,
            "telegram_by_id": telegram_by_id,
            "error": error,
        },
    )
