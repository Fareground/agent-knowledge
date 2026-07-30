"""Corroboration and contradiction records.

A contradiction never edits the claim it targets — it attaches to it and
lowers derived confidence. Silent last-write-wins is forbidden by
construction: the record of disagreement IS the data structure.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fg_agent_id import KeyPair, address_from_signing_key

from .signing import CONTEXT_ENDORSEMENT, sign_payload, verify_by_address
from .types import Endorsement, EndorsementBody, EndorsementVerdict


def build_endorsement(
    keys: KeyPair,
    claim_id: str,
    verdict: EndorsementVerdict,
    basis: str = "",
    episodes: tuple[str, ...] = (),
    issued_at: datetime | None = None,
) -> Endorsement:
    """Build and sign an endorsement as the holder of ``keys``.

    Authors may corroborate their own claims (a re-encounter is evidence);
    confidence still counts distinct identities, so self-corroboration never
    stacks.
    """
    body = EndorsementBody(
        claim_id=claim_id,
        verdict=verdict,
        basis=basis,
        episodes=tuple(episodes),
        author=address_from_signing_key(keys.public.signing),
        issued_at=issued_at if issued_at is not None else datetime.now(UTC),
    )
    return Endorsement(
        body=body, signature=sign_payload(keys, CONTEXT_ENDORSEMENT, body.body())
    )


def verify_endorsement(endorsement: Endorsement) -> None:
    """Verify an endorsement's signature against its author."""
    verify_by_address(
        endorsement.body.author,
        CONTEXT_ENDORSEMENT,
        endorsement.body.body(),
        endorsement.signature,
    )
