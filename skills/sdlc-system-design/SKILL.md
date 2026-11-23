---
name: sdlc-system-design
description: Produce a technical design for a feature or epic from approved requirements - architecture, components, data model (PostgreSQL), API contracts (.NET), React frontend structure, non-functional requirements, risks, and ADRs. Use this whenever the user asks how to build, architect, design, or structure something, wants a design doc, ADR, C4 diagram, schema, or API contract, or is about to break work into stories. Always includes a security threat-model pass via sdlc-security-review. Does not write implementation code.
---

# System Design

Input: `docs/requirements/<feature>.md` (approved). Output: `docs/design/<feature>.md` plus ADRs.
Default stack: ASP.NET Core API, EF Core + Npgsql, PostgreSQL, React. Read
`references/design-principles.md` before designing.

## Workflow
1. Read the requirements. If missing or unapproved, run `sdlc-requirements-analyzer` first.
2. Inspect the repo: existing projects, layering, auth setup, DB schema/migrations, API style,
   frontend structure, CI. Reuse what exists.
3. Ask the user only about blockers (scale, latency, compliance, integration constraints).
4. Draft `docs/design/<feature>.md` from `templates/design-doc.md.tmpl`:
   - Context, goals, non-goals; requirement coverage matrix (every REQ/NFR maps to a design section)
   - Architecture overview: Mermaid C4 context and container diagrams (see `references/design-principles.md`)
   - Components and responsibilities (API modules, background workers, React feature areas)
   - Data model: tables, keys, indexes, constraints, retention; migration and rollback plan
   - API contracts: endpoints, request/response shapes, status codes, error model, authz per endpoint
   - Frontend design: routes, state/data fetching, key components, error and loading states
   - NFR treatment: performance, scalability, availability, observability, cost
   - Security design summary (filled after the threat model)
   - Alternatives considered with trade-offs; risks; assumptions; open questions
5. Write an ADR (`templates/adr.md.tmpl`) in `docs/adr/NNNN-title.md` for every significant decision.
   Each ADR needs at least one rejected alternative.
6. Run the `sdlc-security-review` skill in Mode A (threat model). Fold its required controls back into the
   design and flag them for the backlog.
7. STOP. Present the summary, decisions needing approval, and open questions. Do not start
   `sdlc-backlog-breakdown` until the design is approved.

## Rules
- Prefer the existing stack and patterns. New technology needs an ADR with a clear reason.
- Design for the stated NFR numbers, not generic best practice. Say what you are NOT designing for.
- Mark unknowns as Open Questions, never guess.
- Keep diagrams as Mermaid text so they diff in PRs.
- Call out irreversible or expensive-to-change decisions (schema shape, public API, auth model).
- Include a rollout plan: feature flags, migration ordering, backward compatibility, rollback.
- Do not write implementation code. Short DDL/OpenAPI/interface sketches are fine as design artifacts.

## Shared memory (cross-client continuity)
- Start of session: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh resume`. Reuse the codebase map for step 2; re-read only the paths it lists as changed.
- After the design draft: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint --client <your-client> --feature <slug> --phase design --gate design=in-review --artifact docs/design/<slug>.md --next "Human review of design; then threat model"` (add each ADR path with `--artifact`).
- Record structure in the graph: design sections (`--kind design_section`, e.g. id `DS-<slug>-api`), ADRs (`--kind adr`), and relations `DS-... covers REQ-...` and `ADR-... relates_to DS-...`.
- After the threat model (via `sdlc-security-review` Mode A) checkpoint `--gate threat-model=in-review`; after approvals set `design=approved`, `threat-model=approved`, `--phase backlog`, `--next "Run sdlc-backlog-breakdown"`.

## Large requirements (pack mode)
If the requirements are a pack (`docs/requirements/<feature>/` with `00-index.md`, `slices/`, `nfr.md`) instead of a single file:
1. Read `00-index.md` and `nfr.md` first. Do **not** load every slice.
2. Design **one slice at a time**. Load it with `bash skills/sdlc-requirements-analyzer/scripts/req-index.sh show --feature <feature> --slice <slice>` (or one requirement with `--id <REQ-ID>`).
   Respect `depends_on`: design prerequisite slices first.
3. Write a design overview `docs/design/<feature>/00-overview.md` (architecture, shared components, data ownership, cross-cutting NFR treatment)
   and one section file per slice `docs/design/<feature>/<slice>.md`. Every requirement ID in the slice maps to a design section (coverage matrix per slice).
4. Gate per slice: `bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint --client <your-client> --feature <feature> --phase design --slice <slice> --gate design=in-review --artifact docs/design/<feature>/<slice>.md`.
   Run `bash skills/sdlc-requirements-analyzer/scripts/req-index.sh stale --feature <feature>`: if a slice changed after approval, re-review its design before continuing.
5. Record slice-to-design links in the graph (`DS-<slice> covers REQ-...`).
