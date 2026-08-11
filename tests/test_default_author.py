"""``KnowledgeBase(store, default_author=...)`` — one handle per acting
agent; verbs may omit their keys argument, explicit keys always win, and
governance guards are unchanged."""

from __future__ import annotations

import pytest

from fg_agent_knowledge import (
    KnowledgeBase,
    Policy,
    PolicyError,
    Scope,
    ValidationError,
)

SCOPE = Scope(space="workspace-42")


def test_full_flow_with_per_agent_handles(store, agent_a, agent_b):
    scout = KnowledgeBase(store, default_author=agent_a)
    analyst = KnowledgeBase(store, default_author=agent_b)
    scout.set_policy(SCOPE, Policy(mode="review", required_approvals=1))

    ep = scout.observe(SCOPE, kind="observation", content="deploy failed on cold cache")
    promo = scout.propose(
        SCOPE, kind="procedural", statement="warm the cache first", episodes=(ep.id,)
    )
    promo = analyst.review(promo.id, verdict="approve", basis="matches incident log")
    assert promo.status == "accepted"

    analyst.endorse(promo.claim.claim_id, verdict="corroborate", basis="seen it work")
    retirement = scout.retire(promo.claim.claim_id, reason="pipeline replaced")
    assert retirement.body.claim_id == promo.claim.claim_id


def test_explicit_keys_win_over_default(store, agent_a, agent_b):
    kb = KnowledgeBase(store, default_author=agent_a)
    ep = kb.observe(SCOPE, agent_b, "observation", "explicit observer")
    from fg_agent_id import address_from_signing_key

    assert ep.observer == address_from_signing_key(agent_b.public.signing)


def test_omitting_keys_without_default_raises(kb):
    with pytest.raises(ValidationError, match="no author"):
        kb.propose(SCOPE, kind="semantic", statement="who signs this?")


def test_required_params_stay_required(store, agent_a):
    kb = KnowledgeBase(store, default_author=agent_a)
    with pytest.raises(ValidationError, match="statement is required"):
        kb.propose(SCOPE, kind="semantic")
    with pytest.raises(ValidationError, match="kind is required"):
        kb.observe(SCOPE, content="no kind given")


def test_self_review_guard_survives_defaults(store, agent_a):
    kb = KnowledgeBase(store, default_author=agent_a)
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=1))
    promo = kb.propose(SCOPE, kind="semantic", statement="the sky is blue")
    with pytest.raises(PolicyError):
        kb.review(promo.id, verdict="approve")
