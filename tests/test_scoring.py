"""Scoring edge cases: derived standing with zero, hostile, and flipping records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fg_agent_knowledge import Scope, build_claim, build_endorsement, confidence
from fg_agent_knowledge.scoring import (
    DEFAULT_STALENESS_HORIZON_SECONDS,
    contradictors,
    corroborators,
    freshness_damping,
    is_suspect,
    staleness_seconds,
)
from fg_agent_knowledge.types import ArtifactRef

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _claim(keys, refs=()):
    return build_claim(keys, Scope(space="s"), "semantic",
                       "cache warms slowly on mondays", topics=("cache",),
                       refs=refs, asserted_at=T0)


def test_zero_endorsements_is_base_prior():
    assert confidence(0, 0) == 0.5


def test_corroboration_raises_and_contradiction_outweighs():
    assert confidence(1, 0) > 0.5
    assert confidence(1, 1) < 0.5  # k=2: one contradiction beats one corroboration
    assert confidence(0, 3) < confidence(0, 1)


def test_contradiction_only_drops_toward_zero():
    assert confidence(0, 1) == 0.25
    assert 0 < confidence(0, 10) < 0.05


def test_latest_position_wins_per_identity(agent_a, agent_b):
    claim = _claim(agent_a)
    flip = [
        build_endorsement(agent_b, claim.claim_id, "contradict", issued_at=T0 + timedelta(days=1)),
        build_endorsement(agent_b, claim.claim_id, "corroborate", issued_at=T0 + timedelta(days=2)),
    ]
    assert corroborators(flip) == {flip[1].body.author}
    assert contradictors(flip) == set()


def test_self_corroboration_never_stacks(agent_a):
    claim = _claim(agent_a)
    es = [build_endorsement(agent_a, claim.claim_id, "corroborate",
                            issued_at=T0 + timedelta(days=i)) for i in (1, 2, 3)]
    assert len(corroborators(es)) == 1


def test_staleness_counts_from_assertion_and_resets_on_corroboration(agent_a, agent_b):
    claim = _claim(agent_a)
    now = T0 + timedelta(days=10)
    assert staleness_seconds(claim, [], now) == 10 * 86400
    fresh = build_endorsement(agent_b, claim.claim_id, "corroborate",
                              issued_at=T0 + timedelta(days=9))
    assert staleness_seconds(claim, [fresh], now) == 86400


def test_contradiction_does_not_touch_staleness(agent_a, agent_b):
    claim = _claim(agent_a)
    now = T0 + timedelta(days=10)
    dispute = build_endorsement(agent_b, claim.claim_id, "contradict",
                                issued_at=T0 + timedelta(days=9))
    assert staleness_seconds(claim, [dispute], now) == 10 * 86400


def test_suspect_flips_on_change_and_clears_on_corroboration(agent_a, agent_b):
    ref = ArtifactRef(uri="repo://a/b")
    claim = _claim(agent_a, refs=(ref,))
    changed = {ref.uri: T0 + timedelta(days=1)}
    assert is_suspect(claim, [], changed)
    recheck = build_endorsement(agent_b, claim.claim_id, "corroborate",
                                issued_at=T0 + timedelta(days=2))
    assert not is_suspect(claim, [recheck], changed)


def test_suspect_ignores_unrelated_artifacts(agent_a):
    claim = _claim(agent_a, refs=(ArtifactRef(uri="repo://a/b"),))
    assert not is_suspect(claim, [], {"repo://other": T0 + timedelta(days=1)})


def test_keyword_retriever_relevance(agent_a):
    """Relevance now lives in the retriever (BM25 over stemmed tokens)."""
    from fg_agent_knowledge import KeywordRetriever, RetrievalQuery

    claim = _claim(agent_a)
    r = KeywordRetriever()
    hit = r.rank(RetrievalQuery(task="why is the cache slow"), [claim])
    assert hit.scores.get(claim.claim_id, 0.0) > 0
    miss = r.rank(RetrievalQuery(task="kubernetes ingress"), [claim])
    assert claim.claim_id not in miss.scores
    empty = r.rank(RetrievalQuery(task=""), [claim])
    assert empty.query_empty and not empty.scores


def test_freshness_damping_halves_at_horizon():
    assert freshness_damping(0, DEFAULT_STALENESS_HORIZON_SECONDS) == 1.0
    assert freshness_damping(DEFAULT_STALENESS_HORIZON_SECONDS,
                             DEFAULT_STALENESS_HORIZON_SECONDS) == 0.5
