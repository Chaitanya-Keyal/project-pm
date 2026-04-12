"""Discover contributors from Lens data and manage PM contributor records."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_lens import LensClient

from project_pm.models.contributor import Contributor


@dataclass
class DiscoveredContributor:
    """A contributor discovered from Lens data."""

    github_username: str
    pr_count: int
    prs_merged: int
    prs_open: int
    review_count: int
    comment_count: int
    last_activity: str | None
    role: str | None = None
    merge_tier: str = "none"
    pr_tier: str = "none"
    review_tier: str = "none"

    @property
    def total_activity(self) -> int:
        return self.pr_count + self.review_count + self.comment_count

    @property
    def group_tier(self) -> str:
        """Contributor grouping based on highest tier across all categories."""
        tiers = {self.merge_tier, self.pr_tier, self.review_tier}
        if "high" in tiers:
            return "high"
        if "moderate" in tiers:
            return "moderate"
        if "low" in tiers:
            return "low"
        return "none"


async def discover_contributors(
    lens: LensClient, pm_db: AsyncSession
) -> list[DiscoveredContributor]:
    """Query Lens for all contributors, merge with PM role overrides."""
    lens_contributors = await lens.discover_contributors()

    contributors = [
        DiscoveredContributor(
            github_username=c.github_username,
            pr_count=c.pr_count,
            prs_merged=c.prs_merged,
            prs_open=c.prs_open,
            review_count=c.review_count,
            comment_count=c.comment_count,
            last_activity=str(c.last_active) if c.last_active else None,
            merge_tier=c.merge_tier,
            pr_tier=c.pr_tier,
            review_tier=c.review_tier,
        )
        for c in lens_contributors
    ]

    # Merge with PM role overrides
    role_result = await pm_db.execute(select(Contributor))
    role_map = {c.github_username: c.role for c in role_result.scalars().all()}

    for dc in contributors:
        if dc.github_username in role_map:
            dc.role = role_map[dc.github_username]

    # Sort by total activity descending
    return sorted(contributors, key=lambda c: c.total_activity, reverse=True)


async def update_contributor_role(
    pm_db: AsyncSession, github_username: str, role: str | None
) -> Contributor | None:
    """Update a contributor's role override."""
    result = await pm_db.execute(
        select(Contributor).where(Contributor.github_username == github_username)
    )
    contributor = result.scalar_one_or_none()
    if contributor:
        contributor.role = role if role else None
        await pm_db.commit()
        await pm_db.refresh(contributor)
    return contributor
