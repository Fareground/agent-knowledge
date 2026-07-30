"""Pure scoring functions: confidence, staleness, suspect, briefing score.

Everything here is derived at read time from the endorsement record — nothing
is persisted as authoritative. Confidence and staleness are independent axes:
confidence asks "how sure are we this was ever true", staleness asks "how
long since anyone re-encountered it".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .types import Claim, Endorsement

# Optional per-source trust weight: a consumer with reputation/stake data maps
# an author address to a non-negative weight. Absent this seam, every distinct
# identity is one equal vote (weight 1.0) — the standard's default. This is the
# injection point for sybil resistance a wire standard cannot itself provide.
SourceWeight = Callable[[str], float]

# One contradiction outweighs one corroboration. This is the reference value;
# implementations may substitute — the FIELDS are the standard, not the number.
CONTRADICTION_WEIGHT = 2

# Default verify-first horizon when a scope's policy does not set one: a week.
DEFAULT_STALENESS_HORIZON_SECONDS = 7 * 24 * 3600

# Relevance bonus when a claim's refs overlap the task's refs — claims about
# the artifact you are touching outrank merely topical ones.
REF_OVERLAP_BONUS = 2.0

# Contradictions from this many distinct identities emit a ConflictEvent.
CONFLICT_CONTRADICTION_THRESHOLD = 2

DEFAULT_BRIEFING_LIMIT = 12


def latest_verdicts(endorsements: list[Endorsement]) -> dict[str, Endorsement]:
    """Each identity's standing position: its most recent endorsement.

    An identity that contradicted and later corroborated counts as a
    corroborator — positions supersede, they do not accumulate.
    """
    latest: dict[str, Endorsement] = {}
    for e in sorted(endorsements, key=lambda e: e.body.issued_at):
        latest[e.body.author] = e
    return latest


def corroborators(endorsements: list[Endorsement]) -> set[str]:
    return {
        a for a, e in latest_verdicts(endorsements).items()
        if e.body.verdict == "corroborate"
    }


def contradictors(endorsements: list[Endorsement]) -> set[str]:
    return {
        a for a, e in latest_verdicts(endorsements).items()
        if e.body.verdict == "contradict"
    }


def confidence(
    corroborations: float, contradictions: float, k: float = CONTRADICTION_WEIGHT
) -> float:
    """Reference confidence: ``(1 + c) / (2 + c + k*d)``.

    With no endorsements this is the base prior 0.5; corroborations pull it
    toward 1, contradictions (weighted) pull it toward 0. ``c`` and ``d`` are
    counts by default but may be summed source weights (see
    :func:`weighted_support`) so a consumer's per-source trust flows straight
    into the same formula.
    """
    return (1 + corroborations) / (2 + corroborations + k * contradictions)


def weighted_support(
    endorsements: list[Endorsement], source_weight: SourceWeight | None = None
) -> tuple[float, float]:
    """Return (corroboration weight, contradiction weight) over standing
    positions. With no ``source_weight`` every distinct identity contributes
    1.0, so the sums equal the corroborator/contradictor counts and confidence
    is unchanged. With one, each identity contributes its (clamped
    non-negative) weight — the seam for reputation/stake-weighted trust.
    """
    if source_weight is None:
        return float(len(corroborators(endorsements))), float(len(contradictors(endorsements)))
    corr = sum(max(0.0, source_weight(a)) for a in corroborators(endorsements))
    contra = sum(max(0.0, source_weight(a)) for a in contradictors(endorsements))
    return corr, contra


def last_corroborated_at(claim: Claim, endorsements: list[Endorsement]) -> datetime:
    """The last corroborating encounter; ``asserted_at`` counts as the first.

    Contradictions do not touch this — disputing a claim is not encountering
    it to be true.
    """
    times = [claim.body.asserted_at] + [
        e.body.issued_at for e in endorsements if e.body.verdict == "corroborate"
    ]
    return max(times)


def staleness_seconds(
    claim: Claim, endorsements: list[Endorsement], now: datetime
) -> int:
    """Whole seconds since the last corroborating encounter (never negative)."""
    delta = now - last_corroborated_at(claim, endorsements)
    return max(0, int(delta.total_seconds()))


def is_suspect(
    claim: Claim,
    endorsements: list[Endorsement],
    invalidations: dict[str, datetime],
) -> bool:
    """Provenance-linked invalidation: a claim goes suspect the moment any
    artifact it is about changes after the last corroboration. The next
    corroboration clears it — derived state needs no explicit reset."""
    anchor = last_corroborated_at(claim, endorsements)
    return any(
        changed_at > anchor
        for uri, changed_at in invalidations.items()
        if any(ref.uri == uri for ref in claim.body.refs)
    )


def freshness_damping(staleness: int, horizon_seconds: int) -> float:
    """Smoothly discounts stale claims: 1.0 when fresh, 0.5 at the horizon."""
    return horizon_seconds / (horizon_seconds + staleness)


def briefing_score(
    relevance: float,
    ref_overlap: bool,
    claim_confidence: float,
    staleness: int,
    horizon_seconds: int,
) -> float:
    """Deterministic, model-free rank: relevance (ref-boosted) × confidence ×
    freshness damping."""
    boosted = relevance + (REF_OVERLAP_BONUS if ref_overlap else 0.0)
    return boosted * claim_confidence * freshness_damping(staleness, horizon_seconds)
