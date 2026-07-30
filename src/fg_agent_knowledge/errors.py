"""Error hierarchy for fg-agent-knowledge.

Everything raised by this package derives from :class:`KnowledgeError`, so a
consumer can catch one type at the boundary. Subclasses name the *protocol
rule* that was violated, not the module that noticed it.
"""

from __future__ import annotations


class KnowledgeError(Exception):
    """Base class for all fg-agent-knowledge errors."""


class ValidationError(KnowledgeError):
    """A record is malformed: bad fields, floats in a signed body, bad enums."""


class SignatureError(KnowledgeError):
    """A signature is missing, malformed, or does not verify against its author."""


class NotFoundError(KnowledgeError):
    """A referenced record (claim, promotion, episode) does not exist."""


class PolicyError(KnowledgeError):
    """A governance rule was violated: self-review, duplicate approver,
    reviewing a decided promotion."""


class ScopeError(KnowledgeError):
    """A record references data across a ``space`` boundary. Queries and
    references never cross spaces — this is the one guarantee the library
    itself enforces."""
