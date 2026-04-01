"""Discover contributors from Lens data and manage PM contributor records."""

import json
import secrets
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.contributor import Contributor


@dataclass
class DiscoveredContributor:
    """A contributor discovered from Lens data (not yet necessarily enabled in PM)."""

    github_username: str
    pr_count: int
    review_count: int
    comment_count: int
    last_activity: str | None
    enabled: bool = False
    role: str | None = None

    @property
    def total_activity(self) -> int:
        return self.pr_count + self.review_count + self.comment_count


async def discover_contributors(
    lens_db: AsyncSession, pm_db: AsyncSession
) -> list[DiscoveredContributor]:
    """Query Lens DB for all unique contributors, merge with PM enabled status.

    Sources:
    - github_prs.author — PR authors (most reliable)
    - github_prs.reviews_json — reviewers (user.login from each review)
    - github_prs.issue_comments_json — commenters (user.login)
    """
    # 1. Get PR author counts and latest activity
    pr_authors = await lens_db.execute(text("""
        SELECT
            author,
            COUNT(*) as pr_count,
            MAX(COALESCE(updated_at_gh, created_at_gh)) as last_activity
        FROM github_prs
        GROUP BY author
    """))
    pr_author_rows = pr_authors.fetchall()

    # Build contributor dict keyed by username
    contributors: dict[str, DiscoveredContributor] = {}
    for username, pr_count, last_activity in pr_author_rows:
        contributors[username] = DiscoveredContributor(
            github_username=username,
            pr_count=pr_count,
            review_count=0,
            comment_count=0,
            last_activity=last_activity,
        )

    # 2. Extract reviewers and commenters from JSON blobs
    json_rows = await lens_db.execute(text("""
        SELECT reviews_json, review_comments_json, issue_comments_json,
               COALESCE(updated_at_gh, created_at_gh) as activity_date
        FROM github_prs
        WHERE reviews_json IS NOT NULL
           OR review_comments_json IS NOT NULL
           OR issue_comments_json IS NOT NULL
    """))

    for reviews_json, review_comments_json, issue_comments_json, activity_date in json_rows:
        # Reviewers
        if reviews_json:
            for review in json.loads(reviews_json):
                login = review.get("user", {}).get("login")
                if login:
                    if login not in contributors:
                        contributors[login] = DiscoveredContributor(
                            github_username=login,
                            pr_count=0,
                            review_count=0,
                            comment_count=0,
                            last_activity=activity_date,
                        )
                    contributors[login].review_count += 1
                    if activity_date and (
                        not contributors[login].last_activity
                        or activity_date > contributors[login].last_activity
                    ):
                        contributors[login].last_activity = activity_date

        # Review comments
        if review_comments_json:
            for comment in json.loads(review_comments_json):
                login = comment.get("user", {}).get("login")
                if login:
                    if login not in contributors:
                        contributors[login] = DiscoveredContributor(
                            github_username=login,
                            pr_count=0,
                            review_count=0,
                            comment_count=0,
                            last_activity=activity_date,
                        )
                    contributors[login].comment_count += 1

        # Issue comments
        if issue_comments_json:
            for comment in json.loads(issue_comments_json):
                login = comment.get("user", {}).get("login")
                if login:
                    if login not in contributors:
                        contributors[login] = DiscoveredContributor(
                            github_username=login,
                            pr_count=0,
                            review_count=0,
                            comment_count=0,
                            last_activity=activity_date,
                        )
                    contributors[login].comment_count += 1

    # 3. Merge with PM enabled status
    enabled_result = await pm_db.execute(select(Contributor))
    enabled_map = {c.github_username: c for c in enabled_result.scalars().all()}

    for username, dc in contributors.items():
        if username in enabled_map:
            dc.enabled = True
            dc.role = enabled_map[username].role

    # Sort by total activity descending
    return sorted(contributors.values(), key=lambda c: c.total_activity, reverse=True)


async def enable_contributor(pm_db: AsyncSession, github_username: str) -> Contributor:
    """Enable a contributor's board by creating a PM record with auth token."""
    token = secrets.token_urlsafe(24)
    contributor = Contributor(
        github_username=github_username,
        display_name=github_username,
        auth_token=token,
    )
    pm_db.add(contributor)
    await pm_db.commit()
    await pm_db.refresh(contributor)
    return contributor


async def disable_contributor(pm_db: AsyncSession, github_username: str) -> bool:
    """Disable a contributor's board by removing their PM record."""
    result = await pm_db.execute(
        select(Contributor).where(Contributor.github_username == github_username)
    )
    contributor = result.scalar_one_or_none()
    if contributor:
        await pm_db.delete(contributor)
        await pm_db.commit()
        return True
    return False


async def update_contributor_role(
    pm_db: AsyncSession, github_username: str, role: str | None
) -> Contributor | None:
    """Update an enabled contributor's role override."""
    result = await pm_db.execute(
        select(Contributor).where(Contributor.github_username == github_username)
    )
    contributor = result.scalar_one_or_none()
    if contributor:
        contributor.role = role if role else None
        await pm_db.commit()
        await pm_db.refresh(contributor)
    return contributor
