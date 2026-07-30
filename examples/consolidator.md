# Consolidation is a consumer, not a feature

The standard deliberately ships no consolidation engine. An LLM-run
consolidator is a plain CONSUMER of this API:

1. Read recent episodes for a scope (`store.episode(...)` / your own capture
   feed) — they are cheap, unsigned staging data.
2. Distill: decide which observations generalize into a claim worth signing.
   This is where your model, prompts, and judgment live — outside the wire
   standard.
3. Call `kb.propose(scope, keys, kind, statement, topics, refs, episodes=...)`
   with the episode ids as pedigree. The scope's policy — not the
   consolidator — decides whether the claim needs review.
4. On re-encounter, call `kb.endorse(claim_id, keys, "corroborate", ...)`
   instead of proposing a near-duplicate; on disagreement, `"contradict"`.

Because claims are content-addressed and promotions idempotent, a naive
consolidator that re-derives the same statement does no harm. Because
promotion is governed, an over-eager one cannot pollute a protected scope.
