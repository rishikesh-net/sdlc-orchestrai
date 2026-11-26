# AGENTS.md — SDLCOrchestrAI shared instructions

Single entry point for every coding agent (Claude Code, GitHub Copilot, Cursor, OpenCode, Antigravity).
`CLAUDE.md` and `.github/copilot-instructions.md` point here. Canonical skills live in `skills/`; publish local client copies with `python scripts/sdlc.py sync-skills`.

## Stack defaults
- API: .NET (C#), ASP.NET Core, EF Core + Npgsql
- Frontend: React (TypeScript preferred)
- Database: PostgreSQL
- Tracker: GitHub Issues (+ optional GitHub Projects) via `gh`, or offline Markdown (`tracker: local`) in `.sdlc/config.yaml`
- Prefer existing repo patterns; justify deviations in an ADR.

## Delivery chain (every arrow is a HUMAN APPROVAL GATE)

```
Requirement
  -> sdlc-requirements-analyzer  -> docs/requirements/<feature>.md            [review]
  -> sdlc-system-design          -> docs/design/<feature>.md + ADRs           [review]
     + sdlc-security-review (Mode A: threat model)                             [review]
  -> sdlc-backlog-breakdown      -> docs/backlog/<feature>-backlog.md + .json [review]
  -> python scripts/sdlc.py backlog push --dry-run, then apply                 [review]
  -> sdlc-feature-implementer    -> branch + TDD tests + code + draft PR       [review]
  -> sdlc-security-review (Mode B: diff/PR review) + CI scans                 [review]
  -> merge
```

Never skip a gate. Never start a later phase on an unapproved earlier artifact.
Run `python scripts/sdlc.py verify --gate <gate> --feature <feature>` before asking for gate approval.

## Large requirements (packs)
- Use a single file up to ~40 requirements or 400 lines; above that, use a vertical-slice pack (`docs/requirements/<feature>/`, slice-prefixed IDs `REQ-PREF-001`) via `sdlc-requirements-analyzer`.
- Never load a whole pack into context: read `00-index.md`, then one slice (`python scripts/sdlc.py req show --feature F --slice S`).
- Design, backlog, and security work proceed one slice at a time.

## Shared memory (opt-in for client switches)
- Use `sdlc-session-handoff` (`python scripts/sdlc.py resume` / `checkpoint`) when switching coding clients mid-feature or resuming after a pause.
- Memory is a hint, not truth — verify against git and `docs/`. Never store secrets or personal data in `.sdlc/`.

## Skills
| Skill | Use it when |
|---|---|
| `sdlc-requirements-analyzer` | Turn an idea/ticket into structured, testable requirements (`REQ-xxx`) |
| `sdlc-system-design` | Produce architecture, data model, API contracts, NFRs, and ADRs |
| `sdlc-backlog-breakdown` | Break an approved design into epics, vertical-slice stories, and tickets |
| `sdlc-feature-implementer` | Implement an approved story/issue (branch, TDD scaffold, code, draft PR) |
| `sdlc-security-review` | Threat model a design, or review a diff/PR/codebase for vulnerabilities |
| `sdlc-session-handoff` | Opt-in handoff when switching clients or pausing a multi-day feature |

## Traceability
End-to-end IDs: `REQ-012` -> design section -> `E1-S3` (`req_refs`) -> ticket `#123` -> PR.

## Safety rules (all agents, all skills)
1. Do NOT create, edit, or close GitHub issues without showing a `--dry-run` plan and getting explicit approval.
2. Do NOT run destructive commands (delete, force-push, `DROP`, `git reset --hard`, prod deploys) without explicit approval.
3. Never print, log, or copy secrets, tokens, or connection strings. Reference `file:line` only.
4. Never commit credentials. Use environment variables, `dotnet user-secrets`, or a secret manager.
5. Do not probe live or production systems. Reviews are static and in-repo.
6. Scripts do the deterministic work (verify, scan, push). The model decides and interprets.
7. If something is unknown, write it under "Open Questions". Do not guess.
8. Prefer small, reviewable changes. One concern per PR.
9. Shared memory never replaces an approval gate for side effects.

## Conventions
- Diagrams: Mermaid in markdown.
- API: REST + OpenAPI, RFC 7807 `ProblemDetails`, versioned routes.
- DB: EF Core migrations, snake_case naming, `timestamptz`, rollback plan.
- Frontend: typed API client from OpenAPI where possible; no secrets in client bundles.
- Commits: conventional commits referencing issue numbers.
