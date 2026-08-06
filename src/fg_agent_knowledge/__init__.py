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
from .retrievers import (
    KeywordRetriever,
    Ranking,
    RetrievalQuery,
    Retriever,
)
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
    "CONFLICT_CONTRADICTION_THRESHOLD",
    "CONTEXT_CLAIM",
    "CONTEXT_ENDORSEMENT",
    "CONTEXT_RETIREMENT",
    "CONTEXT_VERDICT",
    "CONTRADICTION_WEIGHT",
    "DEFAULT_BRIEFING_LIMIT",
    "DEFAULT_POLICY",
    "DEFAULT_STALENESS_HORIZON_SECONDS",
    "DOMAIN",
    "SPEC",
    "ArtifactRef",
    "Briefing",
    "BriefingItem",
    "Claim",
    "ClaimBody",
    "ConflictEvent",
    "Endorsement",
    "EndorsementBody",
    "Episode",
    "InMemoryStore",
    "KeywordRetriever",
    "KnowledgeBase",
    "KnowledgeError",
    "NotFoundError",
    "Policy",
    "PolicyError",
    "Promotion",
    "Ranking",
    "Retirement",
    "RetirementBody",
    "RetrievalQuery",
    "Retriever",
    "ReviewVerdict",
    "ReviewVerdictBody",
    "SQLiteStore",
    "Scope",
    "ScopeError",
    "SignatureError",
    "Store",
    "ValidationError",
    "brief",
    "build_claim",
    "build_endorsement",
    "build_retirement",
    "build_verdict",
    "claim_id_of",
    "confidence",
    "record_id",
    "sign_payload",
    "signing_input",
    "staleness_seconds",
    "verify_by_address",
    "verify_claim",
    "verify_endorsement",
    "verify_retirement",
    "verify_verdict",
]
