"""Signing discipline: domain separation, tamper rejection, float rejection."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fg_agent_id.signing import DOMAIN as ID_DOMAIN

from fg_agent_knowledge import (
    CONTEXT_CLAIM,
    CONTEXT_ENDORSEMENT,
    DOMAIN,
    Scope,
    SignatureError,
    ValidationError,
    build_claim,
    build_endorsement,
    signing_input,
    verify_claim,
    verify_endorsement,
)
from fg_agent_knowledge.signing import verify_by_address

SCOPE = Scope(space="s1")


def _claim(keys, statement="the deploy script lives in ops/deploy.sh"):
    return build_claim(keys, SCOPE, "semantic", statement,
                       asserted_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_domain_is_distinct_from_fg_agent_id():
    assert DOMAIN != ID_DOMAIN
    assert signing_input(CONTEXT_CLAIM, {}) != signing_input(CONTEXT_ENDORSEMENT, {})


def test_context_separation_prevents_cross_type_replay(agent_a):
    claim = _claim(agent_a)
    with pytest.raises(SignatureError):
        verify_by_address(claim.body.author, CONTEXT_ENDORSEMENT,
                          claim.body.body(), claim.signature)


def test_tampered_statement_rejected(agent_a):
    claim = _claim(agent_a)
    forged = replace(claim, body=replace(claim.body, statement="the deploy script lives in /tmp"))
    with pytest.raises(SignatureError):
        verify_claim(forged)


def test_tampered_signature_rejected(agent_a, agent_b):
    claim = _claim(agent_a)
    other = _claim(agent_b)
    with pytest.raises(SignatureError):
        verify_claim(replace(claim, signature=other.signature))


def test_wrong_author_rejected(agent_a, agent_b):
    claim = _claim(agent_a)
    e = build_endorsement(agent_b, claim.claim_id, "corroborate")
    forged = replace(e, body=replace(e.body, author=claim.body.author))
    with pytest.raises(SignatureError):
        verify_endorsement(forged)


def test_non_canonical_base64_rejected(agent_a):
    claim = _claim(agent_a)
    assert claim.signature.endswith("=")
    # flip unused trailing padding bits: same raw signature, different spelling
    tampered = claim.signature[:-2] + ("9" if claim.signature[-2] != "9" else "5") + "="
    with pytest.raises(SignatureError):
        verify_claim(replace(claim, signature=tampered))


def test_floats_in_signed_body_rejected():
    with pytest.raises(ValidationError):
        signing_input(CONTEXT_CLAIM, {"confidence": 0.9})


def test_claim_id_matches_body_or_rejected(agent_a):
    claim = _claim(agent_a)
    with pytest.raises(SignatureError):
        verify_claim(replace(claim, claim_id="0" * 64))


def test_identical_bodies_are_one_claim(agent_a):
    a = _claim(agent_a)
    b = _claim(agent_a)
    assert a.claim_id == b.claim_id
