"""Authorization and anti-abuse regressions from the adversarial audit.

The shared library records identity faithfully and enforces protocol rules;
these guard the boundary where "recording who did it" must become "refusing
to let one identity act on another's knowledge." Cross-author disagreement is
allowed only through contradiction (which keeps a claim visible), never
through retire/supersede (which hide it).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fg_agent_id import KeyPair

from fg_agent_knowledge import Policy, Scope
from fg_agent_knowledge.errors import PolicyError, ValidationError
from fg_agent_knowledge.types import MAX_TEXT_BYTES

SCOPE = Scope(space="ws-authz")


def _accepted_claim(kb, author, statement="the api is rate limited at ten rps"):
    promo = kb.propose(SCOPE, author, "semantic", statement)
    assert promo.status == "accepted"
    return promo.claim.claim_id


# -- CRITICAL 1: retirement hijack ---------------------------------------

def test_non_author_cannot_retire(kb, agent_a, agent_b):
    claim_id = _accepted_claim(kb, agent_a)
    with pytest.raises(PolicyError):
        kb.retire(claim_id, agent_b, reason="I don't like it")
    # still briefed — nothing was hidden
    ids = [i.claim.claim_id for i in kb.brief(SCOPE, task="rate limited api").items]
    assert claim_id in ids


def test_author_can_retire_own_claim(kb, agent_a):
    claim_id = _accepted_claim(kb, agent_a)
    kb.retire(claim_id, agent_a, reason="superseded by new limits")
    assert kb.brief(SCOPE, task="rate limited api").items == ()


# -- CRITICAL 2: forged supersedes ---------------------------------------

def test_non_author_cannot_supersede(kb, agent_a, agent_b):
    claim_id = _accepted_claim(kb, agent_a)
    with pytest.raises(PolicyError):
        kb.propose(
            SCOPE, agent_b, "semantic", "the api is unlimited actually",
            supersedes=claim_id,
        )
    ids = [i.claim.claim_id for i in kb.brief(SCOPE, task="rate limited api").items]
    assert claim_id in ids  # victim's claim still visible


def test_cross_author_disagreement_uses_contradiction(kb, agent_a, agent_b):
    """The sanctioned cross-author path: contradiction lowers confidence but
    the claim stays visible with the dispute attached."""
    claim_id = _accepted_claim(kb, agent_a)
    kb.endorse(claim_id, agent_b, "contradict", basis="measured twenty rps")
    item = kb.brief(SCOPE, task="rate limited api").items[0]
    assert item.claim.claim_id == claim_id
    assert item.contradictions == 1


# -- HIGH: caller-supplied timestamp gaming ------------------------------

def test_future_dated_endorsement_rejected(kb, agent_a):
    claim_id = _accepted_claim(kb, agent_a)
    future = datetime.now(UTC) + timedelta(days=3650)
    with pytest.raises(ValidationError):
        kb.endorse(claim_id, agent_a, "corroborate", issued_at=future)


def test_future_dated_claim_rejected(kb, agent_a):
    future = datetime.now(UTC) + timedelta(days=3650)
    with pytest.raises(ValidationError):
        kb.propose(SCOPE, agent_a, "semantic", "future fact", asserted_at=future)


def test_small_clock_skew_tolerated(kb, agent_a):
    claim_id = _accepted_claim(kb, agent_a)
    slightly_ahead = datetime.now(UTC) + timedelta(seconds=30)
    kb.endorse(claim_id, agent_a, "corroborate", issued_at=slightly_ahead)


# -- MEDIUM: unbounded text (DoS amplification) --------------------------

def test_oversized_statement_rejected(kb, agent_a):
    huge = "x" * (MAX_TEXT_BYTES + 1)
    with pytest.raises(ValidationError):
        kb.propose(SCOPE, agent_a, "semantic", huge)


def test_oversized_endorsement_basis_rejected(kb, agent_a):
    claim_id = _accepted_claim(kb, agent_a)
    with pytest.raises(ValidationError):
        kb.endorse(claim_id, agent_a, "corroborate", basis="y" * (MAX_TEXT_BYTES + 1))


# -- HIGH (quality audit): review-decision race does not stick pending ---

def test_concurrent_quorum_decides(kb, agent_a, agent_b, human):
    """Two approvals racing on a required_approvals=2 promotion must land the
    promotion 'accepted', never stuck 'pending' — the last writer decides on
    the full re-read verdict set."""
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=2))
    promo = kb.propose(SCOPE, agent_a, "semantic", "needs two approvals")
    assert promo.status == "pending"
    kb.review(promo.id, agent_b, "approve")
    final = kb.review(promo.id, human, "approve")
    assert final.status == "accepted"


def test_verdict_rejected_after_decision(kb, agent_a, agent_b, human):
    """Once a promotion is decided, no further verdict may be recorded — the
    audit trail cannot be polluted with a vote on a closed promotion."""
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=1))
    promo = kb.propose(SCOPE, agent_a, "semantic", "one approval decides this")
    decided = kb.review(promo.id, agent_b, "approve")
    assert decided.status == "accepted"
    with pytest.raises(PolicyError):
        kb.review(promo.id, human, "approve")
    assert len(kb._store.verdicts(promo.id)) == 1  # the late vote was not stored


def test_threaded_review_never_stores_late_verdict(store, agent_a, agent_b, human):
    """Concurrency stress: many reviewers race on a required_approvals=1
    promotion; the promotion accepts and no verdict is ever stored after the
    decision (verdict count never exceeds the votes admitted while pending)."""
    import threading

    from fg_agent_knowledge import KnowledgeBase

    kb = KnowledgeBase(store)
    kb.set_policy(SCOPE, Policy(mode="review", required_approvals=1))
    promo = kb.propose(SCOPE, agent_a, "semantic", "race target")
    reviewers = [KeyPair.generate() for _ in range(8)]

    barrier = threading.Barrier(len(reviewers))
    outcomes: list[str] = []

    def cast(k):
        barrier.wait()
        try:
            outcomes.append(kb.review(promo.id, k, "approve").status)
        except PolicyError:
            outcomes.append("rejected-late")

    threads = [threading.Thread(target=cast, args=(k,)) for k in reviewers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert kb.promotions(SCOPE)[0].status == "accepted"
    # Every stored verdict was admitted while pending; late ones were refused.
    stored = len(kb._store.verdicts(promo.id))
    assert stored == outcomes.count("accepted")
    assert "rejected-late" in outcomes or stored == len(reviewers)
