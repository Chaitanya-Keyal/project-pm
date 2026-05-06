"""Discover contributors from Lens data and manage PM contributor records."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from project_lens import LensClient

from project_pm.models.contributor import Contributor


# Repos that count as "in scope" for the SeedSigner contributor ranking.
# Contributors whose `repos_active` does not intersect this set are filtered
# out of the ranked list (e.g. embit-only contributors). This keeps the lens
# DB unfiltered so other consumers can still see ecosystem-wide activity,
# while project-pm's view stays scoped to SeedSigner contributors.
#
# Lens stores `repos_active` entries as `owner/name` (matching the values on
# GitCommit.repo / GithubPR.repo), so this set must use the full-name form.
SEEDSIGNER_SCOPE_REPOS = {
    "SeedSigner/seedsigner",
    "SeedSigner/seedsigner-os",
    "SeedSigner/seedsigner-emulator",
    "SeedSigner/seedsigner-translations",
    "SeedSigner/seedsigner-settings-generator",
    "SeedSigner/independent_custody_guide",
    "SeedSigner/hardware",
}


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
    total_tier: str = "none"
    group_tier: str = "none"
    total_activity: int = 0


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
            total_tier=c.total_tier,
            group_tier=c.group_tier,
            total_activity=c.total_activity,
        )
        for c in lens_contributors
    ]

    # Filter to contributors whose `repos_active` intersects with the
    # SeedSigner scope set. This drops e.g. embit-only contributors so
    # the ranked list stays scoped to "SeedSigner contributors". If a
    # contributor has no profile (no `repos_active` available), keep them
    # — fail-open so we don't drop legitimate contributors on missing data.
    profiles = await lens.list_contributor_profiles()
    profile_map = {p.github_login: p for p in profiles}

    def _in_scope(dc: DiscoveredContributor) -> bool:
        profile = profile_map.get(dc.github_username)
        if profile is None:
            return True
        repos_active = profile.stats.get("repos_active") or []
        if not repos_active:
            return True
        return bool(set(repos_active) & SEEDSIGNER_SCOPE_REPOS)

    contributors = [c for c in contributors if _in_scope(c)]

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
