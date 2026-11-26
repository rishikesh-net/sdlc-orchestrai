---
name: sdlc-security-review
description: Security review for a .NET API + React + PostgreSQL codebase - STRIDE threat modeling of a design, and code review of a diff, PR, branch, or whole repo for OWASP-class vulnerabilities, secrets, vulnerable dependencies, authn/authz flaws, injection, and insecure configuration. Use this whenever the user mentions security, threat model, vulnerabilities, OWASP, pen-test findings, secrets, dependency risk, or asks "is this safe/secure", and always during sdlc-system-design and before merging significant PRs. Reports findings with severity and fixes; static analysis only; never changes code or pipelines without approval.
---

# Security Review

Two modes. Pick by context, or run both for a new feature.

## Mode A - Design time (threat model)
Input: `docs/design/<feature>.md`. Output: `docs/security/<feature>-threats.md`.
1. Read the design and requirements. List assets (data, credentials, money-like actions), actors
   (including attackers), entry points, and trust boundaries (browser/API, API/DB, API/third parties).
2. For each component and boundary apply STRIDE (`references/threat-model-stride.md`).
3. For each credible threat record: ID (`T-001`), description, affected component, likelihood,
   impact, severity, required control, and the REQ/NFR or design section it relates to.
4. List required security controls (authn/z model, input validation, encryption, secrets, logging/audit,
   rate limiting, backup/restore) and any new ADR-worthy decisions.
5. Emit `docs/security/<feature>-controls.json` in the backlog schema (`.sdlc/schema/backlog.schema.json`)
   with one task per control, labels `security` and `severity:<level>`, so `sdlc-backlog-breakdown` can merge them.
6. STOP for human review.

## Mode B - Code time (diff, PR, branch, or repo)
1. Determine scope: `git diff --stat origin/main...HEAD` for a branch/PR, or the paths the user names.
   List the trust boundaries the change touches.
2. Run the deterministic scans. They write SARIF 2.1.0 and normalized findings to `.sdlc/reports/`
   (never secret values). `--feature <slug>` names the report; default `repo`.
   - `python scripts/sdlc.py scan --feature <slug>` (all scanners, merged)
   - or one group: `python scripts/sdlc.py scan --only <secrets|sast|deps|iac> --feature <slug>`
   Read `.sdlc/reports/<slug>-findings.json` (`scanners[]` says ran/fallback/skipped) and, if triaging
   inline annotations, `.sdlc/reports/<slug>-findings.sarif`. See `references/sarif.md` for the output
   contract and severity mapping. Treat heuristic-only findings (`confidence: needs-verification`) as
   leads to confirm manually. If a tool is missing, say so and continue with manual review; do not
   install tools without approval.
3. Review manually against `references/owasp-checklist.md` and `references/dotnet-react-postgres.md`.
   Read the actual code paths (route -> authz -> validation -> data access -> response), not just the diff lines.
4. For every finding record: ID, title, severity, confidence (confirmed | likely | needs verification),
   `file:line`, what is wrong, a realistic exploit scenario, and a concrete fix (with a short code or
   config sketch). Never include secret values.
5. Write `docs/security/<name>-review.md` using the report format below. Emit
   `docs/security/<name>-findings.json` (backlog schema, type `task` or `story`, labels `security`,
   `severity:<level>`) for findings that will not be fixed in the current PR.
6. Give the user a short verdict: Block / Fix before merge / Merge with follow-ups / Clean, plus the top 3 issues.
7. STOP. With approval, fix specific findings. To file findings as GitHub issues, show a dry-run first:
   `python scripts/sdlc.py backlog push --file docs/security/<name>-findings.json --dry-run`

## Severity rubric
| Severity | Meaning | Examples |
|---|---|---|
| Critical | Remote, unauthenticated, high impact, easy | SQL injection on public endpoint, exposed admin without auth, committed live secret |
| High | Authenticated or harder to exploit, serious impact | IDOR exposing other users' data, missing authz on write endpoints, JWT signature not validated |
| Medium | Limited impact or needs unusual conditions | Missing rate limiting on login, verbose errors, weak CORS, outdated library with a hard-to-reach CVE |
| Low | Hardening or defense in depth | Missing security headers, overly broad log fields |
| Info | Observations, no action required | |

## Report format
```
# Security review: <name>
Scope: <branch/PR/paths>   Date: <date>   Verdict: <Block | Fix before merge | Merge with follow-ups | Clean>
## Summary (counts by severity)
## Findings
### SEC-001 [High] <title>   (confidence: confirmed)
- Location: path/File.cs:123
- Issue: ...
- Exploit scenario: ...
- Fix: ...
## Scan results (tool, status, summary counts)
## Out of scope / not reviewed
```

## Rules
- Static review only. Do not run exploits, fuzz, or contact live or production systems.
- Never print, copy, or paste a secret. Cite `file:line`, state the secret type, recommend rotation and
  history cleanup. Do not rotate or revoke anything yourself. Scanner reports must contain no secret
  values; keep them in `.sdlc/reports/` and reference `file:line` only.
- Do not inflate severity. Separate confirmed from "needs verification". Say what you did not review.
- Do not modify code, dependencies, CI, or infra without explicit approval.
- Prefer root-cause fixes (e.g. a default-deny authorization policy) over per-endpoint patches.
- If the PR adds a dependency, check maintenance, license, and known advisories before approving.

## Shared memory (cross-client continuity)
- Start of session: `python scripts/sdlc.py resume`. Reuse the codebase map to locate auth, data-access, and input-handling code instead of rescanning.
- Mode A: record threats as graph entities (`--kind threat --attr severity=high`) and controls as tasks, with `T-001 mitigated_by <task-id>`. Checkpoint `--phase threat-model --gate threat-model=in-review --artifact docs/security/<slug>-threats.md`.
- Mode B: record findings (`--kind finding --attr severity=high --attr status=open --attr location=path/File.cs:123`; never include secret values). After issues exist, add `python scripts/sdlc.py graph add-relation --from SEC-001 --rel tracked_by --to <task-id>`. Run `python scripts/sdlc.py graph gaps` to list unmitigated high threats and untracked high findings before issuing a verdict.
- Checkpoint `--phase security-review --gate security-review=in-review|approved --artifact docs/security/<name>-review.md --next "<verdict follow-up>"`.

## Large requirements (pack mode)
For a requirements pack, threat-model per slice plus once for the whole feature: read `nfr.md` and the overview of `docs/design/<feature>/` for cross-cutting
controls and trust boundaries, then load each slice's design section only when reviewing that slice. Save per-slice results as
`docs/security/<feature>/<slice>-threats.md`, and checkpoint with `--slice <slice> --gate threat-model=in-review`.
Optional parallel threat modeling: after the design overview and per-slice design exist, the lead can run
`python scripts/sdlc.py slices plan --feature <feature> --stage threat-model`, dispatch one agent per work order,
then `sdlc slices check --feature <feature> --stage threat-model` (checks unique `T-###` IDs and required sections).
Subagents must treat shared architecture as read-only and record cross-slice threats in their notes file for the lead.
See `skills/sdlc-session-handoff/references/parallel-orchestration.md`.
