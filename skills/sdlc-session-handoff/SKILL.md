---
name: sdlc-session-handoff
description: Optional shared, client-neutral project memory so work can continue across coding clients (Claude Code, Copilot, Cursor, OpenCode, Antigravity) or after long pauses. Use when the user asks to checkpoint, resume, switch clients, or build a codebase map. Reads and writes .sdlc/state.json, .sdlc/HANDOFF.md, and .sdlc/memory/codebase-map.md.
---

# Session Handoff (Shared Memory)

Client-native memory is siloed. This skill keeps optional project memory **in the repo** so any client can pick up where another stopped. Memory is a **hint, not truth**: always verify against the repo.

> **Opt-in by default:** For solo single-client work, git history and `docs/` artifacts are enough. Use `resume` / `checkpoint` when switching clients or pausing a multi-day feature.

## Files (committed to git when used)
| File | Purpose | Written by |
|---|---|---|
| `.sdlc/state.json` | Per-feature phase, gate statuses, next action, open questions, artifacts, notes | `sdlc checkpoint` |
| `.sdlc/HANDOFF.md` | Human-readable "where we left off" (generated from `state.json`; never edit by hand) | `sdlc render` |
| `.sdlc/memory/codebase-map.md` | Compact map of the repo so new sessions avoid full rescans | the agent |

CLI: `scripts/sdlc` / `scripts/sdlc.cmd` (or `python scripts/sdlc.py`, with `sdlc-state.sh` as a compatibility shim).

## 1. Resume (when switching clients or resuming a paused feature)
1. Run `python scripts/sdlc.py resume`. It prints the handoff note, compares the recorded commit with `HEAD`, and lists files changed since.
2. If there is no state yet, run `python scripts/sdlc.py init`.
3. Continue from `next_action`. Do **not** redo a phase whose gate is `approved`, but verify the approved artifact still exists.
4. Read only files changed since the recorded commit instead of rescanning the repo.

## 2. Checkpoint (before switching clients or ending a multi-day session)
```bash
python scripts/sdlc.py checkpoint \
  --client <claude-code|copilot|cursor|opencode|antigravity> \
  --feature <slug> --phase <phase> --gate <gate>=<status> \
  --artifact <path> --next "<exact next step>" [--question "<open question>"] [--branch <name>] [--note "<short note>"]
```
- Phases: `requirements`, `design`, `threat-model`, `backlog`, `issues`, `build`, `implementation`, `security-review`, `done`.
- Gate statuses: `pending`, `in-review`, `approved`, `skipped`.
- Never mark a gate `approved` unless the human approved it.
- Commit `.sdlc/` so the next client can read it.

## 3. Codebase map (optional)
Follow `references/codebase-map-guide.md` to write `.sdlc/memory/codebase-map.md` from `templates/codebase-map.md.tmpl` (aim for under 300 lines: structure, modules, API surface, DB schema summary, auth, build/test commands).

## Rules
- **Verify before trusting.** If `repo_sha` differs from `HEAD`, check changed files before acting on old state.
- **No secrets, tokens, credentials, or personal data** in any memory file. Use `file:line` references.
- **Write through `sdlc.py`** so formats stay consistent. Do not hand-edit `state.json` or `HANDOFF.md`.
- **Memory never replaces an approval gate.** A recorded approval lets you continue; it does not authorize new side effects.
