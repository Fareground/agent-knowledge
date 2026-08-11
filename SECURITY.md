# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately to **sandro@corza.ai**.
Do not open a public issue for security reports.

Include what you can: affected version, a reproduction or proof of concept,
and impact. You will get an acknowledgement, and a fix or mitigation will be
prioritized ahead of other work.

## Scope

This package implements a signed wire format (Ed25519 over a dedicated
signing domain, `fg-agent-knowledge/v1`). Of particular interest:

- Signature forgery, malleability, or cross-domain replay of records.
- Bypasses of the trust model: self-review, non-author retirement or
  supersession, timestamp gaming beyond the skew window.
- Canonicalization ambiguities that let two byte sequences verify as the
  same record.

## Supported versions

Only the latest released version receives security fixes.
