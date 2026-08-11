<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/wordmark-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="assets/wordmark.svg" />
    <img alt="Fareground" src="assets/wordmark.svg" width="320" />
  </picture>
</p>

<h1 align="center">agent-knowledge</h1>

<p align="center">
  <em>Shared knowledge for multi-agent spaces — claims with pedigree, not notes in a pile.</em>
</p>

<p align="center">
  <a href="https://github.com/Fareground/agent-knowledge/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Fareground/agent-knowledge/ci.yml?branch=main&style=flat-square&label=CI" /></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11+-3b82f6?style=flat-square" />
  <a href="https://pypi.org/project/fg-agent-knowledge/"><img alt="PyPI" src="https://img.shields.io/pypi/v/fg-agent-knowledge?style=flat-square" /></a>
</p>

---

## Overview

Per-agent memory is the agent harness's problem. The unowned layer is the
knowledge *between* agents: what a team knows, distinct from what any member
remembers. `agent-knowledge` standardizes that layer as **signed claims with
pedigree**, governed by explicit promotion — and deliberately does NOT
standardize storage engines, ranking algorithms, or consolidation
intelligence. Those compete; the format and protocols standardize.

It sits in Fareground's family of open agent building blocks:
[`agent-id`](https://github.com/Fareground/agent-id) (who an agent is)
→ [`agent-messaging`](https://github.com/Fareground/agent-messaging)
(how agents talk) → [`agent-memory`](https://github.com/Fareground/agent-memory)
(what one agent remembers) → **`agent-knowledge`** (what a group of agents
knows) → [`agent-framework`](https://github.com/Fareground/agent-framework)
(the runtime that ties them together).

## Status

**Early-stage — alpha.** The reference implementation is real and tested: the
claim format, signing domain, trust model, governance verbs, and briefing
assembly are implemented end to end, with byte-stable golden vectors in
`spec/vectors.json`. That said, the wire format is not yet frozen, there is no
federation, and the design is still moving. Treat it as a working reference,
not a stable dependency. Sections below describe only what actually runs today.

## Concepts

- **Claims with pedigree** — the unit of knowledge is a signed,
  content-addressed statement carrying its author, the episodes it was
  distilled from, and the artifacts it is about. `claim_id = sha256(signing_input)`:
  derived, never chosen, so two identical bodies are one claim.
- **Confidence ⊥ staleness** — two independent axes, both derived at read time
  from the endorsement record, never persisted as authoritative. Confidence
  asks "was this ever true"; staleness asks "when was it last re-encountered".
  Contradictions lower confidence but never touch staleness.
- **Contradiction attaches, never edits** — a disagreement is a signed record
  on the claim, visible in every briefing. Silent last-write-wins is forbidden
  by construction.
- **Suspect on artifact change** — claims about an artifact go suspect the
  moment the artifact changes (`invalidate`), and clear on the next
  corroboration. Provenance-linked invalidation is the signature move.
- **Governed promotion** — knowledge enters a scope by proposal, decided under
  a consumer-configured policy (auto with protected topics, or N distinct
  approvals; no self-review). The audit trail is the data structure.
- **Assembled briefings** — the standard is **model-free**: no LLM anywhere in
  the protocol. Briefings are ranked, attributed claims (lexical relevance ×
  confidence × freshness, refs boosted), never generated text. Consumers may
  layer generation on top.
- **Own signing domain** — every record is signed under
  `fg-agent-knowledge/v1/<context>` with fg-agent-id's canonical JSON, so a
  knowledge signature can never be replayed as an identity artifact. Golden
  vectors in `spec/vectors.json`.

## Getting started

```bash
pip install fg-agent-knowledge
```

The only runtime dependency is `fg-agent-id`; `sqlite3` is stdlib. To work
from source instead, see [CONTRIBUTING.md](CONTRIBUTING.md).

### Usage

Two agents propose and review; a briefing serves the result with pedigree
(runnable as [`examples/quickstart.py`](examples/quickstart.py)):

```python
from fg_agent_id import KeyPair
from fg_agent_knowledge import KnowledgeBase, Policy, Scope, SQLiteStore

store = SQLiteStore("team.db")
# One handle per acting agent: default_author is who this handle signs as.
scout = KnowledgeBase(store, default_author=KeyPair.generate())
analyst = KnowledgeBase(store, default_author=KeyPair.generate())
scope = Scope(space="workspace-42")
scout.set_policy(scope, Policy(mode="review", required_approvals=1))

# scout observes, distills, proposes
ep = scout.observe(scope, kind="observation", content="deploy failed twice on cold cache")
promo = scout.propose(
    scope, kind="procedural",
    statement="warm the cache before deploying the pricing service",
    topics=("deploy", "pricing"), episodes=(ep.id,),
)

# analyst reviews — the proposer cannot approve their own promotion
promo = analyst.review(promo.id, verdict="approve", basis="matches incident log")
assert promo.status == "accepted"

# anyone briefs before acting — assembled, attributed, never generated
briefing = analyst.brief(scope, task="deploy pricing service")
top = briefing.items[0]
print(top.claim.body.statement, top.confidence, top.verify_first)
```

Every verb also takes explicit keys as its second argument
(`kb.propose(scope, keys, "procedural", ...)`) — an explicit author always
wins over the handle's `default_author`, and governance guards (self-review,
author-only retire) compare identities at call time either way.

The signature moves — endorsement stances and provenance-linked invalidation:

```python
from datetime import datetime, timezone
from fg_agent_knowledge import ArtifactRef

claim_id = promo.claim.claim_id
analyst.endorse(claim_id, verdict="corroborate", basis="held on today's deploy")
scout.endorse(claim_id, verdict="contradict", basis="cold-cache failure recurred")

# the deploy script changed — every claim ref'ing it goes suspect
scout.invalidate(scope, "repo://pricing/deploy.sh", datetime.now(timezone.utc))
```

(`invalidate` matches claims by their `refs=(ArtifactRef(uri=…),)`; suspect
claims surface as `verify_first` in briefings until re-corroborated.)

> The import package is `fg_agent_knowledge` and the signing domain is
> `fg-agent-knowledge/v1` — those are load-bearing protocol identifiers and are
> intentionally left unchanged by the repository rename.

### Keys across sessions

Every verb signs as an identity, so an agent needs the *same* keypair from one
session to the next — `KeyPair.generate()` on every run creates a brand-new
author each time. `fg-agent-id` ships this as a one-liner: the keyfile is
created on first run and loaded back ever after, passphrase-sealed
(scrypt + ChaCha20-Poly1305) when a passphrase is given (runnable as
[`examples/keyfile_reuse.py`](examples/keyfile_reuse.py)):

```python
from fg_agent_id import load_or_create_keys

scout_keys = load_or_create_keys("scout.key", passphrase="…from your secret manager…")
scout = KnowledgeBase(store, default_author=scout_keys)

# scout now signs as the same author in every session
```

Treat the keyfile like any private key: keep it out of version control and
source the passphrase from your environment or a secret manager.

**Two infra seams, bring your own.** A knowledge base is the fixed normative
core (claim format + signing, the trust model, the verbs, governance) plus two
pluggable adapters: a **Store** (persistence — SQLite/in-memory reference,
bring Postgres/anything) and a **Retriever** (relevance — `KeywordRetriever`
with **BM25 over Porter-stemmed tokens** by default; bring a semantic/vector
retriever behind the same interface: `KnowledgeBase(store, retriever=…)`).
Storage and search are local concerns; trust and format stay fixed so claims
interoperate.

### What this is not (v1)

No consolidation engine (an LLM consolidator is a *consumer* of this API), no
transport (records are transport-agnostic signed JSON — carry them over AMP),
no *built-in* embeddings, no federation (planned: signed export bundles).

## Supported API

Everything importable from `fg_agent_knowledge` works, but the surface has two
tiers with different stability expectations:

- **Facade tier — build against this.** `KnowledgeBase` and its verbs, the
  record types (`Claim`, `Endorsement`, `Promotion`, `Retirement`, `Briefing`,
  `Scope`, `Policy`, …), the error hierarchy (`KnowledgeError` and subclasses),
  and the adapter protocols (`Store`, `Retriever`, plus the reference
  `SQLiteStore`, `InMemoryStore`, `KeywordRetriever`). This is the intended
  consumer surface; changes here are treated as breaking.
- **Wire tier — for interoperating implementations.** The low-level signing
  and encoding primitives (`sign_payload`, `signing_input`, `record_id`,
  `verify_by_address`, `DOMAIN`, the `CONTEXT_*` constants) and the raw record
  builders/verifiers. These track [`spec/SPEC.md`](spec/SPEC.md) exactly —
  useful for writing an alternative implementation or debugging signatures,
  but most applications never need them.

## Project structure

```
src/fg_agent_knowledge/   Reference implementation
  claim.py, endorsement.py, governance.py   Signed record builders + verifiers
  signing.py, serde.py                      Signing domain + canonical JSON
  knowledge.py                              KnowledgeBase facade (the verbs)
  store.py                                  Store adapter: SQLite + in-memory
  retrievers.py, retrieval.py               Retriever adapter + briefing assembly
  scoring.py                                Confidence / staleness derivation
  types.py, claim.py, errors.py             Data model and errors
spec/
  SPEC.md                                   Normative wire format
  vectors.json                              Byte-stable golden vectors
  generate_vectors.py                       Regenerate vectors
tests/                                      Unit + e2e + golden-vector tests
examples/                                   Runnable examples + consumer sketches
```

## Design

The normative wire format and data model live in
[`spec/SPEC.md`](spec/SPEC.md); byte-stable golden vectors in
[`spec/vectors.json`](spec/vectors.json) (regenerate with
`python spec/generate_vectors.py`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, tests, and conventions.

---

<p align="center">
  <sub>Built by <a href="https://github.com/Fareground">Fareground</a> · Licensed under <a href="LICENSE">Apache-2.0</a>.</sub>
</p>
