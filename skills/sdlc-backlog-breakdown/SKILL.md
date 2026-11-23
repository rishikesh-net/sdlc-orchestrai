---
name: sdlc-backlog-breakdown
description: Break an approved requirements doc and design doc into a product backlog - epics, vertical-slice user stories, technical tasks, and spikes with acceptance criteria, estimates, priorities, and dependencies - and create them as GitHub issues. Use this whenever the user wants to split work into issues or tickets, create a backlog, plan a sprint's work, write user stories, or push planned work to GitHub, even if they only say "break this down" or "create the issues". Always dry-runs first and never creates issues without approval.
---

# Backlog Breakdown (GitHub)

Input: approved `docs/requirements/<feature>.md` and `docs/design/<feature>.md`.
Output: `docs/backlog/<feature>-backlog.md` (human), `docs/backlog/<feature>-backlog.json`
(machine, validates against `.sdlc/schema/backlog.schema.json`), then GitHub issues via script.

## Workflow
1. Read requirements, design, ADRs, and `docs/security/<feature>-threats.md` if present.
   If the design is not approved, stop and say so.
2. Identify epics (major capabilities). Typically 1 to 4 per feature.
3. Split each epic into vertical-slice stories (see "Slicing" below). Each story delivers
   working, testable value end to end.
4. For every story write: title, user story (As a / I want / So that), Given/When/Then acceptance
   criteria, technical notes (components, endpoints, tables touched), `req_refs`, `design_ref`,
   estimate, priority, labels, `depends_on`.
5. Add separate tasks/spikes for work that is not a user-visible slice: infra, CI/CD, observability,
   security controls from the threat model, data migration/backfill, test automation, docs.
   Unknowns or risky items become a `spike` with a timebox and a question to answer, not a guess.
6. Validate every story against `references/story-quality-checklist.md` (INVEST + Definition of Ready).
   Check coverage: every REQ-ID appears in at least one item's `req_refs`.
7. Write the `.md` and `.json` files. Then show the user a summary table (id, type, title, estimate,
   priority, depends_on) and the coverage result. STOP for approval.
8. After approval, dry-run:
   `bash skills/sdlc-backlog-breakdown/scripts/push-backlog.sh --file docs/backlog/<feature>-backlog.json --dry-run`
   Show the plan. STOP for approval again.
9. Only after explicit approval, run the same command without `--dry-run`. The script writes issue
   numbers and URLs back into the JSON (`external`). Commit the updated JSON.

## Slicing (.NET + React + PostgreSQL)
- Good: "User can save notification preferences" = migration + API endpoint + React form + tests.
- Bad: "Create the database tables", "Build the API layer", "Build the UI" as separate stories.
- First story in an epic is usually a thin "walking skeleton" through all layers.
- Put shared groundwork (e.g. auth policy, base migration) in an explicit task that stories depend on, kept small.
- Target 1 to 3 days per story. If the estimate is above 5 points, split it or make it an epic.
- Order by risk and value: de-risk unknowns early with spikes.

## Fields and conventions
- `id`: `E1`, `E1-S1`, `E1-T1`, `E1-SP1`. Stable. The script keys idempotency on it and prefixes titles with `[id]`.
- `type`: epic | story | task | spike. `parent`: the epic (or story, for tasks).
- `priority`: P0 (blocker) to P3 (nice to have). `estimate`: story points (1, 2, 3, 5, 8) or null for epics/spikes.
- Security-driven items use labels `security` plus `severity:<level>` where relevant.
- Labels become GitHub labels automatically (`type:*`, `priority:*`, `estimate:*`, plus your own).

## Rules
- Never create issues, edit issues, or touch GitHub Projects without an approved dry-run.
- Every item traces to requirements (`req_refs`) and a design section (`design_ref`).
- Acceptance criteria must be testable and observable. Include at least one negative/error case per story.
- Do not invent requirements. Gaps go into a "Questions" section of the `.md`, not into stories.
- Re-running the script must not create duplicates. If it reports a failure, fix the cause and re-run.
- Prerequisites: `gh` (authenticated, with `repo` scope; add `project` scope for Projects), `jq`, `git`.

## Shared memory (cross-client continuity)
- Start of session: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh resume`. If `docs/backlog/<feature>-backlog.json` already has `external.key` values, issues were created: do not recreate, update instead.
- After writing the backlog files: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint --client <your-client> --feature <slug> --phase backlog --gate backlog=in-review --artifact docs/backlog/<slug>-backlog.json --artifact docs/backlog/<slug>-backlog.md --next "Human review of backlog; then dry-run push"`.
- Load the backlog into the graph: `bash skills/sdlc-session-handoff/scripts/backlog-to-graph.sh --file docs/backlog/<slug>-backlog.json --apply`, then `bash skills/sdlc-session-handoff/scripts/sdlc-graph.sh gaps` to confirm every requirement is covered.
- After the real push: re-run `backlog-to-graph.sh --apply` (to record issue numbers), then checkpoint `--phase build --gate backlog=approved --gate issues=approved --next "Implement <first story id>"`. Commit the updated JSON and `.sdlc/`.

## Large requirements (pack mode)
When requirements are a pack, break down **one slice at a time** so each backlog file stays reviewable:
1. Read `00-index.md`, then the slice (`bash skills/sdlc-requirements-analyzer/scripts/req-index.sh show --feature <feature> --slice <slice>`) and its design section `docs/design/<feature>/<slice>.md`.
2. One epic per slice. Use slice-prefixed IDs so files never collide: `E-<PREFIX>`, `E-<PREFIX>-S1`, `E-<PREFIX>-T1`, `E-<PREFIX>-SP1`.
3. Write `docs/backlog/<feature>/<slice>-backlog.json` (and a matching `.md`). Each item's `req_refs` lists the slice's REQ-IDs; add cross-slice `depends_on` only for real prerequisites.
4. Coverage: every REQ-ID of the slice appears in at least one item. Check with `bash skills/sdlc-session-handoff/scripts/backlog-to-graph.sh --file <file> --apply` then `sdlc-graph.sh gaps`.
5. Dry-run and push per slice file (`push-backlog.sh --file docs/backlog/<feature>/<slice>-backlog.json --dry-run`). Slice epics can be pushed independently, in dependency order.
6. Gate per slice: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint --client <your-client> --feature <feature> --phase backlog --slice <slice> --gate backlog=in-review --artifact docs/backlog/<feature>/<slice>-backlog.json`.
