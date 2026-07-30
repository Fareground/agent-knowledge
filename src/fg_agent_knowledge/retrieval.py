"""Briefing assembly: deterministic, model-free ranking.

A briefing is assembled, never generated — ranked, attributed claims with
their standing visible. Retired and superseded claims never appear; actively
contradicted claims appear WITH their contradictions, never hidden. Claims
fall out of briefings by rank; only governance retires them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .retrievers import KeywordRetriever, RetrievalQuery, Retriever
from .scoring import (
    DEFAULT_BRIEFING_LIMIT,
    DEFAULT_STALENESS_HORIZON_SECONDS,
    SourceWeight,
    briefing_score,
    confidence,
    contradictors,
    corroborators,
    is_suspect,
    staleness_seconds,
    weighted_support,
)
from .store import Store
from .types import ArtifactRef, Briefing, BriefingItem, Claim, Scope

_DEFAULT_RETRIEVER = KeywordRetriever()


def eligible_claims(store: Store, scope: Scope) -> list[Claim]:
    """Accepted, unretired, unsuperseded claims visible from ``scope``.

    A claim is visible when its segment is the scope's segment or ``None``
    (space-wide knowledge narrows into every segment). Queries never cross
    ``space`` — the store is only ever asked for one space.
    """
    accepted = {
        p.claim.claim_id for p in store.promotions(scope.space, status="accepted")
    }
    claims = [c for c in store.claims(scope.space) if c.claim_id in accepted]
    superseded = {c.body.supersedes for c in claims if c.body.supersedes}
    return [
        c for c in claims
        if c.claim_id not in superseded
        and store.retirement(c.claim_id) is None
        and (c.body.scope.segment is None or c.body.scope.segment == scope.segment)
    ]


def brief(
    store: Store,
    scope: Scope,
    task: str,
    topics: tuple[str, ...] = (),
    refs: tuple[ArtifactRef, ...] = (),
    limit: int = DEFAULT_BRIEFING_LIMIT,
    now: datetime | None = None,
    retriever: Retriever | None = None,
    source_weight: SourceWeight | None = None,
) -> Briefing:
    """Assemble a briefing for ``task`` in ``scope``.

    The ``retriever`` supplies *relevance* (how well each claim matches the
    task); the core owns *trust* and assembly. Rank = relevance (refs overlap
    is a strong boost) × confidence × freshness damping. ``verify_first`` flags
    claims that made the briefing but are suspect or stale beyond the scope's
    horizon — read them as "check before you lean on this".

    ``source_weight`` is the optional trust seam: a callable mapping an author
    address to a non-negative weight. Without it every distinct identity is one
    equal vote (the standard's default); with it, corroborations and
    contradictions are weighted by source before confidence is computed — the
    injection point for reputation/stake-based sybil resistance a consumer
    supplies from outside the wire standard.
    """
    now = now if now is not None else datetime.now(UTC)
    retriever = retriever if retriever is not None else _DEFAULT_RETRIEVER
    policy = store.policy(scope)
    horizon = (
        policy.staleness_horizon_seconds
        if policy is not None and policy.staleness_horizon_seconds is not None
        else DEFAULT_STALENESS_HORIZON_SECONDS
    )
    ref_uris = {r.uri for r in refs}
    invalidations = store.invalidations(scope.space)

    eligible = eligible_claims(store, scope)
    ranking = retriever.rank(RetrievalQuery(task=task, topics=topics), eligible)
    # "List everything" — no lexical query and no refs — ranks by trust alone.
    list_all = ranking.query_empty and not ref_uris

    # Batch every eligible claim's endorsements in one call — a briefing over
    # N claims used to fire N separate endorsement queries (the read-path N+1).
    endorsements_by_claim = store.endorsements_for(c.claim_id for c in eligible)

    items: list[BriefingItem] = []
    conflicts: list[str] = []
    for claim in eligible:
        ref_overlap = bool(ref_uris & {r.uri for r in claim.body.refs})
        relevance = ranking.scores.get(claim.claim_id, 0.0)
        if list_all:
            relevance = 1.0
        elif relevance == 0.0 and not ref_overlap:
            continue  # nothing lexical matched and it isn't about a query ref
        endorsements = endorsements_by_claim.get(claim.claim_id, [])
        c, d = len(corroborators(endorsements)), len(contradictors(endorsements))
        corr_w, contra_w = weighted_support(endorsements, source_weight)
        conf = confidence(corr_w, contra_w)
        staleness = staleness_seconds(claim, endorsements, now)
        suspect = is_suspect(claim, endorsements, invalidations)
        score = briefing_score(relevance, ref_overlap, conf, staleness, horizon)
        if d > 0:
            conflicts.append(claim.claim_id)
        items.append(BriefingItem(
            claim=claim, confidence=conf, staleness_seconds=staleness,
            suspect=suspect, corroborations=c, contradictions=d, score=score,
            verify_first=suspect or staleness > horizon,
        ))

    items.sort(key=lambda i: (-i.score, i.claim.claim_id))
    top = tuple(items[:limit])
    top_ids = {i.claim.claim_id for i in top}
    return Briefing(
        items=top,
        conflicts=tuple(sorted(c for c in conflicts if c in top_ids)),
    )
