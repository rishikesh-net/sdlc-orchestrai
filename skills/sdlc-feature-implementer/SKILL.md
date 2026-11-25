---
name: sdlc-feature-implementer
description: Implement an approved story or issue ticket with end-to-end traceability - checkout feature branch, scaffold test-first acceptance criteria mapped to REQ-IDs, write minimal clean code (.NET/React/PostgreSQL), run local build and test verification, and generate a structured PR draft. Use this whenever the user says "implement this story", "code issue #X", "build story E1-S1", or is ready to write code for an approved backlog ticket. Never starts without an approved story and design section.
---

# Feature Implementer (Story to PR)

Input: an approved story (`E<n>-S<m>`) from `docs/backlog/<feature>-backlog.json` or an open GitHub issue.
Output: isolated feature branch (`feat/<issue-or-story-id>-<slug>`), test suite covering all Given/When/Then acceptance criteria, working implementation code, verified local builds/tests, and draft PR description.

## The Rule: No Implementation Without Design & Backlog Approval
Never write application code directly from a vague user request. Ensure:
1. Requirements exist in `docs/requirements/` with `REQ-xxx` IDs.
2. Design & Threat Model exist in `docs/design/` and are approved.
3. The story exists in `docs/backlog/<feature>-backlog.json` with Given/When/Then acceptance criteria.
If any gate is missing, run the prerequisite skill first (`sdlc-requirements-analyzer`, `sdlc-system-design`, or `sdlc-backlog-breakdown`).

---

## Story Execution Workflow

### Step 1: Story Intake & Context Isolation
1. Load the target story:
   `sdlc story show <story-id> [--feature <feature>]`
   Or find the story entry in `docs/backlog/<feature>-backlog.json`.
2. Inspect:
   - **Acceptance Criteria**: Each Given/When/Then statement.
   - **Requirement References**: Cited `req_refs` (e.g., `REQ-001`, `NFR-002`).
   - **Design Reference**: The exact markdown section in `design_ref` (e.g., `docs/design/feature.md#6-api-contracts`).
3. Load **only** the referenced section of the design document and any linked ADRs. Do not load unnecessary documentation to preserve context efficiency.

### Step 2: Branch Isolation
1. Verify working tree is clean:
   `git status --porcelain`
2. Start the story branch:
   `sdlc story start <story-id> [--feature <feature>]`
   This automatically:
   - Creates and switches to branch `feat/<issue-or-story-id>-<slug>`.
   - Checkpoints shared state in `.sdlc/state.json` (phase: `implementation`, active branch recorded).

### Step 3: Test-First Scaffolding (TDD)
Before writing any production logic, scaffold automated tests directly derived from the story's acceptance criteria:
1. For each Given/When/Then statement in `acceptance_criteria`:
   - Create a test method whose name reflects the scenario (e.g. `SavePreferences_ValidCategory_PersistsChoices`).
   - Add a comment linking to the criteria and requirement ID:
     `// AC: Given a signed-in customer, When they save preferences, Then choices persist [REQ-001]`
2. Include at least **one negative / error test case** (e.g., 401 Unauthorized, 400 ProblemDetails for invalid input, boundary limit).
3. Refer to:
   - Backend (.NET C#): `templates/test-scaffold.example.cs`
   - Frontend (React TypeScript): `templates/test-scaffold.example.tsx`

### Step 4: Minimal Working Implementation
Implement the minimal code required to make tests pass:
- **Stack Defaults**:
  - API: ASP.NET Core (.NET 8/10), C# nullable reference types, minimal controllers or FastEndpoints, EF Core + Npgsql.
  - Errors: RFC 7807 `ProblemDetails` for domain/validation errors. Never return raw exception traces.
  - DB: PostgreSQL snake_case column and table naming. Migrations must include rollback considerations.
  - Frontend: React with TypeScript, typed API clients generated from OpenAPI, accessible HTML.
- **Safety**:
  - Never commit secrets, tokens, or hardcoded credentials.
  - Never defeat authentication or authorization checks.
  - Keep changes scoped strictly to the story's acceptance criteria.

### Step 5: Local Verification
Run automated tests and builds locally:
- Backend: `dotnet test`
- Frontend: `npm test` or `pnpm test`
- Gate check: `sdlc verify --gate implementation`
Assert that all tests pass and no regression was introduced.

### Step 6: PR Preparation & Conventional Commits
1. Commit changes using conventional commits:
   `git commit -m "feat(<component>): <short description> (closes #<issue>, implements <story-id>, REQ-<id>)"`
2. Generate PR body from story metadata:
   `sdlc story pr-body <story-id> [--feature <feature>] > .sdlc/pr-body.md`
3. Push feature branch:
   `git push -u origin feat/<issue-or-story-id>-<slug>`
4. Open the Pull Request:
   `gh pr create --body-file .sdlc/pr-body.md` (or provide the PR creation link)
5. Checkpoint the session handoff:
   `sdlc checkpoint --feature <slug> --phase implementation --gate implementation=in-review --artifact .sdlc/pr-body.md --next "Run sdlc-security-review Mode B on PR"`

---

## Shared Memory Protocol
- **Resume**: At the start of an implementation turn, run `sdlc resume`. Verify recorded branch matches current git branch.
- **Checkpoint**: Whenever stepping away or completing a story, run `sdlc checkpoint --feature <slug> --branch <branch> --note "Story <id> implementation completed; PR opened"`.
