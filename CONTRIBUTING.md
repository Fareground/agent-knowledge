# Contributing

Thanks for your interest in `agent-knowledge`. This is an early-stage reference
implementation of a wire standard, so correctness and byte-stability matter more
than breadth.

## Dev setup

Requires Python 3.11+.

```bash
git clone https://github.com/Fareground/agent-knowledge.git
cd agent-knowledge
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

The editable install resolves the `fg-agent-id` dependency from PyPI. If you
are working before/without a PyPI release of `fg-agent-id` (or want its
unreleased tip), install it from GitHub first:

```bash
pip install "fg-agent-id @ git+https://github.com/Fareground/agent-id.git"
pip install -e ".[dev]"
```

## Tests

```bash
pytest                       # full suite (unit + e2e + golden vectors)
pytest --cov=src --cov-report=term-missing
```

All tests must pass before a change is merged. If you touch signing, the claim
format, or canonical JSON, regenerate and review the golden vectors:

```bash
python spec/generate_vectors.py
```

A vectors diff is a wire-format change — call it out explicitly in your PR.

## Style

- Follow PEP 8; type-annotate all function signatures.
- Prefer immutable, frozen dataclasses for records; return new objects rather
  than mutating in place.
- Many small, focused files over few large ones.
- `ruff` is used for linting:

  ```bash
  ruff check src tests
  ```

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add signed export bundles
fix: reject future-dated endorsements beyond skew window
docs: clarify confidence vs staleness
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Commits must **not** include AI/assistant co-author attribution or
`Co-authored-by` trailers for any assistant.

## Scope note

The normative core (claim format, signing domain, trust model, governance
verbs) is fixed and interoperable — changes there need a matching SPEC and
vectors update. Storage and retrieval are pluggable adapters; new adapters are
welcome without touching the core.
