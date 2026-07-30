"""Domain-separated signing for knowledge records.

Same wire construction as fg-agent-id (``uint16be(len(tag)) || tag ||
canonical_json(body)``) but under this standard's own domain, so a signature
produced for a knowledge record can never be replayed as an identity artifact
or vice versa — even if two payloads canonicalize to the same bytes.

Contexts name the record type being signed. Adding a new signed record type
means adding a context constant here. Never reuse a context across record
types, and never sign a bare payload.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from fg_agent_id import KeyPair, canonical_json
from fg_agent_id.address import signing_key_from_address
from fg_agent_id.errors import AddressError
from fg_agent_id.errors import SignatureError as _IdSignatureError
from fg_agent_id.keys import PublicKeys
from fg_agent_id.signing import decode_signature

from .errors import SignatureError, ValidationError

DOMAIN = "fg-agent-knowledge/v1"

# One constant per signed record type. These strings are wire-visible.
CONTEXT_CLAIM = "claim"
CONTEXT_ENDORSEMENT = "endorsement"
CONTEXT_VERDICT = "verdict"
CONTEXT_RETIREMENT = "retirement"

_MAX_TAG_BYTES = 0xFFFF


def domain_tag(context: str) -> bytes:
    """The full UTF-8 domain tag for a context (``<DOMAIN>/<context>``)."""
    if not context:
        raise ValueError("signing context must be a non-empty string")
    tag = f"{DOMAIN}/{context}".encode()
    if len(tag) > _MAX_TAG_BYTES:
        raise ValueError("signing context tag is too long")
    return tag


def signing_input(context: str, payload: Any) -> bytes:
    """The exact bytes to sign or verify for ``payload`` under ``context``.

    Floats anywhere in the payload are rejected (canonical JSON rule inherited
    from fg-agent-id), surfaced as :class:`ValidationError` so callers see a
    knowledge-layer error, not a serialization detail.
    """
    tag = domain_tag(context)
    try:
        body = canonical_json(payload)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return len(tag).to_bytes(2, "big") + tag + body


def record_id(context: str, payload: Any) -> str:
    """Content address of a signed record: sha256 of its signing input, hex.

    Derived, never chosen — two identical bodies are one record. Used for
    ``claim_id`` and any future content-addressed record.
    """
    return hashlib.sha256(signing_input(context, payload)).hexdigest()


def sign_payload(keys: KeyPair, context: str, payload: Any) -> str:
    """Sign ``payload`` under ``context``; returns a base64 signature."""
    return base64.b64encode(keys.sign(signing_input(context, payload))).decode()


def verify_by_address(address: str, context: str, payload: Any, signature: str) -> None:
    """Verify a signature against the signing key an AMP address self-certifies.

    Raises :class:`SignatureError` (this package's) on any failure, including
    non-canonical base64 spellings — signatures are identifiers as well as
    proofs, so one signature must have exactly one wire form.
    """
    try:
        public = PublicKeys(
            signing=signing_key_from_address(address), agreement=_NO_AGREEMENT
        )
        public.verify(decode_signature(signature), signing_input(context, payload))
    except (AddressError, _IdSignatureError) as exc:
        raise SignatureError(str(exc)) from exc


# Signature verification only ever touches the Ed25519 half; this placeholder
# keeps PublicKeys' shape without implying a usable X25519 key.
_NO_AGREEMENT = b"\x00" * 32
