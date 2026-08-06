"""Promotion lifecycle: proposal, review, retirement.

Promotion is a proposal, decided under the scope's policy. The library
enforces protocol rules — no self-review, distinct approvers, one decision
per promotion — and records identities faithfully. WHO may review or set
policy is the consumer's job; org charts do not belong in a wire standard.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fg_agent_id import KeyPair, address_from_signing_key

from .errors import PolicyError
from .signing import (
    CONTEXT_RETIREMENT,
    CONTEXT_VERDICT,
    sign_payload,
    verify_by_address,
)
from .types import (
    Claim,
    Policy,
    Promotion,
    Retirement,
    RetirementBody,
    ReviewDecision,
    ReviewVerdict,
    ReviewVerdictBody,
    Scope,
)

DEFAULT_POLICY = Policy(mode="auto")


def needs_review(claim: Claim, policy: Policy) -> bool:
    """Auto mode accepts immediately UNLESS a topic is protected; review mode
    always queues."""
    if policy.mode == "review":
        return True
    return any(t in policy.protected_topics for t in claim.body.topics)


def open_promotion(scope: Scope, claim: Claim, proposer: str, policy: Policy,
                   now: datetime | None = None) -> Promotion:
    """A new promotion record, decided immediately when policy allows."""
    now = now if now is not None else datetime.now(UTC)
    pending = needs_review(claim, policy)
    return Promotion(
        id=str(uuid.uuid4()),
        scope=scope,
        claim=claim,
        proposer=proposer,
        status="pending" if pending else "accepted",
        created_at=now,
        decided_at=None if pending else now,
    )


def build_verdict(keys: KeyPair, promotion_id: str, verdict: ReviewDecision,
                  basis: str = "", issued_at: datetime | None = None) -> ReviewVerdict:
    body = ReviewVerdictBody(
        promotion_id=promotion_id,
        verdict=verdict,
        basis=basis,
        author=address_from_signing_key(keys.public.signing),
        issued_at=issued_at if issued_at is not None else datetime.now(UTC),
    )
    return ReviewVerdict(body=body, signature=sign_payload(keys, CONTEXT_VERDICT, body.body()))


def verify_verdict(verdict: ReviewVerdict) -> None:
    verify_by_address(verdict.body.author, CONTEXT_VERDICT,
                      verdict.body.body(), verdict.signature)


def check_reviewable(promotion: Promotion, reviewer: str,
                     prior: list[ReviewVerdict]) -> None:
    """Protocol rules for admitting a review verdict. Raises PolicyError."""
    if promotion.status != "pending":
        raise PolicyError(f"promotion {promotion.id} is already {promotion.status}")
    if reviewer == promotion.proposer:
        raise PolicyError("proposer cannot review their own promotion")
    if any(v.body.author == reviewer for v in prior):
        raise PolicyError("approvers must be distinct — this identity already reviewed")


def decide(promotion: Promotion, verdicts: list[ReviewVerdict],
           policy: Policy) -> str | None:
    """The promotion's outcome given its verdicts, or None while still pending.

    Any reject → rejected; ``required_approvals`` distinct approving
    identities → accepted.
    """
    if any(v.body.verdict == "reject" for v in verdicts):
        return "rejected"
    approvers = {v.body.author for v in verdicts if v.body.verdict == "approve"}
    if len(approvers) >= policy.required_approvals:
        return "accepted"
    return None


def build_retirement(keys: KeyPair, claim_id: str, reason: str,
                     issued_at: datetime | None = None) -> Retirement:
    body = RetirementBody(
        claim_id=claim_id,
        reason=reason,
        author=address_from_signing_key(keys.public.signing),
        issued_at=issued_at if issued_at is not None else datetime.now(UTC),
    )
    return Retirement(body=body, signature=sign_payload(keys, CONTEXT_RETIREMENT, body.body()))


def verify_retirement(retirement: Retirement) -> None:
    verify_by_address(retirement.body.author, CONTEXT_RETIREMENT,
                      retirement.body.body(), retirement.signature)
