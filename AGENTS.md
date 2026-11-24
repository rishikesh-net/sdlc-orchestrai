# AGENTS.md — SDLCOrchestrAI shared instructions

This file is the single entry point for every coding agent (Claude Code, GitHub Copilot, Cursor, OpenCode, Antigravity).
`CLAUDE.md` and `.github/copilot-instructions.md` point here. Skills live in `skills/` (canonical)
and are copied to each client's folder by `scripts/sync-skills.sh`.

## Stack defaults
- API: .NET (C#), ASP.NET Core, EF Core + Npgsql
- Frontend: React (TypeScript preferred)
- Database: PostgreSQL
- Tracker: GitHub Issues (+ optional GitHub Projects), via the `gh` CLI
- Prefer the existing stack and patterns in this repo over anything new. Justify deviations in an ADR.

## The delivery chain (each arrow is a HUMAN APPROVAL GATE)

```
Requirement
  -> sdlc-requirements-analyzer  -> docs/requirements/<feature>.md            [review]
  -> sdlc-system-design          -> docs/design/<feature>.md + ADRs           [review]
     + sdlc-security-review (Mode A: threat model)                             [review]
  -> sdlc-backlog-breakdown      -> docs/backlog/<feature>-backlog.md + .json [review]
  -> push-backlog.sh --dry-run, then the real run                              [review]
  -> sdlc-feature-implementer    -> branch + TDD tests + code + draft PR       [review]
  -> sdlc-security-review (Mode B: diff/PR review) + CI scans                 [review]
  -> merge
```

Never skip a gate. Never start a later phase on an unapproved earlier artifact.

## Large requirements (packs)
- Single file up to about 40 requirements or 400 lines. Above that, use a pack of vertical slices (`sdlc-requirements-analyzer`, modes B and C).
- Pack IDs are slice-prefixed (`REQ-PREF-001`); small single-file features keep global IDs (`REQ-001`).
- Never load a whole pack into context. Read `00-index.md`, then one slice (`req-index.sh show --feature F --slice S` or `--id REQ-ID`).
- Design, backlog, and security work run one slice at a time; approvals are per slice (`sdlc-state.sh checkpoint --slice S` or `sdlc checkpoint --slice S`).
- An existing large document is split with `req-index.sh analyze | skeleton | split`: verbatim, with a coverage check; never rewrite requirement wording during a split.

## Session protocol (shared memory across clients)
Project memory lives in the repo so any client (Claude Code, Copilot, Cursor, OpenCode, Antigravity) can continue where another stopped.
1. **Start of every session:** run `sdlc resume` (or `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh resume`). Continue from the recorded next action. Do not
   rescan the repo; re-read only files the output lists as changed. Do not redo an approved gate.
2. **At every approval gate and before ending a session:** run `sdlc checkpoint` (or `sdlc-state.sh checkpoint`), then commit `.sdlc/`.
3. **Codebase map and graph:** use `.sdlc/memory/codebase-map.md` (refresh incrementally with `map-status` / `map-stamp`) and `sdlc-graph.sh` for traceability.
4. Memory is a hint, not truth. Verify against the repo when the commit differs. Never store secrets or personal data in it. Never hand-edit generated files.

## Skills
| Skill | Use it when |
|---|---|
| `sdlc-requirements-analyzer` | A feature idea, ticket, or request needs to become structured, testable requirements |
| `sdlc-system-design` | Approved requirements need architecture, data model, API contracts, NFRs, ADRs |
| `sdlc-backlog-breakdown` | An approved design must become epics, stories, tasks, spikes, and GitHub issues |
| `sdlc-feature-implementer` | An approved backlog story or GitHub issue needs implementation (branch, test scaffold, code, PR draft) |
| `sdlc-security-review` | Threat modeling a design, or reviewing a diff/PR/codebase for vulnerabilities |
| `sdlc-session-handoff` | Start of every session, every approval gate, and client switches: resume from, and checkpoint to, shared memory |

## Artifact locations
- `docs/requirements/<feature>.md` — requirements with REQ-IDs (small features), or `docs/requirements/<feature>/` — a requirements **pack** (large features): `00-index.md`, `slices/NN-<slug>.md`, `nfr.md`, `glossary.md`, `index.json` (generated)
- `docs/design/<feature>.md`, `docs/adr/NNNN-title.md` — design and decisions
- `docs/security/<name>-threats.md`, `<name>-review.md`, `<name>-findings.json`
- `docs/backlog/<feature>-backlog.md` (human) and `<feature>-backlog.json` (machine; schema in `.sdlc/schema/`)
- `.sdlc/config.yaml` — tracker config. `.sdlc/reports/` — scan output (git-ignored): `<feature>-findings.sarif` (SARIF 2.1.0) and `<feature>-findings.json` (schema `.sdlc/schema/findings.schema.json`)
- `.sdlc/state.json`, `.sdlc/HANDOFF.md`, `.sdlc/memory/` — shared cross-client memory (committed)

## Traceability
Use IDs end to end: `REQ-012` -> design section -> `E1-S3` -> GitHub issue `#123` -> PR. Every story
cites the REQ-IDs and design section it implements.

## Safety rules (all agents, all skills)
1. Do NOT create, edit, or close GitHub issues without showing a `--dry-run` plan and getting explicit approval.
2. Do NOT run destructive commands (delete, force-push, `DROP`, `git reset --hard`, prod deploys) without explicit approval.
3. Never print, log, or copy secrets, tokens, or connection strings. Reference `file:line` only and recommend rotation.
4. Never commit credentials. Use environment variables, `dotnet user-secrets`, or a secret manager.
5. Do not probe live or production systems. Reviews are static and in-repo.
6. Scripts do the deterministic work (build, scan, push). The model decides what to do and interprets results.
7. If something is unknown, write it under "Open Questions". Do not guess.
8. Prefer small, reviewable changes. One concern per PR.
9. Shared memory never replaces an approval gate: a recorded approval lets you continue, but new side effects (issue creation, destructive commands) still need approval.

## Conventions
- Diagrams: Mermaid in markdown (diffable).
- API: REST + OpenAPI, RFC 7807 `ProblemDetails` for errors, versioned routes.
- DB: migrations via EF Core; snake_case naming; `timestamptz`; no destructive migration without a rollback plan.
- Frontend: typed API client generated from OpenAPI where possible; no secrets in client bundles.
- Commits: conventional commits. PRs reference issue numbers.
