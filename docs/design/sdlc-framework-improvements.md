# Realistic Improvement Plan for SDLCOrchestrAI

## 1. Executive Summary & Assessment

**SDLCOrchestrAI** already exhibits strong software engineering foundations that distinguish it from ad-hoc prompting frameworks:
- **Deterministic tooling over hallucination**: Critical operations (ID indexing, slice splitting, state checkpoints, backlog pushing) are driven by deterministic shell scripts rather than unconstrained LLM generation.
- **Strict Human Approval Gates**: A formal delivery chain (`Requirements -> System Design + Threat Model -> Backlog Breakdown -> Push Backlog -> Implementation -> Security Review`) ensures that AI never writes code against unapproved architecture.
- **Shared Memory Across Coding Clients**: Unified state protocols (`.sdlc/state.json`, `.sdlc/HANDOFF.md`, `.sdlc/memory/`) allow seamless context transitions across Claude Code, GitHub Copilot, Cursor, OpenCode, and Antigravity.
- **Scalability via Requirements Packs**: Slice-based requirement decomposition prevents context window exhaustion on large features.

However, a close examination of `README.md`, `GETTING_STARTED.md`, `skills/`, `.sdlc/`, and daily development workflows reveals **seven critical, pragmatic gaps** that hinder developer experience, platform reach, and production velocity.

---

## 2. Identified Gaps & Realistic Improvements Matrix

| Area | Current State | Realistic Improvement | Impact / ROI |
|---|---|---|---|
| **1. Platform Portability** | All scripts are Bash + `jq` (`.sh`). Windows users struggle in PowerShell / CMD unless WSL or Git Bash is configured. | Provide a dual-mode strategy: native cross-platform Python CLI (`sdlc` runner) or PowerShell counterparts (`.ps1`). | **High**: Zero-friction setup on Windows, macOS, and Linux without external shell dependencies. |
| **2. The Implementation Void** | Delivery chain stops after `push-backlog.sh` and jumps to "implementation (branch + PR)" with no skill or guidance. | Add 6th core skill: `sdlc-feature-implementer` (or `sdlc-code-implementer`) to guide story-to-branch, TDD, and PR prep. | **Critical**: Bridges the gap between backlog tickets and actual production code changes. |
| **3. Automated Gate Verification** | Gate checkpoints (`sdlc-state.sh checkpoint`) are manual assertions without automated pre-flight consistency checks. | Add `sdlc verify-gate` / linter to deterministically check REQ-ID coverage, schema conformance, and orphan sections. | **High**: Prevents human reviewers from having to manually count and cross-verify ID mappings. |
| **4. Tracker Extensibility** | Hard-coded strictly to GitHub Issues and `gh` CLI. `config.yaml` tracker field is effectively single-tenant. | Introduce Tracker Adapters (GitHub, Jira, Linear, Azure DevOps, and Local/Offline Markdown). | **High**: Enables enterprise adoption where Jira or Azure DevOps is mandated. |
| **5. Security Review Fallbacks** | Scanners (`scan-sast.sh`, `scan-secrets.sh`) fail silently or skip if `semgrep` / `gitleaks` aren't installed. | Standardize report outputs to OASIS SARIF format; provide agent-executable heuristic fallbacks. | **Medium-High**: Unlocks CI/CD ingestion and guarantees basic baseline scans without external tool installation. |
| **6. Multi-Agent Swarm Orchestration** | Large requirement packs (5+ slices) must be analyzed sequentially by a single agent turn. | Enable parallel slice analysis and breakdown via subagents or client-native workflows (e.g., Antigravity `run_workflow`). | **High**: Accelerates large feature planning from hours to minutes while staying within token budgets. |
| **7. Onboarding & Environment DX** | Users manually check tools (`gh`, `jq`, `dotnet`, `node`) as described in `GETTING_STARTED.md`. | Introduce `sdlc check-env` command to check environment health, CLI authentication, and schema readiness. | **Medium**: Drastically reduces initial onboarding drop-off and triage friction. |

---

## 3. Deep-Dive: Proposed Improvement Specifications

### Improvement 1: Universal CLI & Cross-Platform Support (`sdlc` CLI)
#### The Problem
Currently, running `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh resume` requires Bash and `jq`. On Windows environments running PowerShell (such as this environment), calling bash scripts requires explicit shell bridges and `jq` in PATH, causing execution barriers.
#### The Solution
Create a lightweight, zero-dependency Python script `scripts/sdlc.py` that acts as a universal runner:
- Python 3 is universally installed on developer machines across Windows, macOS, and Linux.
- Replaces reliance on external `jq` by utilizing Python's built-in `json` and `argparse` libraries.
- Supports backwards-compatible wrappers so existing bash invocations like `sdlc-state.sh` continue to work unchanged.

```text
sdlc-orchestrai/
├── scripts/
│   ├── sdlc.py              # Single-file zero-dependency runner
│   ├── sdlc                 # Posix executable wrapper
│   ├── sdlc.cmd             # Windows CMD / PowerShell wrapper
│   └── sync-skills.sh       # Sync tool (updated to sync sdlc wrappers)
```

Commands provided:
- `sdlc check-env [--json]` (aliases: `check`, `doctor`, `preflight`, `soundcheck`)
- `sdlc resume [--client <name>]`
- `sdlc checkpoint [--gate <gate>] [--client <name>]`
- `sdlc verify [--gate <gate>] [--feature <name>]`

---

### Improvement 2: Complete the Delivery Chain with `sdlc-feature-implementer`
#### The Problem
The delivery chain defined in `AGENTS.md` is:
```text
Requirement -> System Design -> Backlog Breakdown -> push-backlog.sh -> [GAP] -> Security Review (Mode B)
```
The actual coding phase has no skill definition, templates, or guardrails. When an agent is instructed to "implement issue #4", it often creates code that forgets the design contract, ignores the acceptance criteria, or fails to link test cases to `REQ-xxx` IDs.
#### The Solution
Add `skills/sdlc-feature-implementer/`:
- **Role**: Guides the coding agent through executing a single story (`E<n>-S<m>`) or issue ticket.
- **Workflow**:
  1. **Story Intake**: Reads issue / story JSON, extracts AC, REQ-IDs, and referenced ADR / Design doc sections.
  2. **Branch Isolation**: Verifies clean git status and checks out `feat/<issue-id>-<short-slug>`.
  3. **Test-First Scaffold**: Scaffolds unit/integration tests directly derived from acceptance criteria (incorporating REQ-IDs in test names/annotations).
  4. **Implementation & Local Verification**: Implements minimal code adhering to stack defaults (.NET / React / PostgreSQL) and runs local build/test commands.
  5. **PR Preparation**: Generates a conventional commit and draft PR referencing the issue, design docs, and security considerations.

---

### Improvement 3: Automated Pre-Flight Gate Verification (`sdlc verify`)
#### The Problem
Human approval gates currently require the human reviewer to manually check:
- Did the backlog breakdown cover every single requirement ID in the design doc?
- Are any acceptance criteria missing Given/When/Then formatting?
- Is `docs/backlog/<feature>-backlog.json` compliant with `.sdlc/schema/backlog.schema.json`?
#### The Solution
Implement deterministic schema and traceability linting before any gate is marked approved:
- `sdlc verify requirements <feature>`: Validates ID format (`REQ-xxx` or `REQ-PREF-xxx`), uniqueness, and non-empty acceptance criteria.
- `sdlc verify design <feature>`: Asserts every `REQ-xxx` has a corresponding architecture section and required ADRs.
- `sdlc verify backlog <feature>`: Validates JSON against schema, checks 100% REQ-ID coverage, and ensures each story has story points and estimation tier.
- If verification fails, `sdlc checkpoint` will warn or block until resolved.

---

### Improvement 4: Pluggable Tracker Adapters (Jira / Linear / Azure DevOps / Local)
#### The Problem
`push-backlog.sh` directly invokes `gh issue create`. In real corporate setups, teams rarely use GitHub Issues exclusively; Jira and Linear dominate many software teams.
#### The Solution
Refactor `skills/sdlc-backlog-breakdown/scripts/` to use a modular adapter pattern based on `.sdlc/config.yaml`:

```yaml
tracker: jira  # Options: github | jira | linear | azure-devops | local

jira:
  host: "https://yourcompany.atlassian.net"
  project_key: "PROJ"
  epic_issue_type: "Epic"
  story_issue_type: "Story"

github:
  repo: "org/repo"
  project_number: ""

local:
  output_dir: "docs/backlog/tickets/" # For offline/local-only projects
```

- `push-backlog.sh` delegates to `adapters/github.sh`, `adapters/jira.sh`, `adapters/linear.sh`, or `adapters/local.sh`.
- Supports `--dry-run` universally across all tracker types.

---

### Improvement 5: SARIF Standard & Agent-Executable Security Fallbacks
#### The Problem
`sdlc-security-review` scripts (`scan-sast.sh`, `scan-secrets.sh`, `scan-deps.sh`) depend on external binaries (`semgrep`, `gitleaks`). When a developer or agent environment does not have these binaries installed, automated security checks are skipped, leaving vulnerabilities undetected until CI fails.
#### The Solution
1. **SARIF Standardization**: Output all scanner findings into `.sdlc/reports/<feature>-findings.sarif`. SARIF is natively rendered by GitHub Code Scanning, VS Code, and IDE plugins.
2. **Deterministic Built-in Heuristics**: If `gitleaks` is unavailable, `scan-secrets.sh` (or `sdlc scan secrets`) falls back to an embedded regex engine checking for common token patterns (AWS keys, private keys, connection strings, JWTs).
3. **Structured Findings JSON**: Maintain `.sdlc/reports/<feature>-findings.json` with severity levels, remediation steps, and file:line citations conforming to `.sdlc/schema/`.

---

### Improvement 6: Multi-Agent Parallel Slicing & Native Orchestration
#### The Problem
Large features (e.g. 50+ requirements split into 6 vertical slices) currently require sequential processing in a single chat turn. This is slow and risks forgetting context from earlier slices.
#### The Solution
Leverage modern multi-agent primitives for slice-level parallelism:
- **Index & Skeleton Phase**: Lead agent analyzes requirements and produces `00-index.md` and slice skeletons.
- **Parallel Fan-out**: Subagents (or Antigravity `run_workflow` / Claude Code subagents) are dispatched concurrently for each slice:
  - Agent A -> Slice 01 (Auth & Session)
  - Agent B -> Slice 02 (Payment & Checkout)
  - Agent C -> Slice 03 (Notification & Webhooks)
- **Aggregation Phase**: Lead agent validates cross-slice boundaries, deduplicates shared models, and aggregates the unified backlog graph (`sdlc-graph.sh`).

---

### Improvement 7: Developer Experience & Diagnostic Check (`sdlc check-env`)
#### The Problem
New developers often encounter silent failures during their first run because `gh` is unauthenticated, `jq` is not installed, or Git hooks are missing.
#### The Solution
Create an environment verification command `sdlc check-env` (with aliases `check`, `doctor`, `preflight`) that outputs a concise diagnostic report:
```text
[✓] Git repository initialized (.git found)
[✓] Python 3.10+ runtime available
[✓] Tracker configured: github (gh CLI v2.40 authenticated to way2solutions/sdlc-orchestrai)
[✓] Schemas valid in .sdlc/schema/
[!] Security scanner: semgrep found; gitleaks not found (using heuristic regex fallback)
[✓] Stack SDKs: dotnet (.NET 8.0 SDK), node (Node v20.10, pnpm v9)
Status: READY FOR SDLC WORKFLOW
```

Canonical Command: `sdlc check-env` (aliases: `check`, `doctor`, `preflight`, `soundcheck`).

---

## 4. Phased Implementation Roadmap

```mermaid
flowchart TD
    subgraph Phase 1: Foundations & Portability
        P1A["Cross-Platform Runner (sdlc.py)"]
        P1B["sdlc check-env Diagnostic Checker"]
        P1C["Automated Gate Linter (sdlc verify)"]
    end

    subgraph Phase 2: Workflow Completion
        P2A["New Skill: sdlc-feature-implementer"]
        P2B["Test-First Scaffolding Template"]
        P2C["Automated PR Preparation"]
    end

    subgraph Phase 3: Enterprise & Tooling
        P3A["Tracker Adapter Layer (Jira / Linear / Local)"]
        P3B["SARIF Security Reports & Heuristic Fallback"]
        P3C["Parallel Slice Orchestration"]
    end

    Phase 1 --> Phase 2
    Phase 2 --> Phase 3
```

### Phase 1: Foundations & Portability (Immediate High-Value Wins)
- [x] Save framework improvement plan to `docs/design/sdlc-framework-improvements.md`.
- [x] Implement `scripts/sdlc.py` and universal wrappers (`sdlc` and `sdlc.cmd`).
- [x] Implement `sdlc check-env` diagnostic (with aliases `check`, `doctor`, `preflight`).
- [x] Implement `sdlc verify` pre-flight gate check for requirements, design, and backlog schemas.
- [x] Update `scripts/sync-skills.sh` and sync with client folders (`.agent`, `.claude`, `.cursor`, `.opencode`, `.github`).

### Phase 2: Lifecycle Completion (Bridging Backlog to PR)
- [x] Create `skills/sdlc-feature-implementer/` with `SKILL.md`, references, and PR templates.
- [x] Define story execution protocol (branch -> test scaffold -> implementation -> local verify -> draft PR).
- [x] Connect `sdlc` CLI and checkpointing to support the implementation gate.
- [x] Update `AGENTS.md` delivery chain diagram and guidelines.
- [x] Update `README.md` and `GETTING_STARTED.md` with complete Phase 1 and Phase 2 workflows.

### Phase 3: Enterprise Extensibility & Advanced Orchestration
- [x] Abstract tracker logic into `adapters/` (GitHub, Jira, Linear, Local Markdown).
  - [x] Adapter contract + driver refactor (`push-backlog.sh`, `pull-backlog.sh`); GitHub parity.
  - [x] Local/offline Markdown adapter (`tracker: local`, `docs/backlog/tickets/<id>.md`).
  - [ ] Jira, Linear, and Azure DevOps adapters (planned follow-ups).
- [x] Add SARIF generation to `sdlc-security-review` scripts.
  - [x] `.sdlc/reports/<feature>-findings.sarif` (SARIF 2.1.0) + `<feature>-findings.json` (`.sdlc/schema/findings.schema.json`).
  - [x] Labeled heuristic fallbacks for secrets and SAST; missing tools recorded as `ran`/`fallback`/`skipped`.
  - [x] Non-blocking `scans` job uploads SARIF to GitHub Code Scanning.
- [x] Provide workflow templates for parallel slice processing via agent swarms.
  - [x] Deterministic fan-out/fan-in: `sdlc slices plan|show|check` with per-slice work orders and a manifest.
  - [x] Scoped subagent contract (no state/index/shared-doc/ticket writes) + lead-only aggregation and per-slice gates.
  - [x] Client-native templates (Claude Code subagents, OpenCode tasks, Antigravity `run_workflow`, Copilot/Cursor sequential fallback).
