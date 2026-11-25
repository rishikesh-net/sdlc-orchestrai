# SDLCOrchestrAI

**A portable SDLC skill pack that takes AI coding agents from feature idea to tested PR—with human approval gates and security built in.**

SDLCOrchestrAI gives AI coding agents a repeatable, gate-driven workflow tuned for **.NET API + React + PostgreSQL** projects using **GitHub Issues** or **local Markdown tickets**. It runs from a single source of truth (`skills/` + `AGENTS.md`) across **Claude Code, GitHub Copilot, Cursor, OpenCode, and Google Antigravity**.

> **New here?** Follow the 5-minute walkthrough in [GETTING_STARTED.md](GETTING_STARTED.md).

---

## How it works

Six skills form the delivery chain. Each phase produces a reviewable artifact before the next begins—**every arrow is a human approval gate**.

```mermaid
flowchart LR
  A[Feature request] --> B[sdlc-requirements-analyzer]
  B -->|docs/requirements| C[sdlc-system-design]
  C -->|docs/design + ADRs| D[sdlc-security-review<br/>Mode A: threat model]
  D --> E[sdlc-backlog-breakdown]
  E -->|backlog.json| F[push-backlog.sh<br/>dry-run, then apply]
  F --> G[Tracker tickets<br/>Local MD or GitHub]
  G --> H[sdlc-feature-implementer<br/>branch + TDD + code + PR]
  H --> I[sdlc-security-review<br/>Mode B + CI scans]
  I --> J[Merge]
```

Traceability runs end to end: `REQ-012` -> design section -> `E1-S3` -> ticket `#123` -> PR.

---

## 2-Minute Quick Start

1. **Copy the pack into your repository** (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `skills/`, `scripts/sdlc*`, `scripts/sync-skills.sh`, `.sdlc/config.yaml`, `.sdlc/schema/`, and `.github/workflows/security.yml`).
2. **Check your environment and sync skills to your client:**
   ```bash
   python scripts/sdlc.py check-env
   python scripts/sdlc.py sync-skills
   ```
   *(Shortcut launchers: `scripts/sdlc.cmd` on Windows CMD/PowerShell, `./scripts/sdlc` on macOS/Linux.)*
3. **Start your first feature** by asking your AI client:
   > *"Here's the feature request: customers should be able to choose which email notifications they receive. Turn it into requirements using sdlc-requirements-analyzer."*

---

## Skills at a glance

| Skill | Purpose | Main output |
|---|---|---|
| `sdlc-requirements-analyzer` | Turns ideas or docs into structured, testable `REQ-` / `NFR-` requirements (supports vertical-slice packs for >40 REQs) | `docs/requirements/<feature>.md` |
| `sdlc-system-design` | Produces architecture, data model, API contracts, rollout plan, and ADRs | `docs/design/<feature>.md`, `docs/adr/*.md` |
| `sdlc-backlog-breakdown` | Splits approved design into vertical-slice stories with Given/When/Then criteria; pushes tickets idempotently | `docs/backlog/<feature>-backlog.{md,json}` |
| `sdlc-feature-implementer` | Guides story execution: feature branch, TDD test scaffolding, clean code, local verify, draft PR | Branch, tests, code, draft PR |
| `sdlc-security-review` | STRIDE threat modeling at design time; OWASP + stack security review of diffs/PRs with SARIF output | `docs/security/*-{threats,review}.md` |
| `sdlc-session-handoff` | **Opt-in** cross-client memory: checkpoint progress before switching clients and resume without rescanning | `.sdlc/state.json`, `.sdlc/HANDOFF.md` |

---

## Supported clients

Edit only `skills/` and `AGENTS.md`. Running `python scripts/sdlc.py sync-skills` generates local, `.gitignore`d copies for every client:

| Client | Instructions | Local skill folder |
|---|---|---|
| Claude Code | `CLAUDE.md` -> `AGENTS.md` | `.claude/skills/` |
| GitHub Copilot (VS Code) | `.github/copilot-instructions.md`, `AGENTS.md` | `.github/skills/` |
| Cursor | `AGENTS.md` | `.cursor/rules/*.mdc` |
| OpenCode | `AGENTS.md` | `.opencode/skills/` |
| Google Antigravity (IDE & client) | `AGENTS.md` | `.agent/skills/` |

---

## Guardrails & CI

- **Human gates between phases:** `python scripts/sdlc.py verify --gate <gate> --feature <slug>` validates `REQ-ID` uniqueness and cross-doc coverage before approval.
- **Dry-run before side effects:** `push-backlog.sh` always requires `--dry-run` review before creating GitHub or local tickets.
- **Security built in:** `.github/workflows/security.yml` auto-detects languages for CodeQL, runs `gitleaks` and dependency audits, and uploads SARIF artifacts.
- **Drift & state checks:** `.github/workflows/sync-check.yml` verifies skill generation, `state.json` schema validity, unit tests, and requirements packs.
- **No secrets in docs or memory:** Reports cite `file:line` only.

---

## Documentation map

| Guide | What it covers |
|---|---|
| [GETTING_STARTED.md](GETTING_STARTED.md) | Step-by-step setup, first feature walkthrough (6 prompts), daily cheat sheet, and troubleshooting |
| [skills/sdlc-requirements-analyzer/references/splitting-existing-docs.md](skills/sdlc-requirements-analyzer/references/splitting-existing-docs.md) | Splitting large (>40 REQ / >400 line) specs into vertical-slice packs with `req-index.sh` |
| [skills/sdlc-backlog-breakdown/references/tracker-adapters.md](skills/sdlc-backlog-breakdown/references/tracker-adapters.md) | `local` vs. `github` tracker adapters and `push-backlog.sh` options |
| [skills/sdlc-security-review/references/sarif.md](skills/sdlc-security-review/references/sarif.md) | Security scanner fallbacks (`scan-all.sh` / `sdlc scan`) and SARIF 2.1.0 output |
| [skills/sdlc-session-handoff/references/state-protocol.md](skills/sdlc-session-handoff/references/state-protocol.md) | Opt-in `resume` / `checkpoint` protocol when switching AI clients mid-feature |
| [AGENTS.md](AGENTS.md) | Shared stack conventions, safety rules, and approval gates for all agents |
