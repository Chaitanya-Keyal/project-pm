"""Build per-person board data from Lens PR assessments + PM task actions."""

from dataclasses import dataclass, field
from datetime import datetime

from project_lens import LensClient, PRDetail as LensPRDetail, PRWithAssessment

from project_pm.models.contributor import Contributor


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
class DetailView:
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

    # Lens fields (open PRs only)
    pending_actions: dict | None = None
    pending_actions_updated_at: datetime | None = None
    merge_readiness: str | None = None
    merge_readiness_rationale: str | None = None
    reviewer_sentiment: list | None = None
    stale_reason: str | None = None

    # Rich fields
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


def _to_board_item(pr: PRWithAssessment) -> BoardItem:
    """Convert a Lens PRWithAssessment to a PM BoardItem."""
    participants = []
    if pr.participant_contributions:
        for p in pr.participant_contributions:
            un = p.get("github_username") if isinstance(p, dict) else None
            if un:
                participants.append(un)

    category = None
    if pr.outcome and isinstance(pr.outcome, dict):
        category = pr.outcome.get("category")

    return BoardItem(
        repo=pr.repo,
        number=pr.number,
        title=pr.title,
        author=pr.author,
        state=pr.state,
        tier=pr.tier or 0,
        complexity=pr.complexity or "",
        risk=pr.risk or "",
        summary=pr.summary or "",
        recommendation=pr.recommendation or "",
        review_state=pr.review_state,
        participant_usernames=participants,
        category=category,
    )


async def build_board(lens: LensClient, contributor: Contributor) -> Board:
    """Assemble a contributor's board from Lens data and PM task state."""
    board = Board(contributor=contributor)
    username = contributor.github_username
    role = contributor.role

    open_prs = await lens.get_open_prs_with_assessments()

    for pr in open_prs:
        item = _to_board_item(pr)
        if _is_suggestion_for(item, username, role):
            board.suggestions.append(item)

    return board


async def build_pr_detail(
    lens: LensClient,
    repo: str,
    number: int,
    contributor: Contributor | None = None,
) -> DetailView | None:
    """Fetch full PR detail from Lens, optionally personalized to a viewer."""
    pr = await lens.get_pr_detail(repo, number)
    if not pr:
        return None

    raw_reviews = pr.raw_reviews or []
    raw_review_comments = pr.raw_review_comments or []
    raw_issue_comments = pr.raw_issue_comments or []
    participant_contributions = pr.participant_contributions or []

    # Count unique reviewers
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

    # Unique commits referenced in review comments
    commit_shas = {
        r.get("commit_id")
        for r in raw_review_comments
        if isinstance(r, dict) and r.get("commit_id")
    }

    # Viewer-specific actions (only when viewing from a board)
    viewer_actions = None
    if contributor and pr.pending_actions and isinstance(pr.pending_actions, dict):
        viewer_actions = pr.pending_actions.get(contributor.github_username)

    return DetailView(
        repo=pr.repo,
        number=pr.number,
        title=pr.title,
        author=pr.author,
        state=pr.state,
        review_state=pr.review_state,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        diff_size=pr.diff_size,
        tier=pr.tier or 0,
        complexity=pr.complexity or "",
        risk=pr.risk or "",
        summary=pr.summary or "",
        recommendation=pr.recommendation or "",
        pending_actions=pr.pending_actions,
        pending_actions_updated_at=pr.pending_actions_updated_at,
        merge_readiness=pr.merge_readiness,
        merge_readiness_rationale=pr.merge_readiness_rationale,
        reviewer_sentiment=pr.reviewer_sentiment,
        stale_reason=pr.stale_reason,
        participant_contributions=participant_contributions,
        cross_references=pr.cross_references,
        reviews=pr.reviews,
        outcome=pr.outcome,
        num_participants=len(participant_contributions),
        num_reviews=len(reviewer_users),
        num_review_comments=len(raw_review_comments),
        num_comments=len(raw_issue_comments),
        num_commits=len(commit_shas),
        viewer_actions=viewer_actions,
    )


def _is_suggestion_for(item: BoardItem, username: str, role: str | None) -> bool:
    """Determine if this PR should be suggested to this contributor."""
    is_own_pr = item.author == username
    is_participant = username in item.participant_usernames

    if role == "lead_maintainer":
        return not is_own_pr and item.tier >= 1
    elif role == "lead_dev":
        return not is_own_pr and item.tier >= 1
    else:
        if is_own_pr:
            return True
        if is_participant:
            return True
        return item.tier <= 1
