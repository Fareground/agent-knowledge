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

    scout, analyst = KeyPair.generate(), KeyPair.generate()
    kb = KnowledgeBase(SQLiteStore(db_path))
    scope = Scope(space="workspace-42")
    kb.set_policy(scope, Policy(mode="review", required_approvals=1))

    # scout observes, distills, proposes
    ep = kb.observe(scope, scout, "observation", "deploy failed twice on cold cache")
    promo = kb.propose(
        scope, scout, "procedural",
        "warm the cache before deploying the pricing service",
        topics=("deploy", "pricing"), episodes=(ep.id,),
    )

    # analyst reviews — the proposer cannot approve their own promotion
    promo = kb.review(promo.id, analyst, "approve", basis="matches incident log")
    assert promo.status == "accepted"

    # anyone briefs before acting — assembled, attributed, never generated
    briefing = kb.brief(scope, task="deploy pricing service")
    top = briefing.items[0]
    print(top.claim.body.statement, top.confidence, top.verify_first)


if __name__ == "__main__":
    main()
