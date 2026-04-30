"""Build a mixed activity feed from Lens data — merged/closed PRs, issues, Telegram digests."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from project_lens import (
    IssueWithAssessment,
    LensClient,
    PRWithAssessment,
    TelegramDigestSummary,
)

from project_pm.services.board_service import group_by_recency


@dataclass
class FeedItem:
    """A single entry in the mixed activity feed.

    Carries the raw source object so templates can render it with the
    unified PR/issue/telegram card without shape translation.
    """

    item_type: str  # "pr_merged" | "pr_closed" | "issue" | "telegram"
    updated_at: datetime | None  # primary sort key (used by group_by_recency)
    created_at: datetime | None  # fallback sort key
    source: PRWithAssessment | IssueWithAssessment | TelegramDigestSummary


async def build_activity_feed(
    lens: LensClient,
    days: int = 90,
    filter_type: str = "all",
) -> list[tuple[str, list[FeedItem]]]:
    """Fetch and merge activity from all sources into a grouped feed.

    filter_type: "all", "prs", "issues", or "telegram"
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    closed_prs_coro = lens.get_recently_closed_prs(since=cutoff)
    issues_coro = lens.get_open_issues_with_assessments()
    telegram_coro = lens.get_recent_telegram_digests(since=cutoff)

    closed_prs, issues, digests = await asyncio.gather(
        closed_prs_coro, issues_coro, telegram_coro,
    )

    items: list[FeedItem] = []

    if filter_type in ("all", "prs"):
        for pr in closed_prs:
            item_type = "pr_merged" if pr.state == "merged" else "pr_closed"
            event_ts = pr.merged_at or pr.closed_at or pr.updated_at
            items.append(FeedItem(
                item_type=item_type,
                updated_at=event_ts,
                created_at=pr.created_at,
                source=pr,
            ))

    if filter_type in ("all", "issues"):
        for issue in issues:
            items.append(FeedItem(
                item_type="issue",
                updated_at=issue.updated_at,
                created_at=issue.created_at,
                source=issue,
            ))

    if filter_type in ("all", "telegram"):
        for d in digests:
            items.append(FeedItem(
                item_type="telegram",
                updated_at=d.updated_at,
                created_at=d.created_at,
                source=d,
            ))

    items.sort(key=lambda i: i.updated_at or i.created_at or datetime.min, reverse=True)
    return group_by_recency(items)
