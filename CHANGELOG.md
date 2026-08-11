# Changelog

## 0.2.1 — 2026-08-11

First PyPI release; packaging, documentation, and one additive ergonomic API
— no wire-format changes.

- **`KnowledgeBase(store, default_author=keys)`** — the identity this handle
  acts as. The signing verbs (`observe` / `propose` / `review` / `endorse` /
  `retire`) may then omit their keys argument; an explicit keys argument
  always wins, and governance guards (self-review, author-only retire) are
  unchanged since they compare identities at call time. Fully backward
  compatible — existing explicit-keys calls work as before.
- README/examples: credential setup now uses fg-agent-id's
  `load_or_create_keys` one-liner instead of hand-rolling the keyfile
  load-or-generate pattern.
- Pin the runtime dependency to `fg-agent-id>=0.2,<0.3` (resolvable from PyPI).
- Release workflow: build, tag/version check, clean-env wheel smoke test,
  trusted publishing to PyPI.
- Runnable examples (`examples/quickstart.py`, `examples/keyfile_reuse.py`),
  exercised by the test suite so they cannot rot.
- README: PyPI install instructions, key persistence across sessions
  (passphrase-sealed keyfiles), and a "Supported API" section tiering the
  facade surface vs the low-level wire primitives.
- `SECURITY.md` with a private reporting channel.

## 0.2.0 — 2026-07-20

Retrieval becomes a first-class, pluggable infra seam — alongside storage.

- New **`Retriever` adapter interface** (`rank` + optional `index`/`remove`
  lifecycle hooks). The core owns trust and briefing assembly; a retriever
  owns only relevance, so a deployment can bring its own search (semantic/
  vector) without touching the portable core. `KnowledgeBase(store, retriever=…)`.
- New reference **`KeywordRetriever`**: best-practice lexical search — **Okapi
  BM25** (the Lucene/Elasticsearch ranking function) over stopword-filtered,
  **Porter-stemmed** tokens, with topic-term weighting. Stemming fixes the
  inflection miss (a task "building the deck" now matches a claim about
  "build"); IDF weights rare terms; BM25 length-normalizes. All parameters
  (`k1`, `b`, `stem`, `remove_stopwords`, `topic_weight`) are tunable.
- Removed the store-side FTS5 candidate filter and `Store.search_candidates`;
  retrieval now lives entirely behind the `Retriever` seam. The `Store` is
  persistence-only.
- SPEC §9 documents the two infra seams (Store + Retriever) vs the fixed
  normative core; signing and vectors unchanged.

## 0.1.0 — 2026-07-20

Initial release: the reference implementation of the fg-agent-knowledge v1 wire standard.

- Signed, content-addressed claims with pedigree (episodes, refs, supersedes chains).
- Endorsements: corroborate/contradict; confidence and staleness derived at read time.
- Provenance-linked invalidation (`suspect`) on artifact change.
- Governed promotion: auto/review policies, protected topics, distinct approvers, no self-review.
- Signed retirements — the only way a claim leaves briefings.
- Assembled, model-free briefings with `verify_first` nudges and visible conflicts.
- `SQLiteStore` (WAL + FTS5 with token-overlap fallback) and `InMemoryStore`.
- Own signing domain `fg-agent-knowledge/v1` over fg-agent-id primitives; golden vectors in `spec/vectors.json`.

Adversarial-audit hardening (pre-release):
- Retirement and supersession are author-only — closing two hidden-censorship
  primitives (any identity could previously retire or silently supersede
  another author's claim). Cross-author disagreement uses contradiction.
- Future-dated timestamps rejected beyond a 300s skew window (prevented
  gaming derived confidence/staleness with no collusion).
- Signed text fields bounded (65536 bytes) against storage/signing amplification.
- Review verdicts are admitted atomically only while the promotion is
  `pending` (checked + stored under one store lock), so a concurrent quorum
  can never leave a promotion stuck `pending` nor record a vote on an
  already-decided promotion. Re-verified by a second adversarial pass +
  threaded race tests.
- SPEC §7.1 documents the consumer's Sybil-resistance and policy obligations.
