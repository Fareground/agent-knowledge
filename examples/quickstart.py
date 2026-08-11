"""Quickstart: propose -> review -> brief.

The README usage snippet, complete and runnable. Two agents share a knowledge
base: a scout observes and proposes a claim, an analyst reviews it, and a
briefing serves the accepted knowledge with pedigree.

Run:  python examples/quickstart.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fg_agent_id import KeyPair

from fg_agent_knowledge import KnowledgeBase, Policy, Scope, SQLiteStore


def main(db_path: str | None = None) -> None:
    if db_path is None:
        db_path = str(Path(tempfile.mkdtemp()) / "team.db")

    store = SQLiteStore(db_path)
    # One handle per acting agent: default_author is who this handle signs as.
    scout = KnowledgeBase(store, default_author=KeyPair.generate())
    analyst = KnowledgeBase(store, default_author=KeyPair.generate())
    scope = Scope(space="workspace-42")
    scout.set_policy(scope, Policy(mode="review", required_approvals=1))

    # scout observes, distills, proposes
    ep = scout.observe(
        scope, kind="observation", content="deploy failed twice on cold cache"
    )
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


if __name__ == "__main__":
    main()
