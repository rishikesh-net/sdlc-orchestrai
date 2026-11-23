# STRIDE threat modeling quick guide

## Process
1. Draw (Mermaid) the data flow: external entities, processes, data stores, trust boundaries.
2. For each element crossing or inside a boundary, ask the six STRIDE questions.
3. Rate each credible threat: likelihood (L/M/H) x impact (L/M/H) -> severity.
4. Assign a control and a verification (test, scan, or review step).

## STRIDE prompts
| Letter | Threat | Questions to ask | Typical controls |
|---|---|---|---|
| S | Spoofing | Can someone pretend to be another user/service? | OIDC, strong session handling, mTLS/managed identity for service calls |
| T | Tampering | Can data be altered in transit, at rest, or via client-controlled fields? | TLS, server-side validation, DTOs (no mass assignment), DB constraints, integrity checks |
| R | Repudiation | Can an actor deny an action? Is there an audit trail? | Audit log of security-relevant actions, immutable storage, correlation IDs |
| I | Information disclosure | Can data leak via errors, logs, IDOR, over-broad queries, caches? | Authz on every resource, field-level filtering, redact logs, generic errors, encryption |
| D | Denial of service | Can one client exhaust CPU, memory, connections, or DB? | Rate limiting, pagination caps, request size limits, timeouts, pooled connections |
| E | Elevation of privilege | Can a user reach admin or other tenants' data? | Default-deny authz policies, role/claim checks server-side, tenant isolation (RLS), least-privilege DB roles |

## Trust boundaries to always examine
- Browser <-> API (all input is hostile; CORS, CSRF, cookies vs tokens)
- API <-> PostgreSQL (parameterization, least privilege, TLS)
- API <-> third-party services (SSRF, secrets, webhooks signature verification)
- API <-> background workers/queues (message authenticity, idempotency, poison messages)
- CI/CD <-> cloud (pipeline secrets, supply chain)

## Output table
| ID | Threat (STRIDE) | Component | L | I | Severity | Control | Verified by |
|---|---|---|---|---|---|---|---|
| T-001 | E: user edits another user's record by changing id | Preferences API | H | H | High | Resource-level authz policy; negative test | Integration test |
