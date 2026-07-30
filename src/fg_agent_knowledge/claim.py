"""Building, signing, and verifying claims.

A claim is content-addressed: ``claim_id = sha256(signing_input("claim",
body))`` hex. The id is derived, never chosen, so two identical bodies are one
claim and duplicate proposals are idempotent by construction.
"""

from __future__ import annotations

from datetime import datetime

from fg_agent_id import KeyPair, address_from_signing_key

from .errors import SignatureError
from .signing import CONTEXT_CLAIM, record_id, sign_payload, verify_by_address
from .types import ArtifactRef, Claim, ClaimBody, ClaimKind, Scope


def build_claim(
    keys: KeyPair,
    scope: Scope,
    kind: ClaimKind,
    statement: str,
    topics: tuple[str, ...] = (),
    refs: tuple[ArtifactRef, ...] = (),
    episodes: tuple[str, ...] = (),
    asserted_at: datetime | None = None,
    supersedes: str | None = None,
) -> Claim:
    """Build and sign a claim as the holder of ``keys``.

    The author address is derived from the signing key — a claim can never
    carry an author its signer does not control.
    """
    body = ClaimBody(
        scope=scope,
        kind=kind,
        statement=statement,
        topics=tuple(topics),
        refs=tuple(refs),
        episodes=tuple(episodes),
        author=address_from_signing_key(keys.public.signing),
        asserted_at=asserted_at if asserted_at is not None else _now(),
        supersedes=supersedes,
    )
    payload = body.body()
    return Claim(
        body=body,
        signature=sign_payload(keys, CONTEXT_CLAIM, payload),
        claim_id=record_id(CONTEXT_CLAIM, payload),
    )


def claim_id_of(body: ClaimBody) -> str:
    """The content address of a claim body."""
    return record_id(CONTEXT_CLAIM, body.body())


def verify_claim(claim: Claim) -> None:
    """Verify a claim's signature against its author and its id against its body.

    Raises :class:`SignatureError` on tampering of any kind — a body whose id
    does not match is treated as forged, not merely malformed.
    """
    payload = claim.body.body()
    if record_id(CONTEXT_CLAIM, payload) != claim.claim_id:
        raise SignatureError("claim_id does not match the claim body")
    verify_by_address(claim.body.author, CONTEXT_CLAIM, payload, claim.signature)


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
