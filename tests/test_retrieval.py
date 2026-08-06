"""The retrieval adapter: BM25 keyword retriever + the pluggable seam.

Covers the accuracy wins (stemming, IDF, length normalization), the "list
everything" path, and that a consumer can inject its own retriever (semantic,
etc.) and both change the ranking and receive index/remove lifecycle hooks.
"""
from __future__ import annotations

import pytest
from fg_agent_id import KeyPair

from fg_agent_knowledge import (
    InMemoryStore,
    KeywordRetriever,
    KnowledgeBase,
    Ranking,
    RetrievalQuery,
    Scope,
    build_claim,
)

SCOPE = Scope(space="ws-retrieval")


@pytest.fixture
def agent():
    return KeyPair.generate()


def _claim(agent, statement, topics=(), refs=()):
    return build_claim(agent, SCOPE, "semantic", statement, topics=topics, refs=refs)


# -- stemming: the phrasing-mismatch fix -------------------------------------

def test_stemming_matches_inflections(agent):
    """A loosely-phrased task matches a differently-inflected claim — the miss
    that plain token-overlap had ("building" vs "build")."""
    claim = _claim(agent, "build the deck before deploying")
    r = KeywordRetriever()
    hit = r.rank(RetrievalQuery(task="building and deployment"), [claim])
    assert hit.scores.get(claim.claim_id, 0.0) > 0

    off = KeywordRetriever(stem=False)
    miss = off.rank(RetrievalQuery(task="building and deployment"), [claim])
    assert claim.claim_id not in miss.scores  # without stemming, no match


def test_stopwords_do_not_match(agent):
    claim = _claim(agent, "the cache is the source of the slowness")
    r = KeywordRetriever()
    # A query of only stopwords has no usable terms.
    assert r.rank(RetrievalQuery(task="the is of"), [claim]).query_empty


# -- BM25 properties ---------------------------------------------------------

def test_idf_prefers_rarer_terms(agent):
    """A claim matching a rare query term outranks one matching a common one."""
    common = [_claim(agent, "cache warming helps the cache stay warm cache")
              for _ in range(4)]
    rare = _claim(agent, "the kubernetes ingress controller needs a cache")
    claims = common + [rare]
    r = KeywordRetriever()
    ranking = r.rank(RetrievalQuery(task="kubernetes cache"), claims)
    top = max(ranking.scores, key=ranking.scores.get)
    assert top == rare.claim_id  # "kubernetes" is rare → carries more weight


def test_length_normalization(agent):
    """Between two claims that both contain the term, the more focused (shorter)
    one is not drowned out by a long padded one."""
    short = _claim(agent, "cache invalidation is hard")
    long = _claim(agent, "cache " + " ".join(f"word{i}" for i in range(80)))
    r = KeywordRetriever()
    ranking = r.rank(RetrievalQuery(task="cache invalidation"), [short, long])
    assert ranking.scores[short.claim_id] > ranking.scores[long.claim_id]


def test_empty_query_lists_everything_by_trust(agent):
    """An empty task returns query_empty so the core ranks by trust alone."""
    kb = KnowledgeBase(InMemoryStore())
    kb.propose(SCOPE, agent, "semantic", "first fact")
    kb.propose(SCOPE, agent, "semantic", "second fact")
    out = kb.brief(SCOPE, task="")
    assert len(out.items) == 2  # both surface with no lexical filter


# -- the pluggable seam ------------------------------------------------------

class ReverseRetriever:
    """A toy custom retriever: scores by statement length, and records the
    index/remove hooks it receives — proof the seam is real."""

    def __init__(self):
        self.indexed: list[str] = []
        self.removed: list[str] = []

    def rank(self, query, claims):
        if not query.task:
            return Ranking(query_empty=True)
        return Ranking(scores={c.claim_id: len(c.body.statement) for c in claims})

    def index(self, claim):
        self.indexed.append(claim.claim_id)

    def remove(self, claim_id):
        self.removed.append(claim_id)


def test_custom_retriever_changes_ranking_and_gets_lifecycle(agent):
    retriever = ReverseRetriever()
    kb = KnowledgeBase(InMemoryStore(), retriever=retriever)

    short = kb.propose(SCOPE, agent, "semantic", "short one about cache")
    long = kb.propose(SCOPE, agent, "semantic",
                      "a considerably longer statement also about the cache here")

    # Accepted claims were handed to the retriever's index hook.
    assert set(retriever.indexed) == {short.claim.claim_id, long.claim.claim_id}

    out = kb.brief(SCOPE, task="cache")
    # This retriever scores by length, so the longer claim ranks first —
    # a different order than BM25 would give. The seam is really in control.
    assert out.items[0].claim.claim_id == long.claim.claim_id

    kb.retire(long.claim.claim_id, agent, reason="obsolete")
    assert retriever.removed == [long.claim.claim_id]
