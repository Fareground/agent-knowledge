"""The blueprint's end-to-end scenario: two agents + one human key, over both
stores. Every step of acceptance criterion 2, plus the kb-level negative paths."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fg_agent_knowledge import (
    ArtifactRef,
    NotFoundError,
    Policy,
    Scope,
    ScopeError,
    ValidationError,
)

SCOPE = Scope(space="ws-1")
OTHER_SPACE = Scope(space="ws-2")
PAST = datetime.now(UTC) - timedelta(days=30)


def test_full_lifecycle(kb, agent_a, agent_b, human):
    kb.set_policy(SCOPE, Policy(mode="auto", protected_topics=("security",)))

    # observe → propose (auto scope) → brief serves it
    ep = kb.observe(SCOPE, agent_a, "observation", "deploy fails without warm cache")
    promo = kb.propose(
        SCOPE, agent_a, "procedural", "warm the cache before deploying pricing",
        topics=("deploy", "pricing"), episodes=(ep.id,),
        refs=(ArtifactRef(uri="repo://pricing/deploy.sh"),), asserted_at=PAST,
    )
    assert promo.status == "accepted"
    briefing = kb.brief(SCOPE, task="deploying the pricing service")
    assert [i.claim.claim_id for i in briefing.items] == [promo.claim.claim_id]

    # propose into protected topic → pending → review → accepted
    guarded = kb.propose(SCOPE, agent_b, "semantic",
                         "tokens rotate every ninety days", topics=("security",))
    assert guarded.status == "pending"
    assert kb.brief(SCOPE, task="rotate tokens").items == ()
    guarded = kb.review(guarded.id, human, "approve", basis="confirmed with ops")
    assert guarded.status == "accepted"
    assert kb.brief(SCOPE, task="rotate tokens").items[0].claim.claim_id == guarded.claim.claim_id

    # contradiction lowers confidence and surfaces in the briefing
    claim_id = promo.claim.claim_id
    base = kb.brief(SCOPE, task="deploying pricing").items[0]
    kb.endorse(claim_id, agent_b, "contradict", basis="cold deploys fine now")
    disputed = kb.brief(SCOPE, task="deploying pricing").items[0]
    assert disputed.confidence < base.confidence
    assert disputed.contradictions == 1
    assert claim_id in kb.brief(SCOPE, task="deploying pricing").conflicts

    # corroboration resets staleness (and outvotes the contradiction)
    assert disputed.staleness_seconds > 86400
    kb.endorse(claim_id, human, "corroborate", basis="still true on staging")
    kb.endorse(claim_id, agent_a, "corroborate", basis="re-encountered today")
    fresh = kb.brief(SCOPE, task="deploying pricing").items[0]
    assert fresh.staleness_seconds < 3600
    assert fresh.corroborations == 2

    # artifact invalidation flips suspect and verify_first
    changed_at = datetime.now(UTC) + timedelta(minutes=1)
    affected = kb.invalidate(SCOPE, "repo://pricing/deploy.sh", changed_at)
    assert affected == [claim_id]
    flagged = kb.brief(SCOPE, task="deploying pricing").items[0]
    assert flagged.suspect and flagged.verify_first
    kb.endorse(claim_id, agent_b, "corroborate", basis="re-read the new script",
               issued_at=changed_at + timedelta(minutes=1))
    assert not kb.brief(SCOPE, task="deploying pricing").items[0].suspect

    # supersedes chain hides the old claim from briefings
    revision = kb.propose(
        SCOPE, agent_a, "procedural", "warm the cache and drain connections before deploying pricing",
        topics=("deploy", "pricing"), supersedes=claim_id,
    )
    ids = [i.claim.claim_id for i in kb.brief(SCOPE, task="deploying pricing").items]
    assert revision.claim.claim_id in ids and claim_id not in ids

    # retirement removes from briefings but not from the store
    kb.retire(revision.claim.claim_id, agent_a, reason="pipeline rebuilt")
    assert kb.brief(SCOPE, task="deploying pricing").items == ()
    assert kb.claim(revision.claim.claim_id).body.statement.startswith("warm the cache and")


def test_conflict_event_emitted_on_pileup(kb, agent_a, agent_b, human):
    promo = kb.propose(SCOPE, agent_a, "semantic", "the api is rate limited at ten rps")
    claim_id = promo.claim.claim_id
    kb.endorse(claim_id, agent_b, "contradict", basis="saw a hundred rps")
    assert kb.conflicts(SCOPE) == []
    kb.endorse(claim_id, human, "contradict", basis="docs say fifty")
    events = kb.conflicts(SCOPE)
    assert len(events) == 1 and events[0].claim_id == claim_id
    assert events[0].contradictions == 2


def test_cross_space_episode_refs_rejected(kb, agent_a):
    foreign = kb.observe(OTHER_SPACE, agent_a, "observation", "seen elsewhere")
    with pytest.raises(ScopeError):
        kb.propose(SCOPE, agent_a, "semantic", "leaks across spaces",
                   episodes=(foreign.id,))
    promo = kb.propose(SCOPE, agent_a, "semantic", "endorsable")
    with pytest.raises(ScopeError):
        kb.endorse(promo.claim.claim_id, agent_a, "corroborate", episodes=(foreign.id,))


def test_unknown_episode_rejected(kb, agent_a):
    with pytest.raises(NotFoundError):
        kb.propose(SCOPE, agent_a, "semantic", "built on nothing",
                   episodes=("not-an-episode",))


def test_cross_space_supersedes_rejected(kb, agent_a):
    foreign = kb.propose(OTHER_SPACE, agent_a, "semantic", "belongs elsewhere")
    with pytest.raises(ScopeError):
        kb.propose(SCOPE, agent_a, "semantic", "replacement",
                   supersedes=foreign.claim.claim_id)


def test_queries_never_cross_space(kb, agent_a):
    kb.propose(OTHER_SPACE, agent_a, "semantic", "pricing deploys are manual")
    assert kb.brief(SCOPE, task="pricing deploys").items == ()
    assert kb.claims(SCOPE) == []


def test_float_in_signed_body_rejected(kb, agent_a):
    promo = kb.propose(SCOPE, agent_a, "semantic", "floats never reach the wire")
    with pytest.raises(ValidationError):
        kb.endorse(promo.claim.claim_id, agent_a, "corroborate", basis=0.9)  # type: ignore[arg-type]


def test_refs_boost_and_limit(kb, agent_a):
    ref = ArtifactRef(uri="repo://svc/main.py")
    for i in range(15):
        kb.propose(SCOPE, agent_a, "semantic", f"note number {i} about the service",
                   topics=(f"t{i}",))
    boosted = kb.propose(SCOPE, agent_a, "semantic", "main module reads env at import",
                         refs=(ref,))
    briefing = kb.brief(SCOPE, task="touching the service", refs=(ref,))
    assert briefing.items[0].claim.claim_id == boosted.claim.claim_id
    assert len(kb.brief(SCOPE, task="note about the service").items) <= 12


def test_source_weight_seam_reweights_confidence():
    """The optional trust seam: a consumer's per-source weights change how
    corroborations aggregate into confidence, without touching the wire."""
    from datetime import UTC, datetime

    from fg_agent_knowledge.scoring import confidence, weighted_support

    # Directly exercise the weighting math: two corroborators, one trusted 3x,
    # one distrusted 0x — weighted confidence must exceed the unweighted one
    # only via the trusted source, and a zero-weight source drops out.
    class _E:
        def __init__(self, author, verdict, t):
            self.body = type("B", (), {"author": author, "verdict": verdict, "issued_at": t})()

    now = datetime(2026, 1, 1, tzinfo=UTC)
    ends = [_E("alice", "corroborate", now), _E("bob", "corroborate", now)]
    # Uniform: 2 corroborations.
    assert weighted_support(ends) == (2.0, 0.0)
    # Weighted: alice trusted 3, bob distrusted 0 -> corroboration weight 3.
    weight = {"alice": 3.0, "bob": 0.0}
    corr, contra = weighted_support(ends, lambda a: weight[a])
    assert (corr, contra) == (3.0, 0.0)
    assert confidence(corr, contra) > confidence(2.0, 0.0)
