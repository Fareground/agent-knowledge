"""Record ⇄ JSON converters for storage.

Storage persists exactly the signed body plus the signature, so a round-trip
through a store can never change what a signature covers. Derived standing
(confidence, staleness, suspect) is deliberately absent — it is recomputed at
read time, never persisted.
"""

from __future__ import annotations

import json

from fg_agent_id.serde import parse_datetime

from .types import ArtifactRef, Claim, ClaimBody, Endorsement, EndorsementBody, Scope


def claim_to_json(claim: Claim) -> str:
    return json.dumps(
        {"body": claim.body.body(), "signature": claim.signature,
         "claim_id": claim.claim_id},
        sort_keys=True,
    )


def claim_from_json(raw: str) -> Claim:
    d = json.loads(raw)
    b = d["body"]
    body = ClaimBody(
        scope=Scope(b["scope"]["space"], b["scope"]["segment"]),
        kind=b["kind"],
        statement=b["statement"],
        topics=tuple(b["topics"]),
        refs=tuple(ArtifactRef(r["uri"], r["kind"]) for r in b["refs"]),
        episodes=tuple(b["episodes"]),
        author=b["author"],
        asserted_at=parse_datetime("asserted_at", b["asserted_at"]),
        supersedes=b["supersedes"],
    )
    return Claim(body=body, signature=d["signature"], claim_id=d["claim_id"])


def endorsement_to_json(e: Endorsement) -> str:
    return json.dumps({"body": e.body.body(), "signature": e.signature}, sort_keys=True)


def endorsement_from_json(raw: str) -> Endorsement:
    d = json.loads(raw)
    b = d["body"]
    return Endorsement(
        body=EndorsementBody(
            claim_id=b["claim_id"],
            verdict=b["verdict"],
            basis=b["basis"],
            episodes=tuple(b["episodes"]),
            author=b["author"],
            issued_at=parse_datetime("issued_at", b["issued_at"]),
        ),
        signature=d["signature"],
    )
