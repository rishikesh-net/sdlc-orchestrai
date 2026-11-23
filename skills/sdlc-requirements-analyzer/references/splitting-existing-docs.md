# Splitting an existing large requirements document

Goal: turn one bulky document into a requirements pack **without losing or rewriting anything**, so downstream skills load one slice at a time.

## What the tooling guarantees
- Lines are copied **verbatim** from the source into slices, with a provenance comment (`<!-- source: file L40-L120 -->`).
- A coverage check requires every non-blank source line to be assigned to exactly one target or explicitly skipped. Overlaps and gaps fail the run.
- The original is kept in `_source/`. `_split-report.md` lists where every range went.
- With `id_policy: renumber`, every definition and every reference is rewritten consistently and `id-map.json` records old to new.

## Input formats
The script works on Markdown. For Word, PDF, or wiki exports convert first (for example `pandoc file.docx -t gfm -o file.md`), check that headings
survived, and put the result in `docs/requirements/_incoming/`. Do not split a file with no headings; add structure first or define ranges by line numbers.

## Procedure
1. **Analyze**
   `bash skills/sdlc-requirements-analyzer/scripts/req-index.sh analyze --file docs/requirements/_incoming/big.md`
   Read the recommendation, ID prefixes, duplicate-definition warnings, and the outline. If IDs are not detected (different style), pass
   `--id-regex '<ERE>'` (extended regex, no backslashes, for example `(R|FR)-[0-9]+`).
2. **Draft a plan**
   `req-index.sh skeleton --file <doc> --feature <slug> --title "<Title>" --out docs/requirements/<slug>.split-plan.json`
   (use `--level N` to slice at a different heading level; add `--id-policy renumber` if wanted).
3. **Refine the plan.** Open the JSON and decide:
   - `slices[]`: one per capability. Merge tiny sections, split huge ones (several `ranges` per slice are allowed). Set `title`, `summary`, `priority`, `depends_on`, and a unique `prefix`.
   - `cross_cutting.overview | nfr | glossary`: ranges that are shared by all slices.
   - `skip`: ranges to drop (table of contents, revision history). State why in `skip_reason`.
   - `id_policy`: `keep` (legacy IDs stay; best when tickets or other documents cite them) or `renumber` (slice-prefixed, uniform).
   Ranges are inclusive 1-based line numbers from `analyze`'s outline.
4. **Get the plan approved** by a human before writing anything.
5. **Dry-run**: `req-index.sh split --plan <plan> --dry-run`. Required: `Unassigned non-blank lines: 0`. If lines are unassigned, assign or skip them.
   Use `--allow-unassigned` only to park leftovers in `_unassigned.md` for manual placement.
6. **Split**: `req-index.sh split --plan <plan>`. Refuses to overwrite an existing pack unless `--force`.
7. **Review the report** (`_split-report.md`):
   - dangling references such as "see section 3.2" or "see above": rewrite them as links or requirement IDs
   - ID conflicts (the same legacy ID defined in two places)
   - slices that cannot be understood alone: add the missing context from the glossary or overview
8. **Finish**: fill `summary`, `priority`, `depends_on`, `owner` in each slice's front matter; then
   `req-index.sh build --feature <slug>` and `req-index.sh validate --feature <slug>`.
9. **Approve per slice** with `sdlc-state.sh checkpoint --slice <slice> --gate requirements=approved ...`, load the graph with
   `req-index.sh to-graph --feature <slug> --apply`, and commit the pack. Keep `_source/` until everyone agrees the pack is complete.

## Plan format
See `templates/split-plan.example.json`. Fields: `feature`, `title`, `source`, `id_policy` (keep | renumber), optional `id_regex`,
`slices[] {slug, title, prefix, summary, priority, depends_on[], ranges[[start,end],...]}`,
`cross_cutting {overview, nfr {prefix, ranges}, glossary} `, `skip [[start,end],...]`, `skip_reason`.

## Edge cases
| Situation | What to do |
|---|---|
| Requirement text spans a slice boundary | Move the range boundary; do not edit lines mid-requirement |
| A requirement applies to several slices | Put it once in `nfr.md` (cross-cutting) and reference its ID from slices |
| Same legacy ID defined twice | `analyze` warns; fix in the plan (keep the correct one, or renumber) and review `id-map.json` conflicts |
| IDs not detected | Use `--id-regex`; or use `renumber` after adding IDs manually |
| No headings | Add headings first, or write ranges by line numbers |
| Source changes after splitting | Re-split into a new feature slug and diff, or edit slices directly; the pack is now the source of truth |
| Very large (over 500 requirements) | Group slices into themes with two packs, or add a sub-folder per theme; keep each slice under 300 lines |

## After the split
Downstream skills (`sdlc-system-design`, `sdlc-backlog-breakdown`, `sdlc-security-review`) read `00-index.md` and one slice at a time, using
`req-index.sh show --feature <slug> --slice <slug>` or `--id <REQ-ID>`. Do not paste the whole pack into context.
