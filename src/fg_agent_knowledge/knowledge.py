"""The KnowledgeBase facade — the one class a consumer touches.

Every write path verifies signatures and rejects cross-``space`` references.
Bodies are immutable and storage is append-only; confidence, staleness, and
suspect are derived at read time, never persisted as authoritative.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fg_agent_id import KeyPair, address_from_signing_key

from . import governance
from .claim import build_claim, verify_claim
from .endorsement import build_endorsement, verify_endorsement
from .errors import NotFoundError, PolicyError, ScopeError, ValidationError
from .retrieval import brief as assemble_brief
from .retrievers import KeywordRetriever, Retriever
from .scoring import CONFLICT_CONTRADICTION_THRESHOLD, SourceWeight, contradictors
from .store import Store
from .types import (
    ArtifactRef,
    Briefing,
    Claim,
    ClaimKind,
    ConflictEvent,
    Endorsement,
    EndorsementVerdict,
    Episode,
    EpisodeKind,
    Policy,
    Promotion,
    PromotionStatus,
    Retirement,
    ReviewDecision,
    Scope,
)


class KnowledgeBase:
    """Shared knowledge for one deployment: capture, propose, endorse,
    brief, invalidate — over any :class:`~fg_agent_knowledge.store.Store`."""

    def __init__(
        self,
        store: Store,
        retriever: Retriever | None = None,
        *,
        default_author: KeyPair | None = None,
    ) -> None:
        """``default_author`` is the identity this handle acts as: when set,
        the signing verbs (``observe`` / ``propose`` / ``review`` /
        ``endorse`` / ``retire``) may omit their keys argument. An explicit
        keys argument always wins. The natural pattern is one handle per
        acting agent; governance guards (self-review, author-only retire)
        compare addresses at call time, so a default changes nothing about
        what is allowed."""
        self._store = store
        self._retriever = retriever if retriever is not None else KeywordRetriever()
        self._default_author = default_author

    def _author(self, keys: KeyPair | None) -> KeyPair:
        if keys is not None:
            return keys
        if self._default_author is None:
            raise ValidationError(
                "no author: pass keys explicitly or construct "
                "KnowledgeBase(store, default_author=...)"
            )
        return self._default_author

    # -- capture ---------------------------------------------------------

    def observe(
        self,
        scope: Scope,
        observer: KeyPair | str | None = None,
        kind: EpisodeKind | None = None,
        content: str | None = None,
        refs: tuple[ArtifactRef, ...] = (),
        occurred_at: datetime | None = None,
    ) -> Episode:
        """Record a cheap, unsigned episode. No judgment at write time —
        quality lives in promotion. ``observer`` may be omitted when the
        handle carries a ``default_author``."""
        kind = _require("kind", kind)
        content = _require("content", content)
        if observer is None:
            observer = self._author(None)
        episode = Episode(
            id=str(uuid.uuid4()),
            scope=scope,
            observer=_address_of(observer),
            kind=kind,
            content=content,
            occurred_at=occurred_at if occurred_at is not None else datetime.now(UTC),
            refs=tuple(refs),
        )
        self._store.add_episode(episode)
        return episode

    # -- knowledge -------------------------------------------------------

    def propose(
        self,
        scope: Scope,
        keys: KeyPair | None = None,
        kind: ClaimKind | None = None,
        statement: str | None = None,
        topics: tuple[str, ...] = (),
        refs: tuple[ArtifactRef, ...] = (),
        episodes: tuple[str, ...] = (),
        supersedes: str | None = None,
        asserted_at: datetime | None = None,
    ) -> Promotion:
        """Sign a claim and propose it into ``scope`` under the scope's
        policy. Proposing an identical body again is idempotent — same
        claim_id, same promotion. ``topics=()`` is accepted: the claim is then
        ranked on its statement terms alone and forgoes the retriever's
        topic-term weighting in briefings. ``keys`` may be omitted when the
        handle carries a ``default_author``."""
        keys = self._author(keys)
        kind = _require("kind", kind)
        statement = _require("statement", statement)
        self._check_episode_refs(scope, episodes)
        _reject_future("asserted_at", asserted_at)
        if supersedes is not None:
            superseded = self._require_claim(supersedes)
            if superseded.body.scope.space != scope.space:
                raise ScopeError("supersedes must reference a claim in the same space")
            # Superseding hides the old claim from briefings, so only its own
            # author may revise it. Cross-author disagreement goes through
            # `endorse(..., "contradict")`, which lowers confidence while
            # keeping the claim visible — never silent hiding.
            if superseded.body.author != _address_of(keys):
                raise PolicyError("only a claim's author may supersede it")
        claim = build_claim(
            keys, scope, kind, statement, topics, refs, episodes,
            asserted_at=asserted_at, supersedes=supersedes,
        )
        verify_claim(claim)
        for existing in self._store.promotions(scope.space):
            if existing.claim.claim_id == claim.claim_id and existing.status != "rejected":
                return existing
        promotion = governance.open_promotion(
            scope, claim, claim.body.author, self.policy(scope)
        )
        self._store.add_promotion(promotion)
        if promotion.status == "accepted":
            self._retriever.index(claim)
        return promotion

    def review(
        self,
        promotion_id: str,
        keys: KeyPair | None = None,
        verdict: ReviewDecision | None = None,
        basis: str = "",
    ) -> Promotion:
        """Cast a signed review verdict; the promotion decides itself when
        the policy's bar is met. Self-review and repeat reviewers are
        protocol violations. ``keys`` may be omitted when the handle carries
        a ``default_author`` (the self-review guard still applies)."""
        keys = self._author(keys)
        verdict = _require("verdict", verdict)
        promotion = self._store.promotion(promotion_id)
        if promotion is None:
            raise NotFoundError(f"unknown promotion: {promotion_id}")
        prior = self._store.verdicts(promotion_id)
        reviewer = _address_of(keys)
        governance.check_reviewable(promotion, reviewer, prior)
        record = governance.build_verdict(keys, promotion_id, verdict, basis)
        governance.verify_verdict(record)
        # The store admits the verdict atomically only while the promotion is
        # still pending, so a verdict can never land on an already-decided
        # promotion under a race (the stale snapshot above may say pending).
        if not self._store.add_verdict(record):
            current = self._store.promotion(promotion_id)
            status = current.status if current else "decided"
            raise PolicyError(f"promotion {promotion_id} is already {status}")
        # Re-read the full verdict set AFTER our own admitted write so a
        # concurrent reviewer's verdict is never missed; the last writer
        # decides on the complete set. `decide_promotion`'s pending-guard makes
        # the transition itself single-shot.
        all_verdicts = self._store.verdicts(promotion_id)
        outcome = governance.decide(
            promotion, all_verdicts, self.policy(promotion.scope)
        )
        if outcome is not None:
            self._store.decide_promotion(promotion_id, outcome, datetime.now(UTC))
            if outcome == "accepted":
                self._retriever.index(promotion.claim)
        refreshed = self._store.promotion(promotion_id)
        assert refreshed is not None
        return refreshed

    def endorse(
        self,
        claim_id: str,
        keys: KeyPair | None = None,
        verdict: EndorsementVerdict | None = None,
        basis: str = "",
        episodes: tuple[str, ...] = (),
        issued_at: datetime | None = None,
    ) -> Endorsement:
        """Corroborate or contradict a claim. A contradiction attaches to the
        claim and lowers derived confidence — it never edits anything.
        Unlike review, self-endorsement (including self-corroboration) is
        permitted by design: SPEC §7.1 pushes Sybil-resistance to the
        consumer, and derived confidence is advisory, not a governance gate.
        ``keys`` may be omitted when the handle carries a ``default_author``."""
        keys = self._author(keys)
        verdict = _require("verdict", verdict)
        claim = self._require_claim(claim_id)
        self._check_episode_refs(claim.body.scope, episodes)
        _reject_future("issued_at", issued_at)
        endorsement = build_endorsement(keys, claim_id, verdict, basis, episodes, issued_at)
        verify_endorsement(endorsement)
        self._store.add_endorsement(endorsement)
        return endorsement

    def retire(
        self, claim_id: str, keys: KeyPair | None = None, reason: str | None = None
    ) -> Retirement:
        """The only way a claim leaves briefings for good. The record stays —
        nothing is silently deleted. Only the claim's author may retire it;
        moderated (owner/reviewer) retirement is a consumer governance flow
        layered on top, never a raw capability of the shared library.
        ``keys`` may be omitted when the handle carries a ``default_author``."""
        keys = self._author(keys)
        reason = _require("reason", reason)
        claim = self._require_claim(claim_id)
        if claim.body.author != _address_of(keys):
            raise PolicyError("only a claim's author may retire it")
        retirement = governance.build_retirement(keys, claim_id, reason)
        governance.verify_retirement(retirement)
        self._store.add_retirement(retirement)
        self._retriever.remove(claim_id)
        return retirement

    def invalidate(
        self, scope: Scope, artifact_uri: str, changed_at: datetime
    ) -> list[str]:
        """An artifact changed: every claim in the space about it goes
        suspect until its next corroboration. Returns the affected claim ids."""
        self._store.record_invalidation(scope.space, artifact_uri, changed_at)
        return sorted(
            c.claim_id
            for c in self._store.claims(scope.space)
            if any(r.uri == artifact_uri for r in c.body.refs)
        )

    # -- retrieval -------------------------------------------------------

    def brief(
        self,
        scope: Scope,
        task: str,
        topics: tuple[str, ...] = (),
        refs: tuple[ArtifactRef, ...] = (),
        limit: int | None = None,
        source_weight: SourceWeight | None = None,
    ) -> Briefing:
        """Assemble (never generate) a ranked, attributed briefing.

        ``source_weight`` is the optional per-source trust seam (see
        :func:`~fg_agent_knowledge.retrieval.brief`); omit for equal-vote
        confidence, supply for reputation/stake-weighted trust."""
        kwargs: dict = {} if limit is None else {"limit": limit}
        if source_weight is not None:
            kwargs["source_weight"] = source_weight
        return assemble_brief(self._store, scope, task, topics, refs,
                              retriever=self._retriever, **kwargs)

    def claim(self, claim_id: str) -> Claim:
        return self._require_claim(claim_id)

    def claims(self, scope: Scope) -> list[Claim]:
        return [
            c for c in self._store.claims(scope.space)
            if scope.segment is None or c.body.scope.segment == scope.segment
        ]

    def promotions(
        self, scope: Scope, status: PromotionStatus | None = None
    ) -> list[Promotion]:
        return self._store.promotions(scope.space, status)

    def conflicts(self, scope: Scope) -> list[ConflictEvent]:
        """Claims whose contradiction count crossed the threshold — surface
        these to humans; the library never auto-resolves a fight."""
        events = []
        for claim in self._store.claims(scope.space):
            count = len(contradictors(self._store.endorsements(claim.claim_id)))
            if count >= CONFLICT_CONTRADICTION_THRESHOLD:
                events.append(ConflictEvent(
                    claim_id=claim.claim_id, scope=claim.body.scope,
                    contradictions=count,
                ))
        return sorted(events, key=lambda e: e.claim_id)

    # -- policy ----------------------------------------------------------

    def set_policy(self, scope: Scope, policy: Policy) -> None:
        self._store.set_policy(scope, policy)

    def policy(self, scope: Scope) -> Policy:
        return self._store.policy(scope) or governance.DEFAULT_POLICY

    # -- internals -------------------------------------------------------

    def _require_claim(self, claim_id: str) -> Claim:
        claim = self._store.claim(claim_id)
        if claim is None:
            raise NotFoundError(f"unknown claim: {claim_id}")
        return claim

    def _check_episode_refs(self, scope: Scope, episodes: tuple[str, ...]) -> None:
        for episode_id in episodes:
            episode = self._store.episode(episode_id)
            if episode is None:
                raise NotFoundError(f"unknown episode: {episode_id}")
            if episode.scope.space != scope.space:
                raise ScopeError(
                    "episode references must not cross the space boundary"
                )


def _require(name: str, value):
    """Runtime guard for parameters whose ``None`` default exists only so
    ``keys`` can be omitted ahead of them (Python forbids a default-free
    parameter after a defaulted one). They remain required."""
    if value is None:
        raise ValidationError(f"{name} is required")
    return value


def _address_of(who: KeyPair | str) -> str:
    if isinstance(who, str):
        return who
    return address_from_signing_key(who.public.signing)


# Confidence and staleness are derived from caller-supplied timestamps, so a
# future-dated record could pin staleness at zero forever or leapfrog the
# "latest position per identity" rule. Reject timestamps beyond a small skew
# window; honest clock drift is tolerated, deliberate future-dating is not.
MAX_CLOCK_SKEW_SECONDS = 300


def _reject_future(name: str, ts: datetime | None) -> None:
    if ts is None:
        return
    skew = (ts - datetime.now(UTC)).total_seconds()
    if skew > MAX_CLOCK_SKEW_SECONDS:
        raise ValidationError(f"{name} is too far in the future")
