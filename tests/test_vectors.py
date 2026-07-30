"""Golden vectors: the wire format is byte-stable across runs and releases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fg_agent_id import KeyPair, address_from_signing_key

from fg_agent_knowledge import (
    CONTEXT_CLAIM,
    CONTEXT_ENDORSEMENT,
    CONTEXT_RETIREMENT,
    CONTEXT_VERDICT,
    ArtifactRef,
    Scope,
    build_claim,
    build_endorsement,
    build_retirement,
    build_verdict,
    signing_input,
    verify_claim,
    verify_endorsement,
)

VECTORS = json.loads((Path(__file__).parent.parent / "spec" / "vectors.json").read_text())


def _keypair(seed_hex: str) -> KeyPair:
    return KeyPair(
        signing_key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex)),
        agreement_key=X25519PrivateKey.from_private_bytes(
            bytes.fromhex(VECTORS["seeds"]["agreement"])
        ),
    )


@pytest.fixture(scope="module")
def author():
    return _keypair(VECTORS["seeds"]["author_signing"])


@pytest.fixture(scope="module")
def reviewer():
    return _keypair(VECTORS["seeds"]["reviewer_signing"])


def test_addresses_reproduce(author, reviewer):
    assert address_from_signing_key(author.public.signing) == VECTORS["addresses"]["author"]
    assert address_from_signing_key(reviewer.public.signing) == VECTORS["addresses"]["reviewer"]


def test_claim_vector_reproduces(author):
    v = VECTORS["claim"]
    claim = build_claim(
        author,
        Scope(space="vector-space", segment="vector-segment"),
        "semantic",
        v["body"]["statement"],
        topics=tuple(v["body"]["topics"]),
        refs=(ArtifactRef(uri="repo://pricing/config/rates.yaml", kind="file"),),
        episodes=tuple(v["body"]["episodes"]),
        asserted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert claim.body.body() == v["body"]
    assert signing_input(CONTEXT_CLAIM, claim.body.body()).hex() == v["signing_input_hex"]
    assert claim.claim_id == v["claim_id"]
    assert claim.signature == v["signature"]  # Ed25519 is deterministic
    verify_claim(claim)


def test_endorsement_vector_reproduces(reviewer):
    v = VECTORS["endorsement"]
    e = build_endorsement(
        reviewer, v["body"]["claim_id"], "corroborate",
        basis=v["body"]["basis"], issued_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert e.body.body() == v["body"]
    assert signing_input(CONTEXT_ENDORSEMENT, e.body.body()).hex() == v["signing_input_hex"]
    assert e.signature == v["signature"]
    verify_endorsement(e)


def test_verdict_vector_reproduces(reviewer):
    v = VECTORS["verdict"]
    record = build_verdict(
        reviewer, v["body"]["promotion_id"], "approve",
        basis=v["body"]["basis"], issued_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert record.body.body() == v["body"]
    assert signing_input(CONTEXT_VERDICT, record.body.body()).hex() == v["signing_input_hex"]
    assert record.signature == v["signature"]


def test_retirement_vector_reproduces(author):
    v = VECTORS["retirement"]
    record = build_retirement(
        author, v["body"]["claim_id"], v["body"]["reason"],
        issued_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert record.body.body() == v["body"]
    assert signing_input(CONTEXT_RETIREMENT, record.body.body()).hex() == v["signing_input_hex"]
    assert record.signature == v["signature"]


def test_signing_input_tag_layout():
    raw = signing_input(CONTEXT_CLAIM, {"a": 1})
    tag = b"fg-agent-knowledge/v1/claim"
    assert raw[:2] == len(tag).to_bytes(2, "big")
    assert raw[2 : 2 + len(tag)] == tag
    assert raw[2 + len(tag):] == b'{"a":1}'
