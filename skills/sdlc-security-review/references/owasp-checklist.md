# OWASP-class checklist (web/API)
Align category names with the current OWASP Top 10 edition and the OWASP API Security Top 10 when
reporting; verify against owasp.org since editions change.

## Contents
1. Access control
2. Injection
3. Authentication and sessions
4. Cryptography and data protection
5. Insecure design and business logic
6. Security misconfiguration
7. Vulnerable and outdated components / supply chain
8. Logging, monitoring, and error handling
9. SSRF and outbound requests
10. File handling
11. Integrity (deserialization, CI/CD)

## 1. Access control (most common high-severity finding)
- [ ] Every endpoint requires authentication unless explicitly public (fallback/default policy)
- [ ] Object-level checks: the caller owns or may access the requested record (no IDOR via id params)
- [ ] Function-level checks: admin/role-only operations are enforced server-side
- [ ] Mass assignment: request DTOs expose only intended fields (no binding to entity/role/isAdmin)
- [ ] Tenant isolation enforced in queries or via RLS
- [ ] Client-side route guards are treated as UX only, never as security

## 2. Injection
- [ ] SQL: parameterized only; no string concatenation/interpolation into raw SQL
- [ ] No dynamic ORDER BY/column names built from user input without an allow-list
- [ ] Command, LDAP, XPath, template, and header injection considered
- [ ] Output encoding in React (no `dangerouslySetInnerHTML` with untrusted data; sanitize if unavoidable)

## 3. Authentication and sessions
- [ ] Token validation: issuer, audience, signature, lifetime, algorithm allow-list
- [ ] Passwords (if local): strong hashing (ASP.NET Identity defaults, Argon2/PBKDF2), lockout, breached-password checks
- [ ] Session/cookies: HttpOnly, Secure, SameSite; CSRF defenses when using cookies
- [ ] Refresh token rotation and revocation; logout invalidates server-side state
- [ ] Rate limiting and lockout on login, reset, and OTP endpoints

## 4. Cryptography and data protection
- [ ] TLS everywhere including API->DB; HSTS enabled
- [ ] No custom crypto; use platform primitives; no MD5/SHA1 for security; no hard-coded keys/IVs
- [ ] Sensitive data classified; encrypted at rest where required; minimized and not over-collected
- [ ] ASP.NET Data Protection keys persisted and protected for multi-instance deployments

## 5. Insecure design and business logic
- [ ] Abuse cases considered: enumeration, replay, race conditions, quota bypass, price/amount tampering
- [ ] Idempotency for repeatable operations; server-side recalculation of totals
- [ ] Sensitive flows (reset, email change) require re-authentication or confirmation

## 6. Security misconfiguration
- [ ] CORS: explicit origins, no wildcard with credentials
- [ ] Security headers: CSP, X-Content-Type-Options, frame-ancestors/X-Frame-Options, Referrer-Policy
- [ ] Debug/developer exception pages off in production; Swagger restricted outside dev
- [ ] Default accounts, sample data, and verbose banners removed
- [ ] Container and IaC settings: non-root user, minimal image, no secrets in image layers

## 7. Components and supply chain
- [ ] `dotnet list package --vulnerable --include-transitive` and `npm audit` reviewed
- [ ] Lockfiles committed; versions pinned; unexpected new dependencies justified
- [ ] GitHub Actions pinned to versions/SHAs; least-privilege `permissions:`; no untrusted input in `run:`

## 8. Logging, monitoring, error handling
- [ ] Security events logged (login failures, authz denials, admin actions) without secrets/PII
- [ ] Errors return ProblemDetails with no stack traces or SQL text
- [ ] Alerts exist for spikes in 401/403/429 and for anomalous access

## 9. SSRF and outbound calls
- [ ] User-supplied URLs are allow-listed; block internal/metadata IP ranges; limit redirects
- [ ] Timeouts and size limits on every outbound call

## 10. File handling
- [ ] Type, size, and content validation; random server-side names; stored outside the web root or in object storage
- [ ] No path traversal; no execution of uploaded content; malware scanning where required

## 11. Integrity
- [ ] No unsafe deserialization (`BinaryFormatter`, `TypeNameHandling.All`, untrusted polymorphic JSON)
- [ ] Webhooks verify signatures and timestamps
- [ ] CI/CD secrets scoped per environment; protected branches and required reviews
