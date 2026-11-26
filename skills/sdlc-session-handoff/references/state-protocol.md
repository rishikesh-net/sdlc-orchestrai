# State protocol

## Session lifecycle
```
resume -> work (skills run, gates approved) -> checkpoint at each gate -> commit .sdlc/ -> end
```
A new client (or the same one tomorrow) runs `resume` and continues from `next_action`.

## state.json fields
| Field | Meaning |
|---|---|
| `updated_by`, `updated_at`, `repo_sha`, `repo_dirty` | Who wrote last, when (UTC), at which commit, and whether code had uncommitted changes |
| `features.<slug>.phase` | Current phase |
| `features.<slug>.gates` | Map of gate name to pending / in-review / approved / skipped |
| `features.<slug>.next_action` | The exact next step, written for a different client to execute |
| `features.<slug>.artifacts` | Repo-relative paths of requirement, design, backlog, and security files |
| `features.<slug>.open_questions` | Unresolved questions (closed with `--close-question`) |
| `features.<slug>.branch` | Working branch, if any |
| `features.<slug>.notes` | Last five short notes with time and client |

## Staleness rules
- `repo_sha == HEAD`: state is current.
- `repo_sha != HEAD` and commit exists: read `git diff --name-only <repo_sha>..HEAD`; re-verify only affected artifacts.
- Commit not found locally: fetch or check the branch. Treat the state as unverified and confirm with the user.
- `repo_dirty: true`: the previous session had uncommitted work. Run `git status` before assuming a clean base.

## Concurrency and merging
- `graph.jsonl` is append-friendly and normalized (sorted, de-duplicated). `.gitattributes` uses `merge=union`;
  after a merge run `sdlc-graph.sh normalize` and `validate`.
- `state.json` is JSON and cannot be union-merged. On a conflict, keep both features' entries, take the later
  `updated_at` for top-level fields, then run `python scripts/sdlc.py validate` and `render`.
- `HANDOFF.md` is generated; on any conflict, regenerate it with `python scripts/sdlc.py render`.
- Prefer one active writer at a time. If two people work in parallel, use separate feature slugs.

## What belongs in memory (and what does not)
Belongs: phase and gate status, decisions with pointers to ADRs, next steps, open questions, IDs and links.
Does not: secrets, tokens, connection strings, personal data, chat transcripts, large code excerpts, anything the repo already states clearly.

## Slice hashes
`features.<slug>.slice_hashes` maps a requirements slice slug to a content hash recorded at checkpoint time (`--slice`). `resume` recomputes the hash of
`docs/requirements/<feature>/slices/*-<slice>.md`; a difference means the slice changed after its last checkpoint. Gates scoped to a slice are named `<gate>:<slice>`.
