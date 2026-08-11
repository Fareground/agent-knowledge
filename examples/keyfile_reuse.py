"""Keys across sessions: generate once, seal to a keyfile, reuse forever.

Every knowledge verb signs as an identity, so an agent must present the same
keypair from one session to the next. fg-agent-id ships passphrase-sealed
serialization (scrypt + ChaCha20-Poly1305); this shows the day-one flow.

In real use, keep the keyfile out of version control and source the
passphrase from your environment or a secret manager — never hardcode it.

Run:  python examples/keyfile_reuse.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fg_agent_id import KeyPair


def load_or_create(keyfile: Path, passphrase: str) -> KeyPair:
    """Load the sealed keypair if the keyfile exists, otherwise create it."""
    if keyfile.exists():
        return KeyPair.from_encrypted_bytes(keyfile.read_bytes(), passphrase)
    pair = KeyPair.generate()
    keyfile.write_bytes(pair.to_encrypted_bytes(passphrase))
    return pair


def main(keyfile: Path | None = None) -> None:
    if keyfile is None:
        keyfile = Path(tempfile.mkdtemp()) / "scout.key"
    passphrase = "example-only-passphrase"

    # Session 1: no keyfile yet — generate and seal.
    first = load_or_create(keyfile, passphrase)

    # Session 2 (later, a new process): load the same identity back.
    second = load_or_create(keyfile, passphrase)

    assert first.public == second.public, "same keyfile must yield the same author"
    print(f"same author across sessions: {second.public.signing.hex()[:16]}…")


if __name__ == "__main__":
    main()
