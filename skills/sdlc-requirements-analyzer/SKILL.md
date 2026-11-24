---
name: sdlc-requirements-analyzer
description: Turn a feature idea, ticket, email, or rough request into structured, testable requirements with IDs, actors, functional and non-functional requirements, constraints, assumptions, and open questions; and handle LARGE requirements by organizing them as a pack of vertical slices (index, slices, nfr, glossary), including splitting an existing big requirements document into slices. Use this whenever the user describes a new feature, epic, product need, or change request with no approved requirements doc yet, or says the requirements document is too big, too long, bulky, unwieldy, or needs to be split, sliced, broken up, or reorganized. Run it BEFORE sdlc-system-design. Does not design or write code.
---

# Requirements Analyzer

Three modes. Pick one in step 1.

| Mode | When | Output |
|---|---|---|
| A. Single file | Small feature (up to about 40 requirements or 400 lines) | `docs/requirements/<feature>.md` |
| B. Pack | New large feature | `docs/requirements/<feature>/` (index + slices + nfr + glossary) |
| C. Split an existing document | A large requirements document already exists (Word export, wiki page, long markdown) | a pack created from it, verbatim, with a coverage check |

Scripts: `bash skills/sdlc-requirements-analyzer/scripts/req-index.sh <command>` (needs bash, jq, awk, git).
Before starting, resume shared memory: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh resume`.

## 1. Choose the mode
- The user supplied a big existing document, or says it is too large/bulky: **Mode C** (see below).
- New feature: gather input, draft, and count requirements. If the draft would pass about 40 requirements or 400 lines, switch to **Mode B**.
- Otherwise **Mode A**.
- For Mode C, run `req-index.sh analyze --file <doc>` first. It states whether a pack is warranted and why.

## Mode A: single file
1. Gather input (chat, `gh issue view <n> --comments`, pasted doc). Inspect the repo briefly so requirements fit what exists.
2. Ask at most 5 blocking questions (users, scale, compliance/data sensitivity, deadlines, integrations). Do not ask what you can infer.
3. Draft `docs/requirements/<feature>.md` from `templates/requirements.md.tmpl` with global IDs (`REQ-001`, `NFR-001`).
4. Self-check against the quality rules. STOP for review. Checkpoint (see "Shared memory").

## Mode B: new pack
1. Scaffold: `req-index.sh init-pack --feature <slug> --title "<title>"`.
2. Define slices by user-visible capability or journey (read `references/slicing-guide.md`). For each:
   `req-index.sh new-slice --feature <slug> --slug <slug> --title "<title>" --prefix <PFX> --summary "<one line>" [--depends a,b] [--priority Must]`.
3. Fill each slice using slice-prefixed IDs (`REQ-PREF-001`, `NFR-PREF-001`). Put anything that applies to every slice in `nfr.md`; define terms once in `glossary.md`.
4. Fill the overview, out-of-scope, and pack-level questions in `00-index.md`.
5. `req-index.sh build --feature <slug>` then `validate`. Fix errors.
6. STOP for review. Approval is per slice (see "Shared memory").

## Mode C: split an existing large document
Follow `references/splitting-existing-docs.md` for details. Summary:
1. `req-index.sh analyze --file <doc>`: size, outline with line ranges, ID statistics, recommendation, and hints
   (`nfr?`, `glossary?`, `overview?`, `skip?`) on sections that look cross-cutting.
2. `req-index.sh skeleton --file <doc> --feature <slug> --title "<title>" --out docs/requirements/<slug>.split-plan.json`
   drafts a plan from the headings. Refine it: merge or rename slices, move sections between slices and cross-cutting,
   set prefixes, summaries, priorities, dependencies, and `id_policy`. Ask the user which ID policy they want
   (`keep` legacy IDs, recommended if other documents refer to them; or `renumber` to slice-prefixed IDs; `id-map.json` records every change).
3. Show the user the plan (slice names, what lines go where, what is skipped and why). **Wait for approval.**
4. `req-index.sh split --plan <plan> --dry-run`: must show full coverage (0 unassigned non-blank lines). Fix the plan until it does.
5. `req-index.sh split --plan <plan>`: writes the pack verbatim, keeps the original in `_source/`, writes `_split-report.md`.
6. Review `_split-report.md` with the user: dangling cross-references ("see section 3.2"), `_unassigned.md` if any, ID conflicts.
   Fix slices so each reads on its own, then `build` and `validate`.
7. STOP for review. Do not delete `_source/` until the user confirms the pack is complete.

Never rewrite requirement wording during a split. The script copies lines verbatim; only fix references and fill front matter.

## Quality rules (all modes)
- Every requirement has a unique ID and is atomic: one testable statement. Use "shall" for must-haves, "should" for nice-to-haves; tag priority (Must/Should/Could/Won't).
- Verifiable: replace "fast" with a number (e.g. p95 < 300 ms at 200 rps).
- WHAT and WHY, never HOW. No technology choices except existing hard constraints.
- Cover non-functional areas explicitly: performance, availability, security/privacy, auditability, accessibility (React UI), data retention, observability.
- Capture data requirements: what is stored, how long, who may see it, whether it is personal data.
- Unknowns go in "Open Questions" with an owner. Never invent answers. List out-of-scope items.
- Pack mode: slices are vertical (one capability end to end), each small enough to review alone (about 150 to 300 lines), cross-cutting items live once in `nfr.md`, and a slice never copies text from another slice (reference by ID).

## Output checklist
- [ ] Problem statement, goals/non-goals, actors
- [ ] Requirements with IDs and priority; measurable NFRs
- [ ] Data and integration requirements; constraints, assumptions, dependencies
- [ ] Open questions; acceptance summary
- [ ] Pack mode: `build` and `validate` clean, slice table in `00-index.md` accurate, every slice has summary and priority

## Shared memory (cross-client continuity)
- Mode A: when the draft is ready, `sdlc-state.sh checkpoint --client <your-client> --feature <slug> --phase requirements --gate requirements=in-review --artifact docs/requirements/<slug>.md --next "Human review of requirements"`; after approval set `approved` and `--phase design`.
- Mode B/C: approve **per slice**. For each slice: `sdlc-state.sh checkpoint --client <your-client> --feature <slug> --phase requirements --slice <slice-slug> --gate requirements=approved --artifact docs/requirements/<slug>/slices/<NN-slice>.md --next "..."`.
  This records the slice's content hash; later `resume` and `req-index.sh stale --feature <slug>` flag any slice edited after approval so its design and backlog get re-reviewed.
- Record requirements in the graph: Mode A: `sdlc-graph.sh add-entity --id REQ-001 --kind requirement --source <file>`. Mode B/C: `req-index.sh to-graph --feature <slug> --apply` (creates slice and requirement entities and `part_of` links).
- When all slices are approved: checkpoint `--phase design --next "Run sdlc-system-design, one slice at a time"`.
- Requirements authoring stays sequential (boundaries and IDs must stay consistent). Once slices are approved, the lead may fan out downstream
  design, threat-model, or backlog work: `python scripts/sdlc.py slices plan --feature <slug> --stage design` and `sdlc slices check`. Subagents
  must not edit the pack or `index.json`; see `skills/sdlc-session-handoff/references/parallel-orchestration.md`.
