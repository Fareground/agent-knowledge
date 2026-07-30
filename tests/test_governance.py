"""Governance state machine and its protocol rules, over both stores."""

from __future__ import annotations

import pytest

from fg_agent_knowledge import NotFoundError, Policy, PolicyError, Scope

SCOPE = Scope(space="team")


def test_auto_mode_accepts_immediately(kb, agent_a):
    promo = kb.propose(SCOPE, agent_a, "semantic", "sprints start on tuesdays")
    assert promo.status == "accepted"
    assert promo.decided_at is not None


def test_protected_topic_forces_review_in_auto_mode(kb, agent_a, human):
    kb.set_policy(SCOPE, Policy(mode="auto", protected_topics=("billing",)))
    promo = kb.propose(SCOPE, agent_a, "semantic", "invoices net-30",
                       topics=("Billing",))
    assert promo.status == "pending"
    decided = kb.review(promo.id, human, "approve")
    assert decided.status == "accepted"


def test_review_mode_needs_distinct_approvals(kb, agent_a, agent_b, human):
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=2))
    promo = kb.propose(SCOPE, agent_a, "semantic", "release fridays are banned")
    assert promo.status == "pending"
    promo = kb.review(promo.id, agent_b, "approve")
    assert promo.status == "pending"
    promo = kb.review(promo.id, human, "approve")
    assert promo.status == "accepted"


def test_any_reject_rejects(kb, agent_a, agent_b):
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=2))
    promo = kb.propose(SCOPE, agent_a, "semantic", "we support ie11")
    promo = kb.review(promo.id, agent_b, "reject", basis="we do not")
    assert promo.status == "rejected"


def test_self_review_rejected(kb, agent_a):
    kb.set_policy(SCOPE, Policy(mode="review"))
    promo = kb.propose(SCOPE, agent_a, "semantic", "i am always right")
    with pytest.raises(PolicyError):
        kb.review(promo.id, agent_a, "approve")


def test_same_identity_cannot_review_twice(kb, agent_a, agent_b):
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=2))
    promo = kb.propose(SCOPE, agent_a, "semantic", "standup at nine")
    kb.review(promo.id, agent_b, "approve")
    with pytest.raises(PolicyError):
        kb.review(promo.id, agent_b, "approve")


def test_reviewing_decided_promotion_rejected(kb, agent_a, agent_b, human):
    promo = kb.propose(SCOPE, agent_a, "semantic", "auto accepted")
    assert promo.status == "accepted"
    with pytest.raises(PolicyError):
        kb.review(promo.id, agent_b, "approve")


def test_unknown_promotion_and_claim_ids(kb, agent_a):
    with pytest.raises(NotFoundError):
        kb.review("no-such-promotion", agent_a, "approve")
    with pytest.raises(NotFoundError):
        kb.endorse("0" * 64, agent_a, "corroborate")
    with pytest.raises(NotFoundError):
        kb.retire("0" * 64, agent_a, "gone")
    with pytest.raises(NotFoundError):
        kb.claim("0" * 64)


def test_duplicate_promotion_is_idempotent(kb, agent_a):
    from datetime import UTC, datetime

    at = datetime(2026, 1, 1, tzinfo=UTC)
    first = kb.propose(SCOPE, agent_a, "semantic", "one body, one claim", asserted_at=at)
    second = kb.propose(SCOPE, agent_a, "semantic", "one body, one claim", asserted_at=at)
    assert first.id == second.id
    assert first.claim.claim_id == second.claim.claim_id
    assert len(kb.promotions(SCOPE)) == 1


def test_promotion_audit_trail_queryable(kb, agent_a, agent_b):
    kb.set_policy(SCOPE, Policy(mode="review"))
    promo = kb.propose(SCOPE, agent_a, "semantic", "audit me")
    kb.review(promo.id, agent_b, "approve", basis="checks out")
    assert kb.promotions(SCOPE, status="accepted")[0].id == promo.id
    assert kb.policy(SCOPE).mode == "review"
