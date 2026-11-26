# Slicing guide

## When to use a pack
Use a single file up to about 40 requirements or 400 lines. Above that, use a pack. `python scripts/sdlc.py req analyze` applies these thresholds
(also: about 6000 tokens). Small features stay simple with global IDs (`REQ-001`); packs use slice-prefixed IDs (`REQ-PREF-001`).

## What a slice is
A **vertical slice** is one user-visible capability or journey, end to end: its requirements, rules, acceptance, and open questions.
It maps to one epic later. Good slices: "Notification preferences", "Unsubscribe and consent", "Audit trail", "Admin console".

Bad slicing and why:
| Split by | Problem |
|---|---|
| Document type (all functional, all NFR) | One capability's requirements scatter across files; breaks traceability |
| Layer (UI, API, DB) | Not a capability; produces horizontal work |
| One file per requirement | Hundreds of tiny files, no context, noisy diffs |
| Author or team | Boundaries change; not stable |

## Sizing
Aim for 150 to 300 lines (2 to 4k tokens) and 5 to 20 requirements per slice. `build` warns above 300 lines or about 4500 tokens.
Too big: split by sub-journey. Too small (fewer than 3 requirements): merge with the closest related slice.

## What goes where
| Content | Location |
|---|---|
| Capability requirements, rules, slice-specific NFRs, acceptance, open questions | the slice |
| Requirements that apply to every slice (security baseline, availability, retention, accessibility, audit) | `nfr.md` |
| Terms and definitions | `glossary.md` |
| Problem, goals, non-goals, actors, slice table, pack-level questions | `00-index.md` |
| Generated manifest | `index.json` (never hand-edit) |

## IDs
- Pack style: `REQ-<PREFIX>-NNN` and `NFR-<PREFIX>-NNN`, PREFIX is 2 to 8 uppercase letters/digits, unique per slice (`GEN` for `nfr.md`).
- IDs are stable. Never renumber after approval; retire an ID by marking it "Withdrawn" in place.
- Legacy IDs from an old document can be kept (`id_policy: keep`) when other documents or tickets refer to them.

## Dependencies and ordering
Declare `depends_on: other-slice` in front matter only for real prerequisites (shared data, a flow that must exist first).
Order slices so dependencies come first. Keep the graph shallow; a long chain means the slicing is off.

## Review and approval
Review and approve per slice. A slice edited after approval is flagged stale by `python scripts/sdlc.py req stale` and by `python scripts/sdlc.py resume`.
Use the status values draft, in-review, approved in front matter, and checkpoint with `--slice <slug>`.
