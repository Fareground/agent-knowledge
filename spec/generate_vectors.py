"""Regenerate spec/vectors.json.

Every vector is derived from fixed seeds and fixed timestamps, so the output is
byte-stable across runs. Run this after any intentional wire-format change:

    python spec/generate_vectors.py

Then review the diff — an unexpected change here means the wire format moved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

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
)

SEED_AUTHOR = bytes(range(32))
SEED_REVIEWER = bytes(range(32, 64))
AGREEMENT_SEED = bytes(range(96, 128))

ASSERTED_AT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
ISSUED_AT = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)


def keypair(seed: bytes) -> KeyPair:
    return KeyPair(
        signing_key=Ed25519PrivateKey.from_private_bytes(seed),
        agreement_key=X25519PrivateKey.from_private_bytes(AGREEMENT_SEED),
    )


def main() -> None:
    author = keypair(SEED_AUTHOR)
    reviewer = keypair(SEED_REVIEWER)
    scope = Scope(space="vector-space", segment="vector-segment")

    claim = build_claim(
        author,
        scope,
        "semantic",
        "the pricing service reads its rate table from config/rates.yaml",
        topics=("pricing", "config"),
        refs=(ArtifactRef(uri="repo://pricing/config/rates.yaml", kind="file"),),
        episodes=("00000000-0000-4000-8000-000000000001",),
        asserted_at=ASSERTED_AT,
    )
    endorsement = build_endorsement(
        reviewer, claim.claim_id, "corroborate",
        basis="verified against the deployed config", issued_at=ISSUED_AT,
    )
    verdict = build_verdict(
        reviewer, "00000000-0000-4000-8000-0000000000aa", "approve",
        basis="statement matches the artifact", issued_at=ISSUED_AT,
    )
    retirement = build_retirement(
        author, claim.claim_id, "rate table moved to the database", issued_at=ISSUED_AT,
    )

    vectors = {
        "seeds": {
            "author_signing": SEED_AUTHOR.hex(),
            "reviewer_signing": SEED_REVIEWER.hex(),
            "agreement": AGREEMENT_SEED.hex(),
        },
        "addresses": {
            "author": address_from_signing_key(author.public.signing),
            "reviewer": address_from_signing_key(reviewer.public.signing),
        },
        "claim": {
            "body": claim.body.body(),
            "signing_input_hex": signing_input(CONTEXT_CLAIM, claim.body.body()).hex(),
            "claim_id": claim.claim_id,
            "signature": claim.signature,
        },
        "endorsement": {
            "body": endorsement.body.body(),
            "signing_input_hex": signing_input(
                CONTEXT_ENDORSEMENT, endorsement.body.body()).hex(),
            "signature": endorsement.signature,
        },
        "verdict": {
            "body": verdict.body.body(),
            "signing_input_hex": signing_input(CONTEXT_VERDICT, verdict.body.body()).hex(),
            "signature": verdict.signature,
        },
        "retirement": {
            "body": retirement.body.body(),
            "signing_input_hex": signing_input(
                CONTEXT_RETIREMENT, retirement.body.body()).hex(),
            "signature": retirement.signature,
        },
    }
    out = Path(__file__).parent / "vectors.json"
    out.write_text(json.dumps(vectors, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
