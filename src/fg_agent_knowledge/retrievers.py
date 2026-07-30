"""Retrieval adapters — the second infra seam of a knowledge base.

Storage (the ``Store``) is one seam; retrieval is the other, and just as
important: a knowledge base that can't surface the right claim is only storage.
The normative core owns *trust* (confidence ⊥ staleness ⊥ suspect) and briefing
assembly; a ``Retriever`` owns only *relevance* — how well a claim matches the
task. That split keeps trust portable while letting a deployment bring its own
search: the default ``KeywordRetriever`` (BM25 over stemmed tokens) for lexical
search, or a consumer-supplied semantic/vector retriever behind the same
interface.

A retriever returns relevance in ``[0, 1]``; the core multiplies it by trust.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable

from .text import analyze
from .types import Claim


@dataclass(frozen=True)
class RetrievalQuery:
    """What to rank against — the lexical part of a briefing request. Refs and
    trust are the core's concern, not the retriever's."""
    task: str
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ranking:
    """A retriever's answer: relevance per claim, and whether the query had no
    usable terms (in which case the core ranks by trust alone)."""
    scores: dict[str, float] = field(default_factory=dict)
    query_empty: bool = False


@runtime_checkable
class Retriever(Protocol):
    """The retrieval seam. ``rank`` is required; ``index``/``remove`` are
    optional write-side hooks a stateful (e.g. vector-indexed) retriever uses
    to maintain its index as claims are accepted and retired."""

    def rank(self, query: RetrievalQuery,
             claims: Sequence[Claim]) -> Ranking: ...

    def index(self, claim: Claim) -> None: ...

    def remove(self, claim_id: str) -> None: ...


class BaseRetriever:
    """Convenience base: no-op write hooks so stateless retrievers only
    implement ``rank``."""

    def index(self, claim: Claim) -> None:  # noqa: D401 - see class docstring
        return None

    def remove(self, claim_id: str) -> None:
        return None


# BM25 free parameters, the values Lucene/Elasticsearch default to. k1 controls
# term-frequency saturation; b controls how much document length is penalized.
DEFAULT_K1 = 1.5
DEFAULT_B = 0.75
# Topic terms are curated labels — worth more than the same word buried in
# prose, so each topic term is counted this many times in the document.
DEFAULT_TOPIC_WEIGHT = 2


class KeywordRetriever(BaseRetriever):
    """Best-practice lexical retrieval: Okapi BM25 over stopword-filtered,
    Porter-stemmed tokens — the same ranking function Lucene/Elasticsearch use.

    Stateless: it scores over the candidate claims handed to it each query, so
    it needs no persisted index (fine for realistic per-scope corpora). IDF is
    computed over that candidate set. Everything is tunable for flexibility.
    """

    def __init__(self, *, k1: float = DEFAULT_K1, b: float = DEFAULT_B,
                 stem: bool = True, remove_stopwords: bool = True,
                 topic_weight: int = DEFAULT_TOPIC_WEIGHT) -> None:
        self.k1 = k1
        self.b = b
        self.stem = stem
        self.remove_stopwords = remove_stopwords
        self.topic_weight = max(1, topic_weight)

    def _analyze(self, text: str) -> list[str]:
        return analyze(text, stem=self.stem,
                       remove_stopwords=self.remove_stopwords)

    def _doc_terms(self, claim: Claim) -> list[str]:
        terms = self._analyze(claim.body.statement)
        for topic in claim.body.topics:
            terms.extend(self._analyze(topic) * self.topic_weight)
        return terms

    def _query_terms(self, query: RetrievalQuery) -> list[str]:
        terms = self._analyze(query.task)
        for topic in query.topics:
            terms.extend(self._analyze(topic))
        return terms

    def rank(self, query: RetrievalQuery,
             claims: Sequence[Claim]) -> Ranking:
        q_terms = self._query_terms(query)
        if not q_terms:
            return Ranking(query_empty=True)
        if not claims:
            return Ranking()

        docs = {c.claim_id: Counter(self._doc_terms(c)) for c in claims}
        lengths = {cid: sum(tf.values()) for cid, tf in docs.items()}
        n = len(docs)
        avgdl = (sum(lengths.values()) / n) if n else 0.0

        # Document frequency per (unique) query term, over the candidate set.
        q_unique = set(q_terms)
        df = {t: sum(1 for tf in docs.values() if t in tf) for t in q_unique}
        idf = {
            t: max(0.0, math.log(1 + (n - df_t + 0.5) / (df_t + 0.5)))
            for t, df_t in df.items()
        }

        raw: dict[str, float] = {}
        for cid, tf in docs.items():
            dl = lengths[cid] or 1
            s = 0.0
            for t in q_unique:
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / (avgdl or 1))
                s += idf[t] * (f * (self.k1 + 1)) / denom
            if s > 0:
                raw[cid] = s

        # Normalize to [0, 1] within this query so the core can combine
        # relevance with trust (and its ref boost) on one scale.
        top = max(raw.values(), default=0.0)
        scores = {cid: s / top for cid, s in raw.items()} if top > 0 else {}
        return Ranking(scores=scores)
