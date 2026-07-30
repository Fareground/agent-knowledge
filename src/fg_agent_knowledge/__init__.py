"""fg-agent-knowledge — shared knowledge for multi-agent spaces.

Claims with pedigree, governed promotion, assembled briefings. Third leg of
the standards stack: fg-agent-id (who) → fg-amp (how they talk) →
fg-agent-knowledge (what a group knows).
"""

from .claim import build_claim, claim_id_of, verify_claim
from .endorsement import build_endorsement, verify_endorsement
from .errors import (
    KnowledgeError,
    NotFoundError,
    PolicyError,
    ScopeError,
    SignatureError,
    ValidationError,
)
from .governance import (
    DEFAULT_POLICY,
    build_retirement,
    build_verdict,
    verify_retirement,
    verify_verdict,
)
from .knowledge import KnowledgeBase
from .retrieval import brief
from .scoring import (
    CONFLICT_CONTRADICTION_THRESHOLD,
    CONTRADICTION_WEIGHT,
    DEFAULT_BRIEFING_LIMIT,
    DEFAULT_STALENESS_HORIZON_SECONDS,
    confidence,
    staleness_seconds,
)
from .signing import (
    CONTEXT_CLAIM,
    CONTEXT_ENDORSEMENT,
    CONTEXT_RETIREMENT,
    CONTEXT_VERDICT,
    DOMAIN,
    record_id,
    sign_payload,
    signing_input,
    verify_by_address,
)
from .retrievers import (
    KeywordRetriever,
    Ranking,
    RetrievalQuery,
    Retriever,
)
from .store import InMemoryStore, SQLiteStore, Store
from .types import (
    SPEC,
    ArtifactRef,
    Briefing,
    BriefingItem,
    Claim,
    ClaimBody,
    ConflictEvent,
    Endorsement,
    EndorsementBody,
    Episode,
    Policy,
    Promotion,
    Retirement,
    RetirementBody,
    ReviewVerdict,
    ReviewVerdictBody,
    Scope,
)

__all__ = [
    "SPEC",
    "DOMAIN",
    "CONTEXT_CLAIM",
    "CONTEXT_ENDORSEMENT",
    "CONTEXT_VERDICT",
    "CONTEXT_RETIREMENT",
    "CONTRADICTION_WEIGHT",
    "CONFLICT_CONTRADICTION_THRESHOLD",
    "DEFAULT_BRIEFING_LIMIT",
    "DEFAULT_STALENESS_HORIZON_SECONDS",
    "DEFAULT_POLICY",
    "KnowledgeError",
    "ValidationError",
    "SignatureError",
    "NotFoundError",
    "PolicyError",
    "ScopeError",
    "Scope",
    "ArtifactRef",
    "Episode",
    "ClaimBody",
    "Claim",
    "EndorsementBody",
    "Endorsement",
    "ReviewVerdictBody",
    "ReviewVerdict",
    "RetirementBody",
    "Retirement",
    "Policy",
    "Promotion",
    "ConflictEvent",
    "Briefing",
    "BriefingItem",
    "KnowledgeBase",
    "Store",
    "SQLiteStore",
    "InMemoryStore",
    "Retriever",
    "KeywordRetriever",
    "RetrievalQuery",
    "Ranking",
    "build_claim",
    "claim_id_of",
    "verify_claim",
    "build_endorsement",
    "verify_endorsement",
    "build_verdict",
    "verify_verdict",
    "build_retirement",
    "verify_retirement",
    "brief",
    "confidence",
    "staleness_seconds",
    "signing_input",
    "sign_payload",
    "verify_by_address",
    "record_id",
]
