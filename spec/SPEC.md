# fg-agent-knowledge v1 — Wire Specification

Normative wire formats for the shared-knowledge standard. The key words MUST,
MUST NOT, SHOULD, and MAY are to be interpreted as in RFC 2119. Golden vectors
live in `vectors.json` (regenerate with `python generate_vectors.py`).

The standard is model-free: no LLM appears anywhere in the protocol.
Briefings are assembled, never generated.

## 1. Encoding and signing

All signed bodies are JSON objects serialized with fg-agent-id canonical JSON:
sorted keys, no insignificant whitespace, UTF-8, NFC-normalized, no
NaN/Infinity, **no floats anywhere** (use integers or strings). Timestamps are
RFC 3339 UTC with exactly three fractional digits and a `Z` suffix
(`2026-01-01T00:00:00.000Z`).

Signatures are Ed25519 over a domain-separated signing input:

```
DOMAIN = "fg-agent-knowledge/v1"
tag    = DOMAIN || "/" || context            (UTF-8)
input  = uint16be(len(tag)) || tag || canonical_json(body)
```

Contexts: `claim`, `endorsement`, `verdict`, `retirement`. A context MUST
never be reused across record types and a bare payload MUST never be signed.
Signatures are canonical base64: one signature has exactly one wire form;
verifiers MUST reject non-canonical spellings.

Authors are self-certifying fg-agent-id addresses (`amp:key:<base58>`); a
record verifies against nothing but its `author` field.

## 2. Scope

```json
{"space": "<opaque>", "segment": "<opaque> | null"}
```

`space` is the hard boundary: queries and references MUST NOT cross it.
`segment` optionally narrows (a folder, a topic area, `"pair:<addrA>:<addrB>"`
with addresses sorted, `"staging:<address>"` for private staging). Scopes are
opaque to the library; consumers enforce access control.

## 3. Episode (unsigned)

Cheap, append-only capture; fuel for consolidation, never retrieved by
briefings. `kind` ∈ `observation | outcome | correction | surprise`.
Episodes carry `id` (uuid), `scope`, `observer` (address), `content`, optional
`refs`, `occurred_at`.

## 4. Claim

Signed body (context `claim`):

```json
{
  "spec": "fg-agent-knowledge/v1",
  "scope": {"space": "...", "segment": null},
  "kind": "semantic | procedural | relational",
  "statement": "<plain text>",
  "topics": ["lowercase", "sorted", "deduped"],
  "refs": [{"uri": "<opaque>", "kind": "<opaque> | null"}],
  "episodes": ["<episode uuid>"],
  "author": "amp:key:...",
  "asserted_at": "RFC3339",
  "supersedes": "<claim_id> | null"
}
```

- `claim_id = lowercase hex sha256(signing_input("claim", body))` — derived,
  never chosen. Two identical bodies are one claim; duplicate proposals are
  idempotent.
- Bodies are immutable. Revision = a new claim naming the old one in
  `supersedes`; the superseded claim MUST reference the same `space`.
- `episodes` MUST reference episodes in the same `space`.
- Verifiers MUST check the signature against `author` and the `claim_id`
  against the body.

## 5. Endorsement

Signed body (context `endorsement`): `spec`, `claim_id`, `verdict`
(`corroborate | contradict`), `basis` (free text), `episodes` (same-space),
`author`, `issued_at`.

A contradiction attaches to the claim and lowers derived confidence; it MUST
NOT edit or remove anything. Authors MAY endorse their own claims
(re-encounters are evidence); standing counts distinct identities, so
self-corroboration never stacks.

## 6. Derived standing: confidence ⊥ staleness ⊥ suspect

All three are derived at read time from the record and MUST NOT be persisted
as authoritative.

- **Identity positions**: an identity's standing position is its most recent
  endorsement of the claim; positions supersede, they do not accumulate.
- **confidence** ∈ [0,1]: reference formula `(1 + c) / (2 + c + k·d)` with
  `c` = distinct corroborating identities, `d` = distinct contradicting
  identities, `k` = contradiction weight (reference default 2).
  Implementations MAY substitute a formula; the FIELDS are the standard.
- **staleness_seconds**: whole seconds since the last corroborating
  encounter; `asserted_at` counts as the first. Corroboration resets it;
  contradictions MUST NOT touch it.
- **suspect**: true when any `refs` uri has a reported change
  (`invalidate(uri, changed_at)`) newer than the last corroborating
  encounter. Cleared by the next corroboration.

## 7. Governance

**Promotion** — knowledge enters a scope by proposal:
`{id (uuid), scope, claim, proposer, status: pending|accepted|rejected,
created_at, decided_at}`. Status moves out of `pending` exactly once.

**Policy** per scope: `mode: auto|review`, `required_approvals` (≥1),
`protected_topics` (lowercase), and optionally a staleness horizon for
briefings. Default: `auto`, no protected topics.

- `auto`: accept immediately UNLESS any claim topic is protected → pending.
- `review`: pending until `required_approvals` distinct approving identities;
  any reject → rejected.

**ReviewVerdict** (signed, context `verdict`): `spec`, `promotion_id`,
`verdict: approve|reject`, `basis`, `author`, `issued_at`. Rules:
the proposer MUST NOT review their own promotion; one verdict per identity
per promotion; verdicts on decided promotions MUST be rejected. This last
rule MUST be enforced atomically — a verdict is admitted only while the
promotion is still `pending`, checked and stored under one lock — so that
under concurrent review no verdict can be recorded after the decision and the
status transition happens exactly once.

**Retirement** (signed, context `retirement`): `spec`, `claim_id`, `reason`,
`author`, `issued_at`. The ONLY way a claim leaves briefings; the record
itself is never deleted. A retirement MUST be authored by the claim's own
author — only the author may retire their claim. Moderated (owner/reviewer)
retirement is a consumer-level governance flow (e.g. a retirement proposal),
never a raw library capability, because unrestricted retirement is a
hidden-censorship primitive.

**Supersession**: a claim's `supersedes` MUST reference a claim by the SAME
author in the same space. Cross-author disagreement MUST use a contradiction
endorsement (which lowers confidence while keeping the claim visible), never
supersession (which hides it) — otherwise supersession is an equivalent
censorship primitive.

**Cross-agent "merge" means governed convergence, not structural merge.** A
sibling private-memory standard (fg-agent-memory) delegates "cross-agent
merge" to this layer. That delegation is fulfilled by *convergence*, not by a
merge primitive: this standard deliberately has no operation that fuses two
different authors' claims into one record. Two agents asserting near-duplicate
claims keep both records, each with its own author and pedigree; contradiction
endorsements, confidence, and governed promotion sort them over time. A private
memory rule crosses into shared knowledge as a NEW claim proposed by the
promoting agent (a consumer-side promoter, not a wire operation), never by
transplanting another agent's record. Any implementation that structurally
merges across authors is reintroducing the silent-overwrite this layer exists
to prevent.

**Timestamps**: `asserted_at` / `issued_at` are caller-supplied and feed the
derived standing axes, so a conforming ingest MUST reject any signed record
whose timestamp is more than a small clock-skew window in the future
(reference: 300s). This prevents future-dating to pin staleness at zero or to
win the "latest position per identity" rule.

**Text bounds**: every signed text field (`statement`, `basis`, `reason`,
episode `content`) MUST be bounded (reference: 65536 bytes) to deny
storage/signing amplification.

**ConflictEvent**: when distinct contradicting identities on a claim reach
the threshold (reference: 2), implementations SHOULD surface
`{claim_id, scope, contradictions}` to humans.

All governance records are append-only and queryable — the audit trail is the
data structure. The library enforces protocol rules, not org charts: WHO may
review or set policy is the consumer's concern.

### 7.1 Consumer security obligations (NORMATIVE for consumers)

The library counts *distinct identities*; fg-agent-id addresses are free to
mint, so these guarantees hold ONLY if the consumer controls identity
admission:

- **Sybil resistance.** `required_approvals=N` and corroboration/contradiction
  counts mean "N distinct keys," NOT "N independent principals." A consumer
  MUST gate which identities may propose/review/endorse in a scope (e.g.
  workspace membership + grants). Absent that gate, quorum and standing carry
  no security value.
- **Policy tightening is not retroactive.** A claim accepted under a lenient
  policy stays accepted after its topic later becomes protected; status moves
  out of `pending` exactly once. Consumers needing to re-gate existing
  knowledge MUST drive it explicitly (e.g. retire + re-propose).
- **Rejected promotions are re-proposable.** The same body MAY be proposed
  again after rejection (a fresh appeal with a new audit record); consumers
  that need permanent rejection or review-spam limits MUST enforce them.

## 8. Briefing contract

```
brief(scope, task, topics=[], refs=[], limit=12) -> Briefing
```

Final rank = **relevance × confidence × freshness damping**
`horizon/(horizon+staleness)`, where overlap with `refs` is a strong boost.
Claims sharing the scope's `space` with segment equal to the query's segment or
`null` are eligible.

**Relevance is supplied by a Retriever (the second infra seam) — see §10.** The
core owns trust (confidence/staleness/suspect) and assembly; the Retriever owns
only how well a claim matches `task`+`topics`. The reference Retriever
(`KeywordRetriever`) is deterministic and model-free: **Okapi BM25** over
Porter-stemmed, stopword-filtered tokens of statement+topics. A consumer MAY
supply another Retriever (e.g. semantic/vector); relevance is not part of the
portable, normative core.

- Retired and superseded claims MUST NOT appear.
- Actively contradicted claims MUST appear with their contradictions visible
  (`contradictions` count and the briefing-level `conflicts` list), never
  hidden.
- `verify_first` MUST be set on items that made the briefing while suspect or
  staler than the scope's horizon (reference default: 7 days).
- Each item carries: `claim`, `confidence`, `staleness_seconds`, `suspect`,
  `corroborations`, `contradictions`, `score`, `verify_first`.

## 9. Infrastructure seams (bring your own)

A knowledge base is defined by the normative core — claim format + signing,
the trust model (confidence ⊥ staleness ⊥ suspect), the verbs, and governance.
Everything a deployment's infrastructure varies is a pluggable adapter behind a
small interface, so the same signed claims interoperate across very different
stacks:

- **Store** (persistence). Append-only record shelf: save/fetch claims,
  endorsements, promotions, verdicts, retirements, invalidations, policy.
  Reference: SQLite and in-memory. Bring Postgres, a document store, anything.
- **Retriever** (relevance). `rank(query, candidates) -> Ranking` returns a
  relevance score in `[0,1]` per candidate claim (`query_empty` ⇒ the core
  ranks by trust alone). Optional `index(claim)` / `remove(claim_id)` write
  hooks let a stateful retriever maintain an index as claims are accepted and
  retired. Reference: `KeywordRetriever` (BM25). Bring a semantic/vector
  retriever — it MAY use a model; the core stays model-free.

What stays fixed (never an adapter): the claim wire format, signing, the trust
semantics, and the governance rules. That fixed part is what makes a claim
portable; storage and relevance are local concerns.

## 10. Non-goals (v1)

No consolidation engine, no transport, no federation, and no *built-in*
embeddings — the core ships only the reference BM25 retriever. Semantic/vector
search is explicitly supported, but as a consumer-supplied `Retriever` behind
the §9 seam, not baked into the model-free core.
