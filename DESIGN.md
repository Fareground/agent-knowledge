# agent-knowledge — Design

The shared knowledge substrate for multi-agent spaces. Part of the Fareground
agent-standards family: `fg-agent-id` (who an agent is) → `fg-amp` (how agents
talk) → **`fg-agent-knowledge` (what a group of agents knows)**.

This document explains the design: the concepts, data model, and module
layout, and why they are shaped the way they are. The normative wire spec
lives in [`spec/SPEC.md`](spec/SPEC.md).

## Thesis

Per-agent memory is the agent harness's problem. The unowned layer is the
knowledge *between* agents: what a team knows, distinct from what any member
remembers. fg-agent-knowledge standardizes that layer as **claims with
pedigree** governed by explicit promotion, and deliberately does NOT
standardize storage engines, ranking algorithms, or consolidation
intelligence — those compete; the format and protocols standardize.

The standard is **model-free**: no LLM anywhere in the protocol. Briefings
are assembled (ranked, attributed claims), never generated. Consumers may
layer generation on top.

## Core concepts

### Episode (capture)

A cheap, append-only observation. No judgment at write time; quality lives in
promotion. Episodes are fuel for consolidation, not directly retrieved by
briefings.

```
Episode {
  id:           uuid
  scope:        Scope
  observer:     amp:key address (who saw it)
  kind:         "observation" | "outcome" | "correction" | "surprise"
  content:      str (free text)
  refs:         [ArtifactRef]           # optional things this is about
  occurred_at:  RFC3339 UTC
}
```

Episodes are unsigned (they're staging data, cheap by design). Capture is
built for cooperative agents; platforms auto-capture outcomes as the floor.

### Claim (the unit of knowledge)

A signed, provenance-carrying statement. The heart of the standard.

```
ClaimBody {                      # the signed payload — canonical JSON
  spec:        "fg-agent-knowledge/v1"
  scope:       Scope
  kind:        "semantic" | "procedural" | "relational"
  statement:   str               # the knowledge itself, plain text
  topics:      [str]             # lowercase tags, sorted, deduped
  refs:        [ArtifactRef]     # artifacts this claim is ABOUT (invalidation hooks)
  episodes:    [episode_id]      # provenance: what it was distilled from
  author:      amp:key address
  asserted_at: RFC3339 UTC
  supersedes:  claim_id | null   # explicit revision chain
}

Claim = ClaimBody + signature (by author, context "claim")
claim_id = sha256(signing_input("claim", ClaimBody)) hex  # content-addressed
```

Rules:
- Claim bodies are **immutable**. Revision = new claim with `supersedes`.
- `claim_id` is derived, never chosen; two identical bodies are one claim.
- Signature is verified against `author` (self-certifying via fg-agent-id).

### Endorsements: corroboration & contradiction

Standing is built from signed endorsements by OTHER identities (or the
author, for re-encounters):

```
EndorsementBody {
  spec:       "fg-agent-knowledge/v1"
  claim_id:   str
  verdict:    "corroborate" | "contradict"
  basis:      str                # why (free text)
  episodes:   [episode_id]       # optional evidence
  author:     amp:key address
  issued_at:  RFC3339 UTC
}
Endorsement = body + signature (context "endorsement")
```

A contradiction never edits the claim — it attaches to it and lowers
confidence. Silent last-write-wins is forbidden by construction.

### Confidence ⊥ staleness (the decay model — DECIDED)

Two independent axes on every claim, both **derived, never stored as
authoritative** (recomputed from the endorsement record):

- **confidence** ∈ [0,1] — "how sure are we this was ever true."
  Base prior + corroborations up, contradictions down. Reference formula
  (implementations may substitute, the FIELDS are the standard):
  `confidence = (1 + c) / (2 + c + k*d)` where c = distinct corroborating
  identities, d = distinct contradicting identities, k = contradiction
  weight (default 2 — one contradiction outweighs one corroboration).
- **staleness_seconds** — time since the last corroborating encounter
  (asserted_at counts as the first). Resets on corroboration; contradictions
  do NOT touch staleness.
- **suspect** (bool) — provenance-linked invalidation: set when any
  `ArtifactRef` in `refs` reports a change newer than the last corroboration
  (`invalidate(artifact_uri, changed_at)`). Cleared by the next
  corroboration. This is the signature move: claims about artifacts go
  suspect the moment the artifact changes.

Nothing is silently deleted. Claims fall out of briefings by rank; only
governance retires them.

### Scope

```
Scope { space: str, segment: str | null }
```

`space` is the consumer's boundary (a workspace id, an org id);
`segment` optionally narrows (a folder, a topic area, a relationship key
like `"pair:<addrA>:<addrB>"` with addresses sorted). Private staging is
`segment = "staging:<address>"`. The standard treats scopes as opaque
strings; consumers enforce access control. The library only guarantees:
queries never cross `space`.

### Governance: promotion, verdicts, retirement

Promotion of knowledge into a scope is **a proposal**, reviewed under a
policy the consumer configures:

```
Promotion {
  id, scope, claim (full signed claim), proposer, status:
  "pending" | "accepted" | "rejected", created_at, decided_at
}
ReviewVerdict {  # signed, context "verdict"
  promotion_id, verdict: "approve" | "reject", basis, author, issued_at
}
Policy {
  mode: "auto" | "review"
  required_approvals: int        # review mode
  protected_topics: [str]        # topics that force review even in auto mode
}
Retirement {  # signed, context "retirement" — the ONLY way a claim leaves
  claim_id, reason, author, issued_at
}
```

- `auto` mode: promotion accepts immediately UNLESS any claim topic matches
  `protected_topics` (then it queues for review).
- `review` mode: needs `required_approvals` distinct approving identities;
  any reject → rejected. Proposer cannot review their own promotion.
- Contradiction pileups emit a `ConflictEvent` (claim_id, contradiction
  count crossing a threshold) the consumer can surface to humans.
- All governance records are append-only and queryable — the audit trail is
  the data structure.

### Retrieval: assembled briefings

```
brief(scope, task: str, topics=[], refs=[], limit=12) -> Briefing
Briefing {
  items: [{
    claim, confidence, staleness_seconds, suspect,
    corroborations, contradictions, score,
    verify_first: bool     # nudge: load-bearing + (suspect or stale)
  }],
  conflicts: [claim_id]    # actively contradicted claims relevant to task
}
```

Ranking is deterministic and model-free: lexical relevance of `task` against
statement+topics (FTS where available, token overlap fallback) × confidence
× freshness damping; `refs` overlap is a strong boost (claims about the
artifact you're touching). `verify_first` fires when a claim ranks in the
top of the briefing but is suspect or stale beyond a scope-configurable
horizon. Retired and superseded claims never appear; actively contradicted
claims appear WITH their contradictions visible, never hidden.

## Signing domain

Own domain, never reusing fg-agent-id's: `DOMAIN = "fg-agent-knowledge/v1"`,
same wire construction as fg-agent-id (`uint16be(len(tag)) || tag ||
canonical_json(body)`), implemented over `fg_agent_id.canonical_json` and
`KeyPair`/`verify` primitives. Contexts: `claim`, `endorsement`, `verdict`,
`retirement`. Never sign a bare payload; never reuse a context.

## Package layout (reference implementation, Python ≥3.11)

```
src/fg_agent_knowledge/
  __init__.py     # public API surface
  errors.py       # KnowledgeError hierarchy (ValidationError, SignatureError,
                  #   NotFoundError, PolicyError, ScopeError)
  signing.py      # DOMAIN, contexts, signing_input/sign/verify (wraps fg_agent_id)
  types.py        # Scope, ArtifactRef, frozen dataclasses for all bodies
  claim.py        # build/sign/verify/claim_id; supersedes chain checks
  endorsement.py  # corroborate/contradict records
  scoring.py      # confidence, staleness, suspect, briefing score (pure functions)
  text.py         # tokenize + stopwords + Porter stemmer (retrieval analysis)
  store.py        # Store protocol (persistence only) + SQLite + InMemory
  retrievers.py   # Retriever seam + KeywordRetriever (BM25); bring-your-own
  governance.py   # Promotion lifecycle, Policy, verdicts, retirement, ConflictEvent
  retrieval.py    # brief() assembly: trust + retriever relevance → ranked briefing
  knowledge.py    # KnowledgeBase facade: capture/propose/endorse/brief/invalidate
                  #   — the one class a consumer touches
tests/            # pytest; hermetic; vectors test for signing stability
spec/SPEC.md      # normative wire formats (kept in lockstep with code)
```

Dependencies: `fg-agent-id` only (sqlite3 is stdlib). Dev: pytest.

### KnowledgeBase facade (consumer API)

```python
kb = KnowledgeBase(store)                      # store = SQLiteStore(path) | InMemoryStore()
kb.observe(scope, keys_or_addr, kind, content, refs=[], episodes cheap)
kb.propose(scope, keys, kind, statement, topics, refs, episodes, supersedes=None) -> Promotion
kb.review(promotion_id, keys, verdict, basis="") -> Promotion
kb.endorse(claim_id, keys, verdict, basis="", episodes=[]) -> Endorsement
kb.retire(claim_id, keys, reason) -> Retirement
kb.invalidate(scope, artifact_uri, changed_at) -> [claim_id]   # marks suspect
kb.brief(scope, task, topics=[], refs=[], limit=12) -> Briefing
kb.claim(claim_id) / kb.claims(scope, ...) / kb.promotions(scope, status=...)
kb.set_policy(scope, policy) / kb.policy(scope)
kb.conflicts(scope) -> [ConflictEvent]
```

All write paths verify signatures and reject cross-`space` references.
Authorization beyond that (who MAY review, who MAY set policy) is the
consumer's job — the library records identities faithfully and enforces
protocol rules (no self-review, distinct approvers), not org charts.

## Guarantees the tests pin down

- Signing inputs and claim_ids are byte-stable across runs (golden vectors in
  `spec/vectors.json`, generated by `spec/generate_vectors.py`).
- The full lifecycle works end to end: observe → propose → review → brief;
  contradiction lowers confidence and surfaces in briefings; corroboration
  resets staleness; artifact invalidation flips `suspect` and `verify_first`;
  retirement removes a claim from briefings but never from the store;
  a supersedes chain hides the old claim from briefings.
- Negative paths hold: tampered signatures are rejected, self-review is
  rejected, duplicate promotion of an identical body is idempotent (same
  claim_id), cross-space episode refs are rejected, and floats in any signed
  body are rejected (canonical JSON rule inherited from fg-agent-id).

## Explicit non-goals (v1)

- No consolidation engine (an LLM-run consolidator is a CONSUMER of this
  API: reads episodes, calls `propose`). A sketch lives in
  `examples/consolidator.md`; the package itself never calls a model.
- No transport (AMP integration is a consumer concern; the records are
  transport-agnostic signed JSON).
- No *built-in* embeddings; semantic/vector search is a consumer-supplied
  `Retriever` behind the retrieval seam. The reference is `KeywordRetriever`
  (BM25 over Porter-stemmed tokens).
- No federation/knowledge packs (v2: signed export bundles).
