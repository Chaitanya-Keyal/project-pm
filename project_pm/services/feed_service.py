"""Build a mixed activity feed from Lens data — merged/closed PRs, issues, Telegram digests."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from project_lens import LensClient

from project_pm.services.board_service import group_by_recency


@dataclass
class FeedItem:
    """A single item in the mixed activity feed."""

    item_type: str  # "pr_merged", "pr_closed", "issue", "telegram"
    title: str
    summary: str
    detail_url: str
    updated_at: datetime | None = None  # primary sort key (used by group_by_recency)
    created_at: datetime | None = None  # fallback for group_by_recency

    # PR fields (pr_merged / pr_closed)
    repo: str | None = None
    number: int | None = None
    author: str | None = None
    tier: int | None = None
    risk: str | None = None
    state: str | None = None
    outcome_category: str | None = None

    # Issue fields
    labels: list[str] | None = None
    comment_count: int | None = None
    category: str | None = None
    discussion_state: str | None = None
    impact: str | None = None

    # Telegram fields
    topic: str | None = None
    tg_category: str | None = None
    period: str | None = None

    @property
    def short_repo(self) -> str:
        if not self.repo:
            return ""
        return self.repo.split("/")[-1] if "/" in self.repo else self.repo


def _first_sentence(text: str | None) -> str:
    """Extract the first sentence from text."""
    if not text:
        return ""
    import re
    m = re.match(r"^(.+?\.)\s", text)
    return m.group(1) if m else text[:200]


async def build_activity_feed(
    lens: LensClient,
    days: int = 90,
    filter_type: str = "all",
) -> list[tuple[str, list[FeedItem]]]:
    """Fetch and merge activity from all sources into a grouped feed.

    filter_type: "all", "prs", "issues", or "telegram"
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Fetch all sources in parallel
    closed_prs_coro = lens.get_recently_closed_prs(since=cutoff)
    issues_coro = lens.get_open_issues_with_assessments()
    telegram_coro = lens.get_recent_telegram_digests(since=cutoff)

    closed_prs, issues, digests = await asyncio.gather(
        closed_prs_coro, issues_coro, telegram_coro,
    )

    items: list[FeedItem] = []

    # Merged/closed PRs
    if filter_type in ("all", "prs"):
        for pr in closed_prs:
            event_type = "pr_merged" if pr.state == "merged" else "pr_closed"
            event_ts = pr.merged_at or pr.closed_at or pr.updated_at
            outcome_cat = None
            if pr.outcome and isinstance(pr.outcome, dict):
                outcome_cat = pr.outcome.get("category")
            items.append(FeedItem(
                item_type=event_type,
                title=f"{'Merged' if pr.state == 'merged' else 'Closed'} PR #{pr.number} — {pr.title}",
                summary=_first_sentence(pr.summary),
                detail_url=f"/search/pr/{pr.repo}/{pr.number}",
                updated_at=event_ts,
                created_at=pr.created_at,
                repo=pr.repo,
                number=pr.number,
                author=pr.author,
                tier=pr.tier,
                risk=pr.risk,
                state=pr.state,
                outcome_category=outcome_cat,
            ))

    # Open issues
    if filter_type in ("all", "issues"):
        for issue in issues:
            items.append(FeedItem(
                item_type="issue",
                title=f"{'New Issue' if issue.comment_count == 0 else 'Issue Discussion'}: {issue.title}",
                summary=_first_sentence(issue.summary),
                detail_url=f"/search/issue/{issue.repo}/{issue.number}",
                updated_at=issue.updated_at,
                created_at=issue.created_at,
                repo=issue.repo,
                number=issue.number,
                author=issue.author,
                tier=issue.tier,
                category=issue.category,
                discussion_state=issue.discussion_state,
                impact=issue.impact,
                labels=issue.labels,
                comment_count=issue.comment_count,
            ))

    # Telegram digests
    if filter_type in ("all", "telegram"):
        for d in digests:
            items.append(FeedItem(
                item_type="telegram",
                title=d.topic or "Discussion",
                summary=d.summary,
                detail_url=f"/search/telegram/{d.chroma_id}",
                updated_at=d.updated_at,
                created_at=d.created_at,
                topic=d.topic,
                tg_category=d.category,
                period=d.period,
            ))

    # Sort by most recent first, then group into time buckets
    items.sort(key=lambda i: i.updated_at or i.created_at or datetime.min, reverse=True)
    return group_by_recency(items)
