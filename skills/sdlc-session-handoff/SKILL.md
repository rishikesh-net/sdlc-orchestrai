---
name: sdlc-session-handoff
description: Shared, client-neutral project memory so work continues where the last session or client left off instead of rescanning the repo. Use this at the START of every session and whenever the user says continue, resume, where were we, what's the status, or is switching between clients (Claude Code, Copilot, Cursor, OpenCode, Antigravity); use it at every approval gate and before ending a session to checkpoint progress; use it to build or incrementally refresh the codebase map and the REQ-to-story-to-issue-to-PR-to-threat knowledge graph. Reads and writes .sdlc/state.json, .sdlc/HANDOFF.md, and .sdlc/memory/.
---

# Session Handoff (shared memory)

Client-native memory is siloed. This skill keeps project memory **in the repo** so any client can pick up
exactly where another stopped. Memory is a **hint, not truth**: always verify against the repo.

## Files (all committed to git)
| File | Purpose | Written by |
|---|---|---|
| `.sdlc/state.json` | Per-feature phase, gate statuses, next action, open questions, artifacts, notes | `sdlc-state.sh checkpoint` |
| `.sdlc/HANDOFF.md` | Human-readable "where we left off" (generated from state.json; never edit by hand) | `sdlc-state.sh render` |
| `.sdlc/memory/codebase-map.md` | Compact map of the repo with a commit stamp, so only changed areas are re-read | the agent, then `map-stamp` |
| `.sdlc/memory/graph.jsonl` | Knowledge graph: REQ, design, story, issue, PR, threat, finding and their links | `sdlc-graph.sh` |

Scripts: `skills/sdlc-session-handoff/scripts/sdlc-state.sh` and `sdlc-graph.sh` (need `bash`, `jq`, `git`).

## 1. Resume (start of every session)
1. Run `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh resume`. It prints the handoff note, compares the
   recorded commit with `HEAD`, lists files changed since, and reports whether the codebase map is current.
2. If there is no state yet (first session), run `sdlc-state.sh init`, then build the codebase map (step 3).
3. Continue from the recorded `next_action`. Do **not** redo a phase whose gate is `approved`, but do check that
   the approved artifact still exists and has not changed unexpectedly (`git log -- <artifact>`).
4. Read only what is stale: use the "changed files" list and the map to decide what to re-read. Do not rescan the repo.
5. Tell the user in two or three sentences where things stand and what you will do next.

## 2. Checkpoint (at every approval gate, and before a session ends)
```
bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint \
  --client <claude-code|copilot|cursor|opencode|antigravity> \
  --feature <slug> --phase <phase> --gate <gate>=<status> \
  --artifact <path> --next "<exact next step>" [--question "<open question>"] [--branch <name>] [--note "<short note>"]
```
- Phases: requirements, design, threat-model, backlog, issues, build, security-review, done.
- Gate statuses: pending, in-review, approved, skipped. Gates in use: requirements, design, threat-model, backlog, issues, security-review.
- Make `--next` concrete enough that a different client can act on it without asking.
- Never mark a gate `approved` unless the human approved it in this or a recorded earlier session.
- Then commit `.sdlc/` with the related work (or tell the user to). Uncommitted memory does not travel between machines.
- After conflicts or manual edits run `sdlc-state.sh render` and `sdlc-graph.sh normalize`.

## 3. Codebase map (avoid rescans)
1. First time: follow `references/codebase-map-guide.md` to write `.sdlc/memory/codebase-map.md` from `templates/codebase-map.md.tmpl`.
   Keep it compact (aim for under 300 lines): structure, modules, API surface, DB schema summary, frontend areas, auth, conventions, build/test commands.
2. Stamp it: `sdlc-state.sh map-stamp` (records the current commit).
3. Later: `sdlc-state.sh map-status` lists changed paths since the stamp. Re-read only those, update the affected map
   sections, then `map-stamp` again.

## 4. Knowledge graph
Use `sdlc-graph.sh` to record facts as you create them, so later questions are answered without re-reading documents.
```
sdlc-graph.sh add-entity --id REQ-001 --kind requirement --title "Customers choose notifications" --source docs/requirements/np.md
sdlc-graph.sh add-entity --id E1-S1 --kind story --attr issue=123
sdlc-graph.sh add-relation --from E1-S1 --rel implements --to REQ-001
sdlc-graph.sh import --file docs/security/np-graph.jsonl      # bulk upsert (entities and relations)
bash skills/sdlc-session-handoff/scripts/backlog-to-graph.sh --file docs/backlog/np-backlog.json --apply   # backlog -> graph
sdlc-graph.sh show E1-S1 | list --kind story | find --rel implements --to REQ-001
sdlc-graph.sh gaps        # uncovered requirements, unmitigated high threats, orphan stories, untracked findings
sdlc-graph.sh validate    # structure and dangling references
```
Kinds: feature, slice, requirement, nfr, design_section, adr, epic, story, task, spike, issue, pr, threat, control, finding.
Relations: implements, covers, depends_on, blocks, part_of, mitigated_by, closes, derived_from, tracked_by, found_in, relates_to.

## Rules
- **Verify before trusting.** If `repo_sha` differs from `HEAD`, check the changed files before acting on old state.
- **No secrets, tokens, credentials, or personal data** in any memory file. Use `file:line` references.
- **Store decisions, status, and pointers, not transcripts.** Keep notes short; the script keeps the last five.
- **Write through the scripts** so formats stay consistent. Do not hand-edit `state.json`, `HANDOFF.md`, or `graph.jsonl`.
- **Memory never replaces an approval gate.** A recorded approval lets you continue; it does not authorize new side effects (issue creation, destructive commands).
- **Say which client you are** via `--client` so the next session knows who wrote the state.
- Keep closed features out of the way: set `--phase done` and prune old notes when the file grows.

## Slice-scoped gates (requirements packs)
For large requirements organized as a pack, approve per slice: `sdlc-state.sh checkpoint --feature F --slice <slice> --gate requirements=approved ...`.
The gate is stored as `requirements:<slice>` and the slice file's content hash is recorded. `resume` reports `STALE SLICE: F/<slice>` when that file
changes afterwards (also `req-index.sh stale --feature F`). Treat a stale slice as needing re-review of its design and backlog before you rely on earlier approvals.

## Parallel slice orchestration (lead-mediated)
`python scripts/sdlc.py slices plan --feature F --stage design|threat-model|backlog` writes one scoped work order per eligible slice under
`.sdlc/parallel/F/<stage>/`; `sdlc slices check` verifies fan-in (coverage, missing/stale outputs, duplicate threats) and writes `report.{md,json}`.
Subagents must never write `.sdlc/state.json`, `index.json`, shared docs, or tickets, and must not checkpoint or commit. Only the lead checkpoints
per slice (`--slice`) after human review and commits `.sdlc/`. Requirements authoring stays sequential. Full workflow:
`references/parallel-orchestration.md`; templates: `templates/slice-work-order.md.tmpl`, `templates/slice-agent-prompt.md.tmpl`, `templates/aggregation-checklist.md.tmpl`.
