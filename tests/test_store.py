"""Store parity: every record round-trips identically through both engines
(the fixture parametrizes SQLiteStore and InMemoryStore)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fg_agent_knowledge import (
    ArtifactRef,
    InMemoryStore,
    KnowledgeBase,
    Policy,
    Scope,
    SQLiteStore,
    build_claim,
    build_endorsement,
)

SCOPE = Scope(space="s", segment="seg")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_claim_roundtrip_preserves_bytes(store, agent_a):
    claim = build_claim(
        agent_a, SCOPE, "relational", "alice reviews bob's prs",
        topics=("Reviews", "reviews", "team"),
        refs=(ArtifactRef(uri="repo://x", kind="repo"),),
        episodes=("e-1",), asserted_at=T0, supersedes=None,
    )
    store.add_claim(claim)
    loaded = store.claim(claim.claim_id)
    assert loaded == claim
    assert loaded.body.body() == claim.body.body()  # signature-relevant bytes intact


def test_claim_add_is_idempotent(store, agent_a):
    claim = build_claim(agent_a, SCOPE, "semantic", "stored once", asserted_at=T0)
    store.add_claim(claim)
    store.add_claim(claim)
    assert len(store.claims("s")) == 1


def test_endorsements_append_only_and_ordered(store, agent_a, agent_b):
    claim = build_claim(agent_a, SCOPE, "semantic", "ordered", asserted_at=T0)
    store.add_claim(claim)
    first = build_endorsement(agent_b, claim.claim_id, "contradict", issued_at=T0)
    second = build_endorsement(agent_b, claim.claim_id, "corroborate",
                               issued_at=T0 + timedelta(days=1))
    store.add_endorsement(first)
    store.add_endorsement(second)
    assert store.endorsements(claim.claim_id) == [first, second]


def test_invalidations_keep_latest_per_uri(store):
    store.record_invalidation("s", "repo://x", T0)
    store.record_invalidation("s", "repo://x", T0 + timedelta(days=2))
    store.record_invalidation("s", "repo://x", T0 + timedelta(days=1))
    assert store.invalidations("s") == {"repo://x": T0 + timedelta(days=2)}
    assert store.invalidations("elsewhere") == {}


def test_policy_roundtrip(store):
    policy = Policy(mode="review", required_approvals=3,
                    protected_topics=("Billing", "security"),
                    staleness_horizon_seconds=3600)
    store.set_policy(SCOPE, policy)
    assert store.policy(SCOPE) == policy
    assert store.policy(Scope(space="s")) is None  # segment-keyed


def test_sqlite_persists_across_reopen(tmp_path, agent_a, agent_b, human):
    path = str(tmp_path / "persist.db")
    kb = KnowledgeBase(SQLiteStore(path))
    scope = Scope(space="durable")
    promo = kb.propose(scope, agent_a, "semantic", "survives a restart",
                       topics=("ops",))
    kb.endorse(promo.claim.claim_id, agent_b, "corroborate")

    reopened = KnowledgeBase(SQLiteStore(path))
    item = reopened.brief(scope, task="restart survives").items[0]
    assert item.claim.claim_id == promo.claim.claim_id
    assert item.corroborations == 1


def test_both_stores_rank_identically(agent_a, agent_b, tmp_path):
    scope = Scope(space="parity")
    stores = [InMemoryStore(), SQLiteStore(str(tmp_path / "rank.db"))]
    orders = []
    for s in stores:
        kb = KnowledgeBase(s)
        a = kb.propose(scope, agent_a, "semantic", "the queue drains slowly at noon",
                       topics=("queue",), asserted_at=T0)
        b = kb.propose(scope, agent_a, "semantic", "the queue is redis backed",
                       topics=("queue", "redis"), asserted_at=T0)
        kb.endorse(b.claim.claim_id, agent_b, "corroborate")
        orders.append([i.claim.claim_id
                       for i in kb.brief(scope, task="queue redis slow noon").items])
    assert orders[0] == orders[1]
