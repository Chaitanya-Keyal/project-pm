"""Build per-person board data from Lens PR assessments + PM task actions."""

import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.contributor import Contributor


TIER_LABELS = {0: "Trivial", 1: "Straightforward", 2: "Significant", 3: "Complex"}

MERGE_READINESS_LABELS = {
    "not_ready": "Not Ready",
    "possibly_ready": "Possibly Ready",
    "merge_ready": "Merge Ready",
}

MERGE_READINESS_CLASSES = {
    "not_ready": "danger",
    "possibly_ready": "warning",
    "merge_ready": "success",
}

STALE_REASON_LABELS = {
    "neglected": "Neglected — no reviewer engagement",
    "indecisive": "Indecisive — active discussion but no convergence",
    "soft_rejected": "Soft rejected — minimal engagement, likely dying by neglect",
}


@dataclass
class BoardItem:
    """A single item on the board (PR, issue, etc.)."""

    repo: str
    number: int
    title: str
    author: str
    state: str
    tier: int
    complexity: str
    risk: str
    summary: str
    recommendation: str
    review_state: str | None = None
    participant_usernames: list[str] = field(default_factory=list)
    category: str | None = None

    @property
    def source_ref(self) -> str:
        return f"{self.repo}#PR{self.number}"

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.repo}/pull/{self.number}"

    @property
    def short_repo(self) -> str:
        return self.repo.split("/")[-1] if "/" in self.repo else self.repo

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, "Unknown")

    @property
    def risk_class(self) -> str:
        return {"low": "success", "medium": "warning", "high": "danger"}.get(
            self.risk, ""
        )



@dataclass
class PRDetail:
    """Full detail view of a single PR, personalized to the viewer."""

    # Basic PR info
    repo: str
    number: int
    title: str
    author: str
    state: str
    review_state: str | None
    created_at: datetime | None
    updated_at: datetime | None
    diff_size: int | None

    # Assessment
    tier: int
    complexity: str
    risk: str
    summary: str
    recommendation: str

    # New Lens fields (open PRs only)
    pending_actions: dict | None = None
    pending_actions_updated_at: datetime | None = None
    merge_readiness: str | None = None
    merge_readiness_rationale: str | None = None
    reviewer_sentiment: list | None = None
    stale_reason: str | None = None

    # Existing rich fields
    participant_contributions: list | None = None
    cross_references: list | None = None
    reviews: list | None = None
    outcome: dict | None = None

    # Stats (computed from raw GitHub data)
    num_participants: int = 0
    num_reviews: int = 0
    num_review_comments: int = 0
    num_comments: int = 0
    num_commits: int = 0

    # Computed: viewer-specific
    viewer_actions: dict | None = None

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.repo}/pull/{self.number}"

    @property
    def short_repo(self) -> str:
        return self.repo.split("/")[-1] if "/" in self.repo else self.repo

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, "Unknown")

    @property
    def risk_class(self) -> str:
        return {"low": "success", "medium": "warning", "high": "danger"}.get(
            self.risk, ""
        )

    @property
    def merge_readiness_label(self) -> str:
        return MERGE_READINESS_LABELS.get(self.merge_readiness or "", "")

    @property
    def merge_readiness_class(self) -> str:
        return MERGE_READINESS_CLASSES.get(self.merge_readiness or "", "")

    @property
    def stale_reason_label(self) -> str:
        return STALE_REASON_LABELS.get(self.stale_reason or "", "")

    @property
    def has_viewer_actions(self) -> bool:
        return bool(
            self.viewer_actions and self.viewer_actions.get("open_items", 0) > 0
        )


@dataclass
class Board:
    """The complete board state for a contributor."""

    contributor: Contributor
    action_needed: list[BoardItem] = field(default_factory=list)
    watching: list[BoardItem] = field(default_factory=list)
    suggestions: list[BoardItem] = field(default_factory=list)


async def build_board(
    lens_db: AsyncSession,
    pm_db: AsyncSession,
    contributor: Contributor,
) -> Board:
    """Assemble a contributor's board from Lens data and PM task state."""

    board = Board(contributor=contributor)

    # Get all open PRs with assessments
    result = await lens_db.execute(text("""
        SELECT p.repo, p.number, p.title, p.author, p.state, p.review_state,
               a.tier, a.complexity, a.risk, a.summary, a.recommendation,
               a.participant_contributions, a.outcome
        FROM github_prs p
        JOIN pr_assessments a ON p.repo = a.repo AND p.number = a.pr_number
        WHERE p.state = 'open'
        ORDER BY a.tier DESC, p.updated_at_gh DESC
    """))

    username = contributor.github_username
    role = contributor.role

    for row in result.fetchall():
        (
            repo,
            number,
            title,
            author,
            state,
            review_state,
            tier,
            complexity,
            risk,
            summary,
            recommendation,
            participant_contributions_json,
            outcome_json,
        ) = row

        # Parse participants
        participants = []
        if participant_contributions_json:
            for p in json.loads(participant_contributions_json):
                un = p.get("github_username")
                if un:
                    participants.append(un)

        # Parse outcome category
        category = None
        if outcome_json:
            outcome = json.loads(outcome_json)
            category = outcome.get("category")

        item = BoardItem(
            repo=repo,
            number=number,
            title=title,
            author=author,
            state=state,
            tier=tier,
            complexity=complexity,
            risk=risk,
            summary=summary,
            recommendation=recommendation,
            review_state=review_state,
            participant_usernames=participants,
            category=category,
        )

        # Route to the right board section based on role and relevance
        if _is_suggestion_for(item, username, role):
            board.suggestions.append(item)

    return board


def _parse_json(raw: str | None) -> dict | list | None:
    """Parse a JSON string, returning None if empty or invalid."""
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


async def build_pr_detail(
    lens_db: AsyncSession,
    contributor: Contributor,
    repo: str,
    number: int,
) -> PRDetail | None:
    """Fetch full PR detail from Lens, personalized to the viewer."""

    result = await lens_db.execute(
        text("""
        SELECT p.repo, p.number, p.title, p.author, p.state, p.review_state,
               p.created_at_gh, p.updated_at_gh, p.diff_size,
               a.tier, a.complexity, a.risk, a.summary, a.recommendation,
               a.participant_contributions, a.outcome, a.reviews,
               a.pending_actions, a.pending_actions_updated_at,
               a.merge_readiness, a.merge_readiness_rationale,
               a.reviewer_sentiment, a.stale_reason,
               a.cross_references,
               p.reviews_json, p.review_comments_json, p.issue_comments_json
        FROM github_prs p
        JOIN pr_assessments a ON p.repo = a.repo AND p.number = a.pr_number
        WHERE p.repo = :repo AND p.number = :number
    """),
        {"repo": repo, "number": number},
    )

    row = result.fetchone()
    if not row:
        return None

    (
        repo_val,
        number_val,
        title,
        author,
        state,
        review_state,
        created_at,
        updated_at,
        diff_size,
        tier,
        complexity,
        risk,
        summary,
        recommendation,
        participant_contributions_json,
        outcome_json,
        reviews_json,
        pending_actions_json,
        pending_actions_updated_at,
        merge_readiness,
        merge_readiness_rationale,
        reviewer_sentiment_json,
        stale_reason,
        cross_references_json,
        raw_reviews_json,
        raw_review_comments_json,
        raw_issue_comments_json,
    ) = row

    # Compute stats from raw GitHub data
    raw_reviews = _parse_json(raw_reviews_json) or []
    raw_review_comments = _parse_json(raw_review_comments_json) or []
    raw_issue_comments = _parse_json(raw_issue_comments_json) or []
    participant_contributions = _parse_json(participant_contributions_json) or []

    # Count unique reviewers (distinct users who submitted reviews)
    reviewer_users = set()
    for r in raw_reviews:
        if not isinstance(r, dict):
            continue
        user = r.get("user")
        if isinstance(user, dict):
            login = user.get("login", "")
        elif isinstance(user, str):
            login = user
        else:
            continue
        if login:
            reviewer_users.add(login)
    num_reviews = len(reviewer_users)

    # Unique commits referenced in reviews
    commit_shas = {r.get("commit_id") for r in raw_review_comments if isinstance(r, dict) and r.get("commit_id")}

    pending_actions = _parse_json(pending_actions_json)
    viewer_actions = None
    if pending_actions and isinstance(pending_actions, dict):
        viewer_actions = pending_actions.get(contributor.github_username)

    return PRDetail(
        repo=repo_val,
        number=number_val,
        title=title,
        author=author,
        state=state,
        review_state=review_state,
        created_at=created_at,
        updated_at=updated_at,
        diff_size=diff_size,
        tier=tier or 0,
        complexity=complexity or "",
        risk=risk or "",
        summary=summary or "",
        recommendation=recommendation or "",
        pending_actions=pending_actions,
        pending_actions_updated_at=pending_actions_updated_at,
        merge_readiness=merge_readiness,
        merge_readiness_rationale=merge_readiness_rationale,
        reviewer_sentiment=_parse_json(reviewer_sentiment_json),
        stale_reason=stale_reason,
        participant_contributions=participant_contributions,
        cross_references=_parse_json(cross_references_json),
        reviews=_parse_json(reviews_json),
        outcome=_parse_json(outcome_json),
        num_participants=len(participant_contributions),
        num_reviews=num_reviews,
        num_review_comments=len(raw_review_comments),
        num_comments=len(raw_issue_comments),
        num_commits=len(commit_shas),
        viewer_actions=viewer_actions,
    )


def _is_suggestion_for(item: BoardItem, username: str, role: str | None) -> bool:
    """Determine if this PR should be suggested to this contributor."""

    # Don't suggest your own PRs (those go in a different section later)
    is_own_pr = item.author == username
    is_participant = username in item.participant_usernames

    if role == "lead_maintainer":
        # Maintainer sees PRs ready for merge decision (reviewed, not their own)
        # For now: all open PRs tier 1+ that aren't theirs
        return not is_own_pr and item.tier >= 1

    elif role == "lead_dev":
        # Lead dev sees PRs needing direction, coordination, triage
        # For now: all open PRs tier 1+ that aren't theirs
        return not is_own_pr and item.tier >= 1

    else:
        # Regular contributors see:
        # 1. Their own open PRs (always relevant)
        # 2. PRs they could review (matched by complexity to their level)
        if is_own_pr:
            return True
        # Suggest tier 0-1 PRs for review to newer contributors
        # Suggest up to tier 2 for those already participating
        if is_participant:
            return True
        return item.tier <= 1
