"""Storage: a small protocol, a SQLite reference, an in-memory twin.

Stores are dumb on purpose — append-only record shelves. Persistence only:
retrieval/ranking is a :class:`~fg_agent_knowledge.retrievers.Retriever`'s job
and confidence, staleness, and suspect are derived at read time by the layers
above; a store never persists them as authoritative. The only mutation a store
ever performs is deciding a pending promotion, a one-way status transition on
an audit record.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime
from typing import Protocol

from fg_agent_id.serde import canonical_timestamp, parse_datetime

from .serde import (
    claim_from_json,
    claim_to_json,
    endorsement_from_json,
    endorsement_to_json,
)
from .types import (
    ArtifactRef,
    Claim,
    Endorsement,
    Episode,
    Policy,
    Promotion,
    PromotionStatus,
    Retirement,
    RetirementBody,
    ReviewVerdict,
    ReviewVerdictBody,
    Scope,
)


class Store(Protocol):
    """What a storage engine must offer. Engines compete; this interface is
    the standard's floor."""

    def add_episode(self, episode: Episode) -> None: ...
    def episode(self, episode_id: str) -> Episode | None: ...
    def add_claim(self, claim: Claim) -> None: ...
    def claim(self, claim_id: str) -> Claim | None: ...
    def claims(self, space: str) -> list[Claim]: ...
    def add_endorsement(self, endorsement: Endorsement) -> None: ...
    def endorsements(self, claim_id: str) -> list[Endorsement]: ...
    def endorsements_for(
        self, claim_ids: Iterable[str]
    ) -> dict[str, list[Endorsement]]:
        """Endorsements for many claims in one call — the batched form that
        keeps a briefing over N claims from doing N separate queries (the read
        path's N+1). Every requested id appears in the result, empty if it has
        no endorsements."""
        ...
    def add_promotion(self, promotion: Promotion) -> None: ...
    def promotion(self, promotion_id: str) -> Promotion | None: ...
    def promotions(self, space: str, status: PromotionStatus | None = None) -> list[Promotion]: ...
    def decide_promotion(self, promotion_id: str, status: PromotionStatus, decided_at: datetime) -> None: ...
    def add_verdict(self, verdict: ReviewVerdict) -> bool:
        """Admit a verdict atomically IFF its promotion is still ``pending``.
        Returns ``True`` if admitted, ``False`` if the promotion was already
        decided (the verdict is not stored) — so a verdict can never land on a
        decided promotion regardless of concurrency."""
        ...
    def verdicts(self, promotion_id: str) -> list[ReviewVerdict]: ...
    def add_retirement(self, retirement: Retirement) -> None: ...
    def retirement(self, claim_id: str) -> Retirement | None: ...
    def record_invalidation(self, space: str, uri: str, changed_at: datetime) -> None: ...
    def invalidations(self, space: str) -> dict[str, datetime]: ...
    def set_policy(self, scope: Scope, policy: Policy) -> None: ...
    def policy(self, scope: Scope) -> Policy | None: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY, space TEXT NOT NULL, segment TEXT, observer TEXT NOT NULL,
  kind TEXT NOT NULL, content TEXT NOT NULL, refs TEXT NOT NULL, occurred_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims (
  claim_id TEXT PRIMARY KEY, space TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS endorsements (
  rowid_ord INTEGER PRIMARY KEY AUTOINCREMENT, claim_id TEXT NOT NULL, record TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS promotions (
  id TEXT PRIMARY KEY, space TEXT NOT NULL, claim_id TEXT NOT NULL, proposer TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT);
CREATE TABLE IF NOT EXISTS verdicts (
  rowid_ord INTEGER PRIMARY KEY AUTOINCREMENT, promotion_id TEXT NOT NULL,
  verdict TEXT NOT NULL, basis TEXT NOT NULL, author TEXT NOT NULL,
  issued_at TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retirements (
  claim_id TEXT PRIMARY KEY, reason TEXT NOT NULL, author TEXT NOT NULL,
  issued_at TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS invalidations (
  space TEXT NOT NULL, uri TEXT NOT NULL, changed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policies (
  space TEXT NOT NULL, segment TEXT NOT NULL, record TEXT NOT NULL,
  PRIMARY KEY (space, segment));
CREATE INDEX IF NOT EXISTS idx_claims_space ON claims(space);
CREATE INDEX IF NOT EXISTS idx_endorsements_claim ON endorsements(claim_id);
CREATE INDEX IF NOT EXISTS idx_promotions_space ON promotions(space);
"""


class SQLiteStore:
    """The reference store: single file, WAL. Persistence only — ranking is a
    :class:`~fg_agent_knowledge.retrievers.Retriever`'s job, not the store's."""

    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def add_episode(self, episode: Episode) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO episodes VALUES (?,?,?,?,?,?,?,?)",
                (episode.id, episode.scope.space, episode.scope.segment,
                 episode.observer, episode.kind, episode.content,
                 json.dumps([r.body() for r in episode.refs]),
                 canonical_timestamp(episode.occurred_at)),
            )
            self._db.commit()

    def episode(self, episode_id: str) -> Episode | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, space, segment, observer, kind, content, refs, occurred_at "
                "FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if row is None:
            return None
        return Episode(
            id=row[0], scope=Scope(row[1], row[2]), observer=row[3], kind=row[4],
            content=row[5], occurred_at=parse_datetime("occurred_at", row[7]),
            refs=tuple(ArtifactRef(r["uri"], r["kind"]) for r in json.loads(row[6])),
        )

    def add_claim(self, claim: Claim) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO claims VALUES (?,?,?)",
                (claim.claim_id, claim.body.scope.space, claim_to_json(claim)))
            self._db.commit()

    def claim(self, claim_id: str) -> Claim | None:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        return claim_from_json(row[0]) if row else None

    def claims(self, space: str) -> list[Claim]:
        with self._lock:
            rows = self._db.execute(
                "SELECT record FROM claims WHERE space=?", (space,)).fetchall()
        return [claim_from_json(r[0]) for r in rows]

    def add_endorsement(self, endorsement: Endorsement) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO endorsements (claim_id, record) VALUES (?,?)",
                (endorsement.body.claim_id, endorsement_to_json(endorsement)))
            self._db.commit()

    def endorsements(self, claim_id: str) -> list[Endorsement]:
        with self._lock:
            rows = self._db.execute(
                "SELECT record FROM endorsements WHERE claim_id=? ORDER BY rowid_ord",
                (claim_id,)).fetchall()
        return [endorsement_from_json(r[0]) for r in rows]

    def endorsements_for(
        self, claim_ids: Iterable[str]
    ) -> dict[str, list[Endorsement]]:
        ids = list(dict.fromkeys(claim_ids))
        result: dict[str, list[Endorsement]] = {cid: [] for cid in ids}
        if not ids:
            return result
        # Chunk the IN-list to stay under SQLite's bound-parameter limit while
        # still collapsing N per-claim queries into a handful of batched ones.
        chunk = 500
        for start in range(0, len(ids), chunk):
            batch = ids[start:start + chunk]
            placeholders = ",".join("?" for _ in batch)
            with self._lock:
                rows = self._db.execute(
                    f"SELECT claim_id, record FROM endorsements"
                    f" WHERE claim_id IN ({placeholders}) ORDER BY rowid_ord",
                    batch,
                ).fetchall()
            for claim_id, record in rows:
                result[claim_id].append(endorsement_from_json(record))
        return result

    def add_promotion(self, promotion: Promotion) -> None:
        self.add_claim(promotion.claim)
        with self._lock:
            self._db.execute(
                "INSERT INTO promotions VALUES (?,?,?,?,?,?,?)",
                (promotion.id, promotion.scope.space, promotion.claim.claim_id,
                 promotion.proposer, promotion.status,
                 canonical_timestamp(promotion.created_at),
                 canonical_timestamp(promotion.decided_at) if promotion.decided_at else None))
            self._db.commit()

    def _promotion_from_row(self, row: tuple) -> Promotion:
        claim = self.claim(row[2])
        assert claim is not None  # promotions always store their claim first
        return Promotion(
            id=row[0], scope=claim.body.scope, claim=claim, proposer=row[3],
            status=row[4], created_at=parse_datetime("created_at", row[5]),
            decided_at=parse_datetime("decided_at", row[6]) if row[6] else None)

    def promotion(self, promotion_id: str) -> Promotion | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, space, claim_id, proposer, status, created_at, decided_at "
                "FROM promotions WHERE id=?", (promotion_id,)).fetchone()
            return self._promotion_from_row(row) if row else None

    def promotions(self, space: str, status: PromotionStatus | None = None) -> list[Promotion]:
        sql = ("SELECT id, space, claim_id, proposer, status, created_at, decided_at "
               "FROM promotions WHERE space=?")
        args: tuple = (space,)
        if status is not None:
            sql, args = sql + " AND status=?", (space, status)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
            return [self._promotion_from_row(r) for r in rows]

    def decide_promotion(self, promotion_id: str, status: PromotionStatus,
                         decided_at: datetime) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE promotions SET status=?, decided_at=? WHERE id=? AND status='pending'",
                (status, canonical_timestamp(decided_at), promotion_id))
            self._db.commit()

    def add_verdict(self, verdict: ReviewVerdict) -> bool:
        b = verdict.body
        with self._lock:
            row = self._db.execute(
                "SELECT status FROM promotions WHERE id=?", (b.promotion_id,)
            ).fetchone()
            if row is None or row[0] != "pending":
                return False
            self._db.execute(
                "INSERT INTO verdicts (promotion_id, verdict, basis, author, issued_at, signature) "
                "VALUES (?,?,?,?,?,?)",
                (b.promotion_id, b.verdict, b.basis, b.author,
                 canonical_timestamp(b.issued_at), verdict.signature))
            self._db.commit()
            return True

    def verdicts(self, promotion_id: str) -> list[ReviewVerdict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT promotion_id, verdict, basis, author, issued_at, signature "
                "FROM verdicts WHERE promotion_id=? ORDER BY rowid_ord",
                (promotion_id,)).fetchall()
        return [ReviewVerdict(
            body=ReviewVerdictBody(
                promotion_id=r[0], verdict=r[1], basis=r[2], author=r[3],
                issued_at=parse_datetime("issued_at", r[4])),
            signature=r[5]) for r in rows]

    def add_retirement(self, retirement: Retirement) -> None:
        b = retirement.body
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO retirements VALUES (?,?,?,?,?)",
                (b.claim_id, b.reason, b.author,
                 canonical_timestamp(b.issued_at), retirement.signature))
            self._db.commit()

    def retirement(self, claim_id: str) -> Retirement | None:
        with self._lock:
            row = self._db.execute(
                "SELECT claim_id, reason, author, issued_at, signature "
                "FROM retirements WHERE claim_id=?", (claim_id,)).fetchone()
        if row is None:
            return None
        return Retirement(
            body=RetirementBody(claim_id=row[0], reason=row[1], author=row[2],
                                issued_at=parse_datetime("issued_at", row[3])),
            signature=row[4])

    def record_invalidation(self, space: str, uri: str, changed_at: datetime) -> None:
        with self._lock:
            self._db.execute("INSERT INTO invalidations VALUES (?,?,?)",
                             (space, uri, canonical_timestamp(changed_at)))
            self._db.commit()

    def invalidations(self, space: str) -> dict[str, datetime]:
        with self._lock:
            rows = self._db.execute(
                "SELECT uri, MAX(changed_at) FROM invalidations WHERE space=? GROUP BY uri",
                (space,)).fetchall()
        return {r[0]: parse_datetime("changed_at", r[1]) for r in rows}

    def set_policy(self, scope: Scope, policy: Policy) -> None:
        record = json.dumps({
            "mode": policy.mode, "required_approvals": policy.required_approvals,
            "protected_topics": list(policy.protected_topics),
            "staleness_horizon_seconds": policy.staleness_horizon_seconds})
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO policies VALUES (?,?,?)",
                (scope.space, scope.segment or "", record))
            self._db.commit()

    def policy(self, scope: Scope) -> Policy | None:
        with self._lock:
            row = self._db.execute(
                "SELECT record FROM policies WHERE space=? AND segment=?",
                (scope.space, scope.segment or "")).fetchone()
        if row is None:
            return None
        d = json.loads(row[0])
        return Policy(mode=d["mode"], required_approvals=d["required_approvals"],
                      protected_topics=tuple(d["protected_topics"]),
                      staleness_horizon_seconds=d["staleness_horizon_seconds"])


class InMemoryStore:
    """A dict-backed twin of :class:`SQLiteStore` for tests and embedding."""

    def __init__(self) -> None:
        self._episodes: dict[str, Episode] = {}
        self._claims: dict[str, Claim] = {}
        self._endorsements: dict[str, list[Endorsement]] = {}
        self._promotions: dict[str, Promotion] = {}
        self._verdicts: dict[str, list[ReviewVerdict]] = {}
        self._retirements: dict[str, Retirement] = {}
        self._invalidations: dict[str, dict[str, datetime]] = {}
        self._policies: dict[tuple[str, str], Policy] = {}
        self._lock = threading.Lock()

    def add_episode(self, episode: Episode) -> None:
        self._episodes.setdefault(episode.id, episode)

    def episode(self, episode_id: str) -> Episode | None:
        return self._episodes.get(episode_id)

    def add_claim(self, claim: Claim) -> None:
        self._claims.setdefault(claim.claim_id, claim)

    def claim(self, claim_id: str) -> Claim | None:
        return self._claims.get(claim_id)

    def claims(self, space: str) -> list[Claim]:
        return [c for c in self._claims.values() if c.body.scope.space == space]

    def add_endorsement(self, endorsement: Endorsement) -> None:
        self._endorsements.setdefault(endorsement.body.claim_id, []).append(endorsement)

    def endorsements(self, claim_id: str) -> list[Endorsement]:
        return list(self._endorsements.get(claim_id, []))

    def endorsements_for(
        self, claim_ids: Iterable[str]
    ) -> dict[str, list[Endorsement]]:
        return {
            cid: list(self._endorsements.get(cid, []))
            for cid in dict.fromkeys(claim_ids)
        }

    def add_promotion(self, promotion: Promotion) -> None:
        self.add_claim(promotion.claim)
        self._promotions[promotion.id] = promotion

    def promotion(self, promotion_id: str) -> Promotion | None:
        return self._promotions.get(promotion_id)

    def promotions(self, space: str, status: PromotionStatus | None = None) -> list[Promotion]:
        return [p for p in self._promotions.values()
                if p.scope.space == space and (status is None or p.status == status)]

    def decide_promotion(self, promotion_id: str, status: PromotionStatus,
                         decided_at: datetime) -> None:
        with self._lock:
            existing = self._promotions.get(promotion_id)
            if existing is not None and existing.status == "pending":
                self._promotions[promotion_id] = replace(
                    existing, status=status, decided_at=decided_at)

    def add_verdict(self, verdict: ReviewVerdict) -> bool:
        with self._lock:
            p = self._promotions.get(verdict.body.promotion_id)
            if p is None or p.status != "pending":
                return False
            self._verdicts.setdefault(verdict.body.promotion_id, []).append(verdict)
            return True

    def verdicts(self, promotion_id: str) -> list[ReviewVerdict]:
        return list(self._verdicts.get(promotion_id, []))

    def add_retirement(self, retirement: Retirement) -> None:
        self._retirements.setdefault(retirement.body.claim_id, retirement)

    def retirement(self, claim_id: str) -> Retirement | None:
        return self._retirements.get(claim_id)

    def record_invalidation(self, space: str, uri: str, changed_at: datetime) -> None:
        per_space = self._invalidations.setdefault(space, {})
        if uri not in per_space or changed_at > per_space[uri]:
            per_space[uri] = changed_at

    def invalidations(self, space: str) -> dict[str, datetime]:
        return dict(self._invalidations.get(space, {}))

    def set_policy(self, scope: Scope, policy: Policy) -> None:
        self._policies[(scope.space, scope.segment or "")] = policy

    def policy(self, scope: Scope) -> Policy | None:
        return self._policies.get((scope.space, scope.segment or ""))
