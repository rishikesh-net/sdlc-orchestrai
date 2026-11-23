# Stack-specific checks: ASP.NET Core, React, PostgreSQL

## Contents
1. ASP.NET Core API
2. EF Core and Npgsql
3. React frontend
4. PostgreSQL
5. Configuration and secrets
6. Quick grep patterns

## 1. ASP.NET Core API
- Default-deny: `FallbackPolicy` requires an authenticated user; use `[AllowAnonymous]` sparingly and review each one.
- Use authorization policies and resource-based authorization (`IAuthorizationService`) for ownership checks.
- JWT bearer: `ValidateIssuer`, `ValidateAudience`, `ValidateLifetime`, `ValidateIssuerSigningKey` all true;
  set `ClockSkew` deliberately; never accept `alg: none`; keys from a secret store.
- Model binding: bind to request DTOs, not entities; use `[Required]`/validators; reject unknown fields where feasible.
- CORS: `WithOrigins(...)` explicit list; no `AllowAnyOrigin()` with `AllowCredentials()`.
- Cookies auth: `HttpOnly`, `Secure`, `SameSite`; antiforgery for cookie-authenticated unsafe methods.
- Rate limiting: built-in `AddRateLimiter` on login, reset, and expensive endpoints.
- Request limits: `MaxRequestBodySize`, form/multipart limits, and pagination caps.
- Error handling: `UseExceptionHandler` + `ProblemDetails`; `UseDeveloperExceptionPage` only in Development.
- HTTPS redirection and HSTS in production; forwarded headers configured correctly behind a proxy.
- Swagger/OpenAPI UI not exposed publicly in production unless intended.
- `HttpClient`: use `IHttpClientFactory`, timeouts, and validate destinations for user-influenced URLs (SSRF).
- Logging: no tokens, passwords, connection strings, or full PII; use structured logging with redaction.
- Deserialization: avoid `TypeNameHandling` in Newtonsoft; avoid `BinaryFormatter`.

## 2. EF Core and Npgsql
- Prefer LINQ. For raw SQL use `FromSqlInterpolated`/`ExecuteSqlInterpolated` (parameterized).
  Flag `FromSqlRaw`/`ExecuteSqlRaw` with string concatenation or `$""` interpolation.
- Dynamic sorting/filtering uses an allow-list of property names.
- Global query filters for soft-delete/tenant; ensure `IgnoreQueryFilters()` is not used on user paths.
- Connection string comes from config/secret store, with `SSL Mode=Require` (or `VerifyFull`) in production.
- Migrations run with a separate privileged role; the app role has only the DML it needs.
- Optimistic concurrency tokens on user-edited entities.

## 3. React frontend
- `dangerouslySetInnerHTML`, `innerHTML`, `eval`, `new Function`, `document.write`: flag unless input is sanitized (DOMPurify) and justified.
- Links with user-controlled `href` (`javascript:` URLs) and `target="_blank"` without `rel="noopener noreferrer"`.
- Open redirects after login (validate `returnUrl` against an allow-list of relative paths).
- Token storage: avoid long-lived tokens in `localStorage`/`sessionStorage`; prefer httpOnly cookies or in-memory with a BFF.
- Secrets: nothing sensitive in `VITE_*`/`REACT_APP_*`/`NEXT_PUBLIC_*`; no API keys in source or source maps shipped publicly.
- `postMessage` handlers check `event.origin`.
- CSP defined and tested; third-party scripts reviewed and integrity-pinned where possible.
- Client-side authorization is cosmetic; every sensitive action must be enforced by the API.
- Dependencies: `npm audit`, lockfile present, no install scripts from unknown packages.

## 4. PostgreSQL
- Roles: no superuser for the application; separate migration and runtime roles; revoke default `PUBLIC` privileges as appropriate.
- Network: TLS required, `pg_hba.conf` restricted, DB not publicly reachable.
- Row-level security for multi-tenant data where designed; test policies with non-owner roles.
- Sensitive columns: consider `pgcrypto` or application-level encryption; mask in logs and exports.
- Logging: avoid `log_statement=all` in production without redaction; protect logs that may contain parameters.
- Backups encrypted, tested restore, access audited.
- Extensions: minimize and review (`CREATE EXTENSION` only when needed).

## 5. Configuration and secrets
- Local dev: `dotnet user-secrets`, `.env` files git-ignored; Production: managed secret store (Key Vault, AWS Secrets Manager, GitHub environment secrets).
- Prefer managed identity/workload identity over static credentials.
- `.gitignore` covers `appsettings.*.local.json`, `.env*`, `*.pfx`, `*.pem`, `*.key`.
- If a secret was ever committed: rotate it, then clean history. Deleting the file is not enough.

## 6. Quick grep patterns (for orientation; scanners are authoritative)
```
FromSqlRaw|ExecuteSqlRaw|SqlQueryRaw          # raw SQL
AllowAnyOrigin|AllowCredentials              # CORS
\[AllowAnonymous\]                           # public endpoints
TypeNameHandling|BinaryFormatter             # unsafe deserialization
dangerouslySetInnerHTML|innerHTML|eval\(     # DOM XSS
localStorage\.(set|get)Item\(.*(token|jwt)   # token storage
ServerCertificateCustomValidationCallback    # disabled TLS checks
Password=|Pwd=|postgres(ql)?://[^ ]*:[^ ]*@  # embedded credentials (never print the match)
```
