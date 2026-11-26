# Tracker adapters and local tickets

The backlog CLI works with more than GitHub. The neutral backlog JSON is the source of truth; an
adapter turns each item into a ticket in the configured tracker.

## Configuration

`.sdlc/config.yaml`:

```yaml
tracker: github        # github | local   (jira | linear | azure-devops are planned)

github:
  repo: your-org/your-repo
  project_number: ""   # optional GitHub Projects (v2)
  project_owner: ""

local:
  output_dir: docs/backlog/tickets   # relative to the repo root
```

Override without editing the file:

```bash
SDLC_TRACKER=local python scripts/sdlc.py backlog push --file ... --dry-run
python scripts/sdlc.py backlog push --file ... --tracker local --dry-run
```

Precedence: `--tracker` > `SDLC_TRACKER` > `tracker:` in config > `github`.
`SDLC_REPO` overrides `github.repo`; `SDLC_LOCAL_DIR` overrides `local.output_dir`.
Credentials (Jira/Linear/Azure DevOps, once implemented) come only from environment variables.

## Local Markdown tracker

`tracker: local` writes one file per item: `<output_dir>/<id>.md`.

```markdown
---
id: E1-S1
title: "Customer can view and save notification preferences"
type: story
parent: E1
state: open
priority: P1
estimate: 5
labels: ["component:api","component:web"]
depends_on: ["E1-T1"]
req_refs: ["REQ-001"]
design_ref: "docs/design/notification-preferences.md#6-api-contracts"
tracker: local
---

<body, acceptance criteria, requirement links, marker>
```

- Idempotent: re-running updates the same file; existing `state` is preserved.
- `external` becomes `{tracker: local, key: <id>, url: docs/backlog/tickets/<id>.md}`.
- `python scripts/sdlc.py backlog pull --tracker local` returns JSON with `number` set to the item id.
- Commit ticket files with the backlog JSON so offline planning is reviewable in git.

## Dry-run rules

`python scripts/sdlc.py backlog push --dry-run` never creates directories, files, issues, or project
entries. It prints the same plan table as a real run and exits 0. Always dry-run and get approval
before applying.

## Adding an adapter

Implement a class in `skills/sdlc-backlog-breakdown/scripts/backlog.py` with the same methods as
`LocalAdapter` and `GitHubAdapter`, then register it in `make_adapter()`. Requirements:

- Implement the full interface (`describe`, `project_desc`, `dry_run_note`, `find`, `sync_labels`,
  `create`, `update`, `refresh`, `link`, `project_add`, `pull`); no-ops are fine where a concept does
  not apply.
- Read credentials from environment variables only; never store them in config or reports.
- Keep `--dry-run` side-effect free.
- Be idempotent on backlog `id`; write back `external: {tracker, key, url}`.
- Use `json` and `pathlib` (no `jq`), and keep output CRLF-safe on Windows.
