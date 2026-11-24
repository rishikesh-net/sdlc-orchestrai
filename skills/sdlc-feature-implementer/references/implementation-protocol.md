# Implementation Protocol (.NET + React + PostgreSQL)

Guidelines for coding agents implementing stories under `sdlc-feature-implementer`.

## 1. Test-First Scaffolding Rules

Every acceptance criterion in the story must be covered by an automated test.

### Test Naming Convention
Use the pattern: `UnitOfWork_StateUnderTest_ExpectedBehavior`

```csharp
[Fact]
public async Task SavePreferences_WhenCategoryIsValid_PersistsAndReturns200()
{
    // AC: Given a signed-in customer, When they save preferences, Then choices persist and appear on reload [REQ-001]
}

[Fact]
public async Task SavePreferences_WhenUserUnauthenticated_Returns401Unauthorized()
{
    // AC: Given an unauthenticated request, When it calls preferences API, Then it receives 401 [REQ-001]
}
```

### Traceability Comments
Every test method covering an acceptance criteria MUST include a comment citing:
1. The exact Given/When/Then acceptance criteria text.
2. The associated requirement ID(s) (`[REQ-xxx]`).

---

## 2. Backend Conventions (.NET C#)

- **Architecture**: Clean / Vertical Slice. Avoid unnecessary abstractions.
- **Nullability**: `<Nullable>enable</Nullable>` is mandatory. No unhandled null warnings.
- **Validation**: FluentValidation or DataAnnotations executed before domain handlers.
- **Error Responses**: Return `Microsoft.AspNetCore.Mvc.ProblemDetails` adhering to RFC 7807:
  - 400 Bad Request: Validation failure (include `errors` dictionary).
  - 401 Unauthorized: Missing or invalid authentication token.
  - 403 Forbidden: Authenticated user lacks required permission/role.
  - 404 Not Found: Entity does not exist or user cannot access it.
  - 409 Conflict: Optimistic concurrency or unique constraint violation.
- **Async/Await**: Async all the way through (e.g., `async Task<IActionResult>`). Always pass `CancellationToken`.

---

## 3. Database Conventions (PostgreSQL & EF Core)

- **Naming**: snake_case for tables and columns (`customer_preferences`, `updated_at`).
- **Data Types**:
  - Timestamps: Always `timestamp with time zone` (`timestamptz`), stored in UTC.
  - Identifiers: `uuid` (UUIDv7 or UUIDv4) or `bigint identity`.
- **Migrations**:
  - Add via EF Core: `dotnet ef migrations add <DescriptiveName>`.
  - Non-destructive: Never drop columns or tables without a two-phase rollout and explicit rollback instructions.
  - Ensure foreign keys have backing indexes.

---

## 4. Frontend Conventions (React + TypeScript)

- **Strict Types**: No `any`. Strict TypeScript compiler mode.
- **Component Architecture**: Functional components with custom hooks isolating API interaction.
- **Error Boundaries**: Handle loading and error states explicitly in the UI.
- **Testing**:
  - Vitest / Jest with React Testing Library.
  - Test user behavior, not implementation details (use `getByRole`, `findByText`).

---

## 5. Security & Safety Checklist

Before committing or opening a PR:
- [ ] No secrets, passwords, or connection strings in code or git history.
- [ ] Parameterized SQL / EF Core LINQ used everywhere (no raw string interpolation into queries).
- [ ] Authentication and authorization policies applied to all endpoints.
- [ ] CORS policies properly restricted (no `AllowAnyOrigin` in production configurations).
- [ ] Rate limiting considered for public endpoints.
