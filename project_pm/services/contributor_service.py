"""Discover contributors from Lens data and manage PM contributor records."""

import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_lens import LensClient

from project_pm.models.contributor import Contributor


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
    lens: LensClient, pm_db: AsyncSession
) -> list[DiscoveredContributor]:
    """Query Lens for all contributors, merge with PM enabled status."""
    lens_contributors = await lens.discover_contributors()

    contributors = [
        DiscoveredContributor(
            github_username=c.github_username,
            pr_count=c.pr_count,
            review_count=c.review_count,
            comment_count=c.comment_count,
            last_activity=str(c.last_active) if c.last_active else None,
        )
        for c in lens_contributors
    ]

    # Merge with PM enabled status
    enabled_result = await pm_db.execute(select(Contributor))
    enabled_map = {c.github_username: c for c in enabled_result.scalars().all()}

    for dc in contributors:
        if dc.github_username in enabled_map:
            dc.enabled = True
            dc.role = enabled_map[dc.github_username].role

    # Sort by total activity descending
    return sorted(contributors, key=lambda c: c.total_activity, reverse=True)


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
