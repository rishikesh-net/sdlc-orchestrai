# Tracker adapters

`push-backlog.sh` and `pull-backlog.sh` are tracker-neutral drivers. They source exactly one adapter
from this directory based on the configured tracker.

Selection precedence: `--tracker <name>` > `SDLC_TRACKER` > `.sdlc/config.yaml` `tracker:` > `github`.

| Adapter | Status | Requires |
|---|---|---|
| `github.sh` | Stable | `gh` authenticated (`repo` scope; `project` for Projects), `jq` |
| `local.sh` | Stable | `jq` (offline Markdown tickets) |
| Jira / Linear / Azure DevOps | Planned | Their public APIs (tokens via environment only) |

## Contract

The driver calls these functions after `source adapters/<tracker>.sh`. Implement all of them; no-ops are
fine (`return 0`) where a concept does not apply. Every adapter sets `ADAPTER_NAME`.

```text
ADAPTER_NAME                                # "github" | "local" | ...
adapter_init                                # validate config + credentials; no writes
adapter_describe                            # one-line target for the plan header
adapter_project_desc                        # optional extra header line (e.g. Projects)
adapter_dry_run_note                        # optional note printed after --dry-run
adapter_find ID                             # "key<TAB>url" or nothing
adapter_sync_labels FILE                    # ensure labels exist (no-op is OK)
adapter_create ID TITLE BODYFILE LABELS     # print "key<TAB>url"; nonzero on failure
adapter_update KEY TITLE BODYFILE LABELS    # nonzero + message on stdout on failure
adapter_refresh KEY BODYFILE                # update body only
adapter_link CHILDKEY PARENTKEY             # parent/sub-ticket linkage; best-effort
adapter_project_add KEY URL                 # optional board/project add
adapter_pull STATE LABEL LIMIT              # JSON array [{number,title,state,labels,url}]
```

Globals provided by the driver: `DRY` (1 for dry-run), `FILE` (backlog JSON path), `ONLY` (epic filter).
Helpers from `common.sh`: `bl_cfg`, `bl_die`, `bl_warn`, `bl_jqr`, `bl_jqc`, and `BL_ROOT`.

## Rules

- `--dry-run` must not create files, directories, tickets, or remote objects.
- Idempotency is keyed by the stable backlog `id`; reruns update rather than duplicate.
- On success, write `external: {tracker, key, url}` back to the backlog JSON (the driver does this).
- Never log or store credentials. For hosted trackers, read tokens from environment variables only.
- Use `bl_jqr`/`bl_jqc` (CRLF-safe) instead of raw `jq -r`/`jq -c` in adapters.
