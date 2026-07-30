"""Wire dataclasses for every record in the standard.

All records are frozen: a stored body is never mutated, revision is a new
record. Signed record types render themselves to a plain ``body()`` dict —
the exact structure the signature covers — with timestamps pinned to the
canonical RFC 3339 spelling so independent implementations agree
byte-for-byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fg_agent_id.serde import canonical_timestamp, normalize_timestamp

from .errors import ValidationError

SPEC = "fg-agent-knowledge/v1"

EpisodeKind = Literal["observation", "outcome", "correction", "surprise"]
ClaimKind = Literal["semantic", "procedural", "relational"]
EndorsementVerdict = Literal["corroborate", "contradict"]
ReviewDecision = Literal["approve", "reject"]
PromotionStatus = Literal["pending", "accepted", "rejected"]
PolicyMode = Literal["auto", "review"]

EPISODE_KINDS = ("observation", "outcome", "correction", "surprise")
CLAIM_KINDS = ("semantic", "procedural", "relational")
ENDORSEMENT_VERDICTS = ("corroborate", "contradict")
REVIEW_DECISIONS = ("approve", "reject")
POLICY_MODES = ("auto", "review")


def _require_choice(name: str, value: str, choices: tuple[str, ...]) -> str:
    if value not in choices:
        raise ValidationError(f"{name} must be one of {choices}, got {value!r}")
    return value


# Signed bodies carry free text (statement, basis, reason, episode content).
# Bounding it keeps a single record from bloating the signing input, the DB,
# and the FTS index — an unauthenticated amplification vector otherwise.
MAX_TEXT_BYTES = 65_536


def _require_str(name: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"{name} must be a non-empty string")
    return _bound_text(name, value)


def _bound_text(name: str, value: str) -> str:
    """Cap a text field's size. Applies to optional (possibly empty) fields
    like ``basis`` that skip the non-empty check but must still be bounded."""
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValidationError(f"{name} exceeds {MAX_TEXT_BYTES} bytes")
    return value


@dataclass(frozen=True)
class Scope:
    """Where knowledge lives. ``space`` is the hard boundary (queries never
    cross it); ``segment`` optionally narrows within it. Both are opaque to
    the library — consumers enforce access control."""

    space: str
    segment: str | None = None

    def __post_init__(self) -> None:
        _require_str("scope.space", self.space)
        if self.segment is not None:
            _require_str("scope.segment", self.segment)

    def body(self) -> dict:
        return {"space": self.space, "segment": self.segment}


@dataclass(frozen=True)
class ArtifactRef:
    """A pointer to something a record is *about* — the invalidation hook.
    ``uri`` is opaque; equality of uris is the only semantics the standard
    assigns."""

    uri: str
    kind: str | None = None

    def __post_init__(self) -> None:
        _require_str("ref.uri", self.uri)

    def body(self) -> dict:
        return {"uri": self.uri, "kind": self.kind}


@dataclass(frozen=True)
class Episode:
    """A cheap, unsigned, append-only observation — fuel for consolidation,
    never directly retrieved by briefings."""

    id: str
    scope: Scope
    observer: str
    kind: EpisodeKind
    content: str
    occurred_at: datetime
    refs: tuple[ArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        _require_choice("episode.kind", self.kind, EPISODE_KINDS)
        _require_str("episode.observer", self.observer)
        _require_str("episode.content", self.content)
        object.__setattr__(
            self, "occurred_at", normalize_timestamp("occurred_at", self.occurred_at)
        )


@dataclass(frozen=True)
class ClaimBody:
    """The signed payload of a claim — the unit of knowledge."""

    scope: Scope
    kind: ClaimKind
    statement: str
    topics: tuple[str, ...]
    refs: tuple[ArtifactRef, ...]
    episodes: tuple[str, ...]
    author: str
    asserted_at: datetime
    supersedes: str | None = None

    def __post_init__(self) -> None:
        _require_choice("claim.kind", self.kind, CLAIM_KINDS)
        _require_str("claim.statement", self.statement)
        _require_str("claim.author", self.author)
        normalized = tuple(sorted({t.lower() for t in self.topics if t}))
        object.__setattr__(self, "topics", normalized)
        object.__setattr__(
            self, "asserted_at", normalize_timestamp("asserted_at", self.asserted_at)
        )

    def body(self) -> dict:
        return {
            "spec": SPEC,
            "scope": self.scope.body(),
            "kind": self.kind,
            "statement": self.statement,
            "topics": list(self.topics),
            "refs": [r.body() for r in self.refs],
            "episodes": list(self.episodes),
            "author": self.author,
            "asserted_at": canonical_timestamp(self.asserted_at),
            "supersedes": self.supersedes,
        }


@dataclass(frozen=True)
class Claim:
    """A claim body plus its author's signature and derived content address."""

    body: ClaimBody
    signature: str
    claim_id: str


@dataclass(frozen=True)
class EndorsementBody:
    """The signed payload of a corroboration or contradiction."""

    claim_id: str
    verdict: EndorsementVerdict
    basis: str
    episodes: tuple[str, ...]
    author: str
    issued_at: datetime

    def __post_init__(self) -> None:
        _require_str("endorsement.claim_id", self.claim_id)
        _require_choice("endorsement.verdict", self.verdict, ENDORSEMENT_VERDICTS)
        _require_str("endorsement.author", self.author)
        _bound_text("endorsement.basis", self.basis)
        object.__setattr__(
            self, "issued_at", normalize_timestamp("issued_at", self.issued_at)
        )

    def body(self) -> dict:
        return {
            "spec": SPEC,
            "claim_id": self.claim_id,
            "verdict": self.verdict,
            "basis": self.basis,
            "episodes": list(self.episodes),
            "author": self.author,
            "issued_at": canonical_timestamp(self.issued_at),
        }


@dataclass(frozen=True)
class Endorsement:
    body: EndorsementBody
    signature: str


@dataclass(frozen=True)
class ReviewVerdictBody:
    """The signed payload of a promotion review."""

    promotion_id: str
    verdict: ReviewDecision
    basis: str
    author: str
    issued_at: datetime

    def __post_init__(self) -> None:
        _require_str("verdict.promotion_id", self.promotion_id)
        _require_choice("verdict.verdict", self.verdict, REVIEW_DECISIONS)
        _require_str("verdict.author", self.author)
        _bound_text("verdict.basis", self.basis)
        object.__setattr__(
            self, "issued_at", normalize_timestamp("issued_at", self.issued_at)
        )

    def body(self) -> dict:
        return {
            "spec": SPEC,
            "promotion_id": self.promotion_id,
            "verdict": self.verdict,
            "basis": self.basis,
            "author": self.author,
            "issued_at": canonical_timestamp(self.issued_at),
        }


@dataclass(frozen=True)
class ReviewVerdict:
    body: ReviewVerdictBody
    signature: str


@dataclass(frozen=True)
class RetirementBody:
    """The signed payload of a retirement — the ONLY way a claim leaves."""

    claim_id: str
    reason: str
    author: str
    issued_at: datetime

    def __post_init__(self) -> None:
        _require_str("retirement.claim_id", self.claim_id)
        _require_str("retirement.reason", self.reason)
        _require_str("retirement.author", self.author)
        object.__setattr__(
            self, "issued_at", normalize_timestamp("issued_at", self.issued_at)
        )

    def body(self) -> dict:
        return {
            "spec": SPEC,
            "claim_id": self.claim_id,
            "reason": self.reason,
            "author": self.author,
            "issued_at": canonical_timestamp(self.issued_at),
        }


@dataclass(frozen=True)
class Retirement:
    body: RetirementBody
    signature: str


@dataclass(frozen=True)
class Policy:
    """How promotions into a scope are decided. ``staleness_horizon_seconds``
    also feeds ``verify_first`` in briefings."""

    mode: PolicyMode = "auto"
    required_approvals: int = 1
    protected_topics: tuple[str, ...] = ()
    staleness_horizon_seconds: int | None = None

    def __post_init__(self) -> None:
        _require_choice("policy.mode", self.mode, POLICY_MODES)
        if self.required_approvals < 1:
            raise ValidationError("policy.required_approvals must be >= 1")
        object.__setattr__(
            self,
            "protected_topics",
            tuple(sorted({t.lower() for t in self.protected_topics if t})),
        )


@dataclass(frozen=True)
class Promotion:
    """A proposal to admit a claim into a scope. Append-only audit record;
    ``status`` moves pending → accepted | rejected exactly once."""

    id: str
    scope: Scope
    claim: Claim
    proposer: str
    status: PromotionStatus
    created_at: datetime
    decided_at: datetime | None = None


@dataclass(frozen=True)
class ConflictEvent:
    """Emitted when contradictions on a claim cross the threshold — a signal
    for humans, not an automatic action."""

    claim_id: str
    scope: Scope
    contradictions: int


@dataclass(frozen=True)
class BriefingItem:
    claim: Claim
    confidence: float
    staleness_seconds: int
    suspect: bool
    corroborations: int
    contradictions: int
    score: float
    verify_first: bool


@dataclass(frozen=True)
class Briefing:
    """An assembled (never generated) briefing: ranked, attributed claims."""

    items: tuple[BriefingItem, ...]
    conflicts: tuple[str, ...]
