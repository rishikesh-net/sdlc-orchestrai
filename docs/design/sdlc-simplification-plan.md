# SDLCOrchestrAI: Over-Engineering Audit & Hybrid Simplification Plan

## Goal Description

`docs/design/sdlc-framework-improvements.md` lists three phases of improvements (cross-platform `sdlc.py`, `sdlc-feature-implementer`, gate verification, tracker adapters, SARIF security outputs, parallel slice orchestration), almost all of which are now marked `[x]`.

An audit of `README.md`, `GETTING_STARTED.md`, `docs/design/sdlc-framework-improvements.md`, and the actual codebase under `scripts/`, `skills/`, `.sdlc/`, and `.github/workflows/` shows that **the pack has accumulated significant over-engineering and split-brain tooling**, while leaving several basic contracts broken.

This plan implements the **Hybrid ("Keep what pays for itself, cut what doesn't")** approach:
- **Keep** the deterministic tools that genuinely prevent LLM errors: `sdlc verify`, `push-backlog.sh` (`github` + `local` adapters with `--dry-run`), `req-index.sh` (for large packs), and `.github/workflows/security.yml`.
- **Fix** all broken contracts, CI drift, and repo hygiene issues.
- **Strengthen** `sdlc verify` with `verify_design` and cross-document `REQ-ID` coverage checks (`requirements -> design -> backlog`).
- **Cut / Archive** zero-ROI over-engineering: `graph.jsonl` (`sdlc-graph.sh`, `backlog-to-graph.sh`), `sdlc slices` (~450 lines + 5 templates), and duplicate state/sync implementations.
- **Make `sdlc-session-handoff` opt-in** (on client switch / long pauses rather than mandatory at every gate) and trim `AGENTS.md`, `README.md`, and `GETTING_STARTED.md`.

---

## Verified Over-Engineering & Broken Contracts

1. **Dual-Runtime Split-Brain**: `scripts/sdlc.py` (1,818 lines) duplicates `sdlc-state.sh` (13.5 KB) and `sync-skills.sh`, while ~88 KB of Bash + `jq` scripts remain separate.
2. **Premature Knowledge Graph (`graph.jsonl`)**: `.sdlc/memory/graph.jsonl` is 0 bytes in this repo; traceability already lives in `docs/backlog/*-backlog.json` (`req_refs`, `design_ref`, `external`).
3. **Heavy Parallel-Slice Orchestration (`sdlc slices`)**: ~450 lines in `sdlc.py` + `parallel-manifest.schema.json` + 5 templates + `parallel-orchestration.md` for an unused workflow.
4. **5-Way Client Copy & Sync Contradiction**: `.gitignore` ignores `.agent/`, `.claude/`, `.cursor/`, `.github/skills/`, `.opencode/`, yet `README.md` tells users to commit them and `.github/workflows/sync-check.yml` runs `sync-skills.sh` without `--check`.
5. **Broken Contracts in `sdlc-feature-implementer/SKILL.md`**: References `references/test-scaffold.example.*` (actually in `templates/`), runs `sdlc verify implementation` (invalid flag; must be `--gate implementation`), and uses `--phase build` while `state.json` uses `implementation`.
6. **Incomplete `sdlc verify`**: `--gate design` is accepted by `argparse` but no `verify_design()` exists; `verify_backlog()` doesn't check `REQ-ID` coverage against requirements.

---

## Proposed Changes

### Component 1: Fix Contracts, CI & Hygiene
- **`skills/sdlc-feature-implementer/SKILL.md`**: Fix `templates/test-scaffold.example.*` paths, `sdlc verify --gate implementation`, and align `--phase implementation`.
- **`.github/workflows/sync-check.yml`**: Validate skill generation via `python scripts/sdlc.py sync-skills --check` (after generating) and `python scripts/sdlc.py validate` (removing `sdlc-graph.sh validate`).
- **`.sdlc/reports/`**: Clean untracked local smoke-test artifacts (`cli-smoke-*`, `cygwin-smoke-*`, `final-smoke-*`, `final2-*`, `gb-all-*`), keeping only `.gitkeep`.

### Component 2: Strengthen `sdlc verify` & Prune Over-Engineering
- **`scripts/sdlc.py`**:
  - Add `verify_design(feature)` and `REQ-ID` coverage checks in `verify_backlog(feature)`.
  - Remove `cmd_slices_*` (~450 lines) and `slices` subcommands.
- **Prune zero-ROI files**:
  - Remove `skills/sdlc-session-handoff/scripts/sdlc-graph.sh`, `backlog-to-graph.sh`, `.sdlc/schema/graph.schema.json`, `.sdlc/memory/graph.jsonl`.
  - Remove `.sdlc/schema/parallel-manifest.schema.json`, `scripts/tests/test_slices.py`, `skills/sdlc-session-handoff/references/parallel-orchestration.md`, and `skills/sdlc-session-handoff/templates/{slice-work-order,slice-agent-prompt,aggregation-checklist}.md.tmpl`.

### Component 3: Consolidate Runtime & Streamline Docs
- **`skills/sdlc-session-handoff/scripts/sdlc-state.sh`**: Replace duplicated 13.5 KB Bash logic with a thin shim delegating to `scripts/sdlc.py` (`python3`/`python`).
- **`AGENTS.md`**: Trim to concise rules, make `sdlc-session-handoff` opt-in for client switches, and remove `graph.jsonl` / `sdlc slices`.
- **`skills/sdlc-session-handoff/SKILL.md`**: Update to reflect opt-in handoff and removal of `graph.jsonl` / `sdlc slices`.
- **`README.md` & `GETTING_STARTED.md`**: Remove "commit synced client folders" contradictions, remove `graph.jsonl` / `sdlc slices` sections, document the streamlined core loop, and sync skills to local client folders.

---

## Verification Plan
- Run `python -m unittest discover -s scripts/tests -v`
- Run `python scripts/sdlc.py check-env --json`
- Run `python scripts/sdlc.py verify --gate all`
- Run `python scripts/sdlc.py validate`
- Run `python scripts/sdlc.py sync-skills` and `python scripts/sdlc.py sync-skills --check`
