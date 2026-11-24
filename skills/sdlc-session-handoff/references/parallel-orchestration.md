# Parallel slice orchestration

Use this for **requirements packs** only, after slices are approved. Requirements authoring (`new-slice`,
`split`, `build`) stays sequential. Parallel work covers per-slice **design**, per-slice **threat model**, and
per-slice **backlog**; the lead agent keeps every approval gate.

## Why it is safe

- One deterministic **work order** per slice scopes inputs, outputs, and rules.
- Subagents cannot write `.sdlc/state.json`, `index.json`, shared docs, or tickets.
- Fan-in is checked deterministically before human review.
- Human approval remains per slice; parallelism never skips a gate.

## 1. Plan (lead, deterministic)

```bash
# design: requires docs/design/<feature>/00-overview.md and slice status: approved
python scripts/sdlc.py slices plan --feature F --stage design --max-parallel 3

# after design per-slice gates are approved
python scripts/sdlc.py slices plan --feature F --stage threat-model
python scripts/sdlc.py slices plan --feature F --stage backlog

# inspect one order without writing
python scripts/sdlc.py slices show --feature F --stage design --slice S
```

Artifacts (git-ignored, regenerable):
```text
.sdlc/parallel/<feature>/<stage>/manifest.json
.sdlc/parallel/<feature>/<stage>/NN-<slug>.md      # work orders
.sdlc/parallel/<feature>/<stage>/<slug>-notes.md   # shared decisions / ADR proposals
```

`plan` skips slices whose prerequisites are not approved and reports why. `--include-unapproved` plans them
anyway with a warning. It never edits the pack, state, or index. It refuses to overwrite existing work
orders without `--force`.

## 2. Fan out (one agent per work order)

Give each agent only its work order (or the prompt in `templates/slice-agent-prompt.md.tmpl`). Honor the
manifest's `max_parallel`. Every agent must:
- read only the inputs listed in the work order;
- write only the listed outputs plus its own `*-notes.md`;
- never run `req-index.sh build`, `sdlc checkpoint`, `push-backlog.sh`, or `git commit`;
- report covered REQ IDs, open questions, and conflicts.

| Client | How to fan out | Notes |
|---|---|---|
| Claude Code | One subagent/Task per work order, fresh context | Pass the work-order path; limit concurrency |
| OpenCode | One Task per work order | If subagents are read-only, run write stages in separate sessions/terminals |
| Antigravity | One `run_workflow` step per manifest entry (fan-out), then a fan-in step | Pass work-order paths, not the whole pack |
| Copilot / Cursor | Sequential loop over `manifest.slices` | Same work order and rules; no native parallel writes |

No client API is required by the helper; the work-order file is the stable interface.

## 3. Fan in (lead, deterministic first)

```bash
python scripts/sdlc.py slices check --feature F --stage design
python scripts/sdlc.py slices check --feature F --stage threat-model
python scripts/sdlc.py slices check --feature F --stage backlog
```

`check` verifies outputs exist, requirements are covered, backlog epics/IDs are valid, threat IDs are
unique, and flags stale slice hashes. Reports:
`.sdlc/parallel/<feature>/<stage>/report.{md,json}`. Exit code is non-zero on failures.

Then use `templates/aggregation-checklist.md.tmpl`:
1. Read only `report.md`, `*-notes.md`, and ADR proposals.
2. Deduplicate shared models/components in `docs/design/<feature>/00-overview.md`.
3. Assign ADR numbers; move accepted proposals to `docs/adr/`.
4. Reconcile naming/NFR/error/auth decisions across slices.
5. Update traceability: `backlog-to-graph.sh --apply`, then `sdlc-graph.sh gaps`.
6. Human review per slice; lead checkpoints `--slice <slug> --gate <stage>=approved`.
7. Commit artifacts and `.sdlc/`; push backlogs only after approval (dry-run first).

## Stage outputs

| Stage | Per-slice output | Prerequisite |
|---|---|---|
| `design` | `docs/design/<feature>/<slice>.md` | `00-overview.md`; requirements slice approved |
| `threat-model` | `docs/security/<feature>/<slice>-threats.md` | design slice + design gate approved |
| `backlog` | `docs/backlog/<feature>/<slice>-backlog.json` + `.md` | design slice + design gate approved |

## Rules and failure handling

- Never parallelize `new-slice`, `split`, `build`, or edits to `00-index.md`.
- If a work order names a missing input, stop; do not invent it.
- If slices disagree on a shared entity, record both in the notes files and resolve in the overview.
- A stale slice hash in `check` means the requirements changed after planning: re-plan with `--force`
  and re-review the affected slice.
- If no slice is eligible, `plan` exits non-zero and lists the prerequisites that are missing.
