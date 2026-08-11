"""Keys across sessions: one call, same identity every run.

Every knowledge verb signs as an identity, so an agent must present the same
keypair from one session to the next. fg-agent-id ships this as a one-liner:
``load_or_create_keys`` generates and saves a keyfile on first run and loads
it back ever after — pass a passphrase to seal it (scrypt + ChaCha20-Poly1305).

In real use, keep the keyfile out of version control and source the
passphrase from your environment or a secret manager — never hardcode it.

Run:  python examples/keyfile_reuse.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fg_agent_id import load_or_create_keys


def main(keyfile: Path | None = None) -> None:
    if keyfile is None:
        keyfile = Path(tempfile.mkdtemp()) / "scout.key"
    passphrase = "example-only-passphrase"

    # Session 1: no keyfile yet — generate and seal.
    first = load_or_create_keys(keyfile, passphrase)

    # Session 2 (later, a new process): load the same identity back.
    second = load_or_create_keys(keyfile, passphrase)

    assert first.public == second.public, "same keyfile must yield the same author"
    print(f"same author across sessions: {second.public.signing.hex()[:16]}…")


if __name__ == "__main__":
    main()
