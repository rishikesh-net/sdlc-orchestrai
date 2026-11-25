# Getting Started with sdlc-orchestrai

This guide takes you from an empty install to your first feature flowing through requirements, design,
a security threat model, and a GitHub backlog. Plan for about 30 minutes for setup and a first dry run.

## 1. Prerequisites
| Tool | Needed for | Check with |
|---|---|---|
| Python 3 (3.8+) | Universal runner (`scripts/sdlc.py`, launchers) | `python --version` or `sdlc check-env` |
| `git` | Version control & branch management | `git --version` |
| GitHub CLI `gh` | Creating and reading issues & PRs | `gh --version` |
| An AI client | Claude Code, GitHub Copilot (VS Code), Cursor, OpenCode, or Google Antigravity | n/a |

> [!TIP]
> **Environment Diagnostics**: Run `scripts/sdlc.cmd check-env` (Windows) or `./scripts/sdlc check-env` (macOS/Linux) to immediately check all prerequisites, SDKs, and tracker configuration.

Optional scanners (the scripts skip any that are missing and say so):
| Tool | Used by | Install hint |
|---|---|---|
| `gitleaks` | Secret scanning | https://github.com/gitleaks/gitleaks |
| `semgrep` | Static analysis | `pip install semgrep` |
| .NET SDK | NuGet vulnerability check & backend tests | https://dotnet.microsoft.com |
| Node.js and `npm` | npm audit & frontend tests | https://nodejs.org |

## 2. Install
1. Copy the contents of the `sdlc-orchestrai-skills` folder into the **root of your repository**.
   If `.gitignore` or `.github/` already exist, merge instead of overwriting.
2. Run the environment diagnostic:
   ```bash
   scripts/sdlc.cmd check-env     # Windows (or ./scripts/sdlc check-env on macOS/Linux)
   ```
3. Open `.sdlc/config.yaml` and set your tracker:
   ```yaml
   tracker: github          # or: local (offline Markdown tickets)
   github:
     repo: your-org/your-repo
     project_number: ""     # optional: GitHub Projects (v2) number
     project_owner: ""      # optional: defaults to the repo owner
   local:
     output_dir: docs/backlog/tickets
   ```
4. Authenticate GitHub (only for `tracker: github`):
   ```bash
   gh auth login
   gh auth refresh -s project    # only if you use GitHub Projects
   ```
5. Publish the skills to your local client folders:
   ```bash
   scripts/sdlc.cmd sync-skills   # (or bash scripts/sync-skills.sh)
   ```
6. In `.github/workflows/security.yml`, the `detect` job auto-detects committed source and CodeQL runs only for languages present (C#, JavaScript/TypeScript, Python). If your repo has .NET or Node code, replace the `TODO` .NET and Node versions with yours. For inline results in **Security > Code scanning** on a private repo, enable GitHub Code Scanning (GitHub Advanced Security); otherwise SARIF is still saved as a workflow artifact.

> **Rule of thumb:** edit only `skills/`, `AGENTS.md`, and `.sdlc/`. The client folders `.claude/skills/`,
> `.github/skills/`, `.opencode/skills/`, `.agent/skills/`, and `.cursor/rules/` are generated locally by `sdlc sync-skills`.

## 3. Verify your client sees the skills
Open the repo in your client and ask: **"Which sdlc- skills do you have available?"**
You should see all 6 core skills: `sdlc-requirements-analyzer`, `sdlc-system-design`, `sdlc-backlog-breakdown`, `sdlc-feature-implementer`, `sdlc-security-review`, and `sdlc-session-handoff`.

| Client | Where it reads from | If nothing shows up |
|---|---|---|
| Claude Code | `CLAUDE.md`, `.claude/skills/` | Restart the session; confirm the folder is in the workspace root |
| GitHub Copilot | `.github/copilot-instructions.md`, `.github/skills/` | Use agent mode; check your VS Code and Copilot versions support skills |
| Cursor | `AGENTS.md`, `.cursor/rules/` | Confirm the rules are enabled in Cursor settings |
| OpenCode | `AGENTS.md`, `.opencode/skills/` | Also reads `.claude/skills/`; see the duplicate-skill note in the README |
| Google Antigravity (IDE and client) | `AGENTS.md`, `.agent/skills/` | Reopen the workspace; if you use an SDK/CLI wrapper that reads `.agents/`, sync with `SDLC_SYNC_EXTRA=".agents/skills"` |

Client conventions change between releases, so consult each tool's documentation if a path has moved.

### Initialize shared memory (once)
```bash
bash skills/sdlc-session-handoff/scripts/sdlc-state.sh init
```
Then ask your agent: **"Build the codebase map using sdlc-session-handoff."** It fills `.sdlc/memory/codebase-map.md` and stamps it with the current
commit. Commit `.sdlc/`. From now on, every skill checkpoints progress there, so any client can resume.

## 4. Run your first feature end to end
Use a small, real feature the first time. Review each artifact before moving on. These gates are the point.

### Step 1: Requirements
Prompt:
> Here's the feature request: *customers should be able to choose which email notifications they receive.*
> Turn it into requirements.

Result: `docs/requirements/<feature>.md` with `REQ-` and `NFR-` IDs, actors, constraints, and open questions.
**Review:** Are requirements testable and measurable? Are open questions real? Approve or ask for changes.

Large feature or an existing big document? Use a requirements pack and see [section 5](#5-large-requirements-slices-and-splitting-an-existing-document).

### Step 2: System design and threat model
Prompt:
> Design this feature from `docs/requirements/<feature>.md`.

Result: `docs/design/<feature>.md`, ADRs in `docs/adr/`, and a threat model in `docs/security/<feature>-threats.md`.
**Review:** Does every requirement map to a design section? Are the data model, API contracts, and rollback plan clear?

### Step 3: Backlog
Prompt:
> Break the approved design into a backlog.

Result: `docs/backlog/<feature>-backlog.md` and `<feature>-backlog.json` (epics, vertical-slice stories, tasks, spikes).
**Review:** Are stories small (1 to 3 days)? Does each have Given/When/Then criteria and requirement references?
Is every requirement covered?

### Step 4: Dry run, then create tickets
```bash
bash skills/sdlc-backlog-breakdown/scripts/push-backlog.sh \
  --file docs/backlog/<feature>-backlog.json --dry-run
```
Read the plan table. When satisfied, run it again without `--dry-run`. Ticket references are written back
into the JSON; commit it. Re-running is safe and updates rather than duplicates.

The tracker comes from `.sdlc/config.yaml` (`tracker: github` or `tracker: local`). Override per command
with `--tracker <name>` or `SDLC_TRACKER`. With `tracker: local`, tickets are Markdown files under
`local.output_dir` (default `docs/backlog/tickets/`) and no `gh` authentication is needed. Details:
`skills/sdlc-backlog-breakdown/references/tracker-adapters.md`.

### Step 5: Feature Implementation (Story to PR)
Use `sdlc-feature-implementer` to write code against approved acceptance criteria with full traceability:

1. **Inspect story criteria and design**:
   ```bash
   sdlc story show E1-S1
   ```
2. **Start the story branch**:
   ```bash
   sdlc story start E1-S1
   ```
   This creates branch `feat/<issue-id>-<slug>` and updates `.sdlc/state.json`.
3. **Scaffold tests first (TDD)**:
   Convert each Given/When/Then statement in the acceptance criteria into automated test methods citing `[REQ-xxx]`.
4. **Implement minimal code**:
   Adhere to project stack rules (.NET ASP.NET Core, React TypeScript, PostgreSQL snake_case migrations).
5. **Verify locally**:
   ```bash
   dotnet test           # or npm test
   sdlc verify --gate implementation
   ```
6. **Generate PR draft and submit**:
   ```bash
   sdlc story pr-body E1-S1 > .sdlc/pr-body.md
   gh pr create --body-file .sdlc/pr-body.md
   ```

### Step 6: Security review before merge
Prompt:
> Security review my branch against main.

The skill runs the scans, reviews the code against the OWASP and stack checklists, and writes
`docs/security/<name>-review.md` with a verdict. To file leftover findings as issues, run the push script on
`docs/security/<name>-findings.json` (dry run first).

## 5. Large requirements: slices and splitting an existing document
A single `<feature>.md` becomes bulky fast: every phase has to load all of it and review is all-or-nothing. Above roughly **40 requirements or 400 lines**,
use a **requirements pack** of vertical slices instead. The agent decides this itself (`sdlc-requirements-analyzer` picks the mode), and you can also drive it by hand.

```
docs/requirements/<feature>/
  00-index.md        overview + generated slice table (read first)
  glossary.md, nfr.md
  slices/01-<capability>.md, 02-...      each with its own REQ-<PREFIX>-NNN IDs
  index.json         generated manifest (never hand-edit)
```
Set a shortcut for the commands below:
```bash
R=skills/sdlc-requirements-analyzer/scripts/req-index.sh
```

### A. Split an existing large requirements document
Use this when a big document already exists (an SRS, a wiki export, a long Markdown file).

**1. Put the document in the repo as Markdown.** Save it as `docs/requirements/_incoming/<name>.md`. For Word, PDF, or wiki content convert first
(for example `pandoc spec.docx -t gfm -o spec.md`) and check that headings survived. The splitter needs headings or explicit line ranges.

**2. Ask the agent, or run it yourself.** Prompt:
> Split docs/requirements/_incoming/notification-platform.md into a requirements pack using sdlc-requirements-analyzer. Keep the original IDs.

Or by hand, starting with an analysis:
```bash
bash $R analyze --file docs/requirements/_incoming/notification-platform.md
```
You get the size, an estimated requirement count, detected ID prefixes, duplicate-definition warnings, a recommendation (`pack` or `single-file`) with reasons,
and an outline with line ranges. Headings that look cross-cutting are tagged `[nfr?]`, `[glossary?]`, `[overview?]`, `[skip?]`.
If it reports no IDs but the document has them, add `--id-regex '<ERE>'` (extended regex, no backslashes), for example `(R|FR)-[0-9]+`.

**3. Draft a split plan from the headings.**
```bash
bash $R skeleton --file docs/requirements/_incoming/notification-platform.md \
     --feature notification-platform --title "Notification platform" \
     --out docs/requirements/notification-platform.split-plan.json
```
Add `--level 3` to slice at a deeper heading level, and `--id-policy renumber` if you want slice-prefixed IDs.

**4. Refine the plan (the important human step).** Open the JSON:

| Field | What to decide |
|---|---|
| `slices[]` | One per capability. Merge tiny sections, split huge ones (a slice can have several `ranges`). Set `title`, `summary`, `priority` (Must/Should/Could/Won't), `depends_on` (slice slugs), and a unique uppercase `prefix` |
| `cross_cutting.nfr / glossary / overview` | Ranges shared by every slice: security baseline, definitions, introduction |
| `skip` + `skip_reason` | Ranges to drop, such as the table of contents or revision history. Say why |
| `id_policy` | `keep`: legacy IDs stay as they are (best when tickets or other documents cite them). `renumber`: every ID becomes `REQ-<PREFIX>-NNN` / `NFR-<PREFIX>-NNN`, all references are rewritten, and `id-map.json` records old to new |

Ranges are inclusive, 1-based line numbers from the `analyze` outline. A worked plan is in `skills/sdlc-requirements-analyzer/templates/split-plan.example.json`.
Get a human to approve the plan before you write anything.

**5. Dry-run.**
```bash
bash $R split --plan docs/requirements/notification-platform.split-plan.json --dry-run
```
Required result: `Unassigned non-blank lines: 0 (full coverage)`. Errors you may see and the fix:

| Message | Fix |
|---|---|
| `overlap (slice:a / slice:b)` | Two ranges share lines; adjust a range boundary |
| `out of bounds` | A range runs past the end of the file |
| `every non-blank line must be assigned or skipped` | Assign the listed line ranges to a slice or to `skip` (or use `--allow-unassigned` to park them in `_unassigned.md`) |

**6. Split.**
```bash
bash $R split --plan docs/requirements/notification-platform.split-plan.json
```
It writes the pack, keeps the untouched original in `_source/`, builds `index.json`, and writes `_split-report.md`. It refuses to overwrite an existing pack unless you add `--force`.

**7. Review the report and fix the seams.** In `_split-report.md` check:
- *Possible dangling references* such as "see section 3.2" or "see above": rewrite them as links or requirement IDs.
- *ID conflicts* (the same legacy ID defined in two places) and the `id-map.json` conflicts list.
- Slices that cannot be understood alone: add context from the glossary or overview. Never reword the requirements themselves.
Then fill in each slice's front matter (`summary`, `priority`, `depends_on`, `owner`) and run:
```bash
bash $R build    --feature notification-platform
bash $R validate --feature notification-platform
```

**8. Approve per slice, load the graph, commit.**
```bash
bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint --client <your-client> --feature notification-platform \
     --phase requirements --slice notification-preferences --gate requirements=approved \
     --artifact docs/requirements/notification-platform/slices/01-notification-preferences.md --next "Design this slice"
bash $R to-graph --feature notification-platform --apply
git add -A && git commit -m "docs: split notification-platform requirements into slices"
```
Keep `_source/` until everyone agrees the pack is complete.

### B. Start a new large feature as a pack
```bash
bash $R init-pack  --feature billing --title "Billing platform"
bash $R new-slice  --feature billing --slug invoicing --title "Invoicing" --prefix INV --summary "Create and send invoices"
bash $R new-slice  --feature billing --slug payments  --title "Payments"  --prefix PAY --depends invoicing
bash $R build --feature billing && bash $R validate --feature billing
```
Or ask: *"Capture requirements for the billing platform as a requirements pack."* The agent scaffolds the pack, creates slices by capability, and fills them with prefixed IDs.

### C. Work one slice at a time
Design, backlog, and security review all read `00-index.md` and then **one slice**, never the whole pack:
```bash
bash $R show --feature billing --index                 # overview and slice table
bash $R show --feature billing --slice payments        # one slice
bash $R show --feature billing --id REQ-PAY-003        # just one requirement block
```
Typical prompts:
> Design the payments slice of billing.
> Break the payments slice into a backlog.
> Security review the payments slice.

Each skill writes per-slice artifacts (`docs/design/<feature>/<slice>.md`, `docs/backlog/<feature>/<slice>-backlog.json`, `docs/security/<feature>/<slice>-threats.md`)
and checkpoints with `--slice`. Create tickets per slice file with `push-backlog.sh` (dry-run first); slice epics can be pushed independently, in dependency order.

### C2. Parallel slice processing (optional)
Once slices are approved, the lead agent can fan out per-slice design, threat-model, or backlog work:

```bash
python scripts/sdlc.py slices plan  --feature billing --stage design --max-parallel 3
# dispatch one agent per work order in .sdlc/parallel/billing/design/, then:
python scripts/sdlc.py slices check --feature billing --stage design
```

`plan` skips slices without approved prerequisites and writes scoped work orders plus a manifest. Subagents
write only their assigned outputs and notes; they must not touch `.sdlc/state.json`, `index.json`, shared docs, or
tickets. The lead runs `check`, reconciles shared models/ADR proposals, gets human review, and checkpoints each
slice. Requirements authoring stays sequential. Client-specific dispatch patterns are in
`skills/sdlc-session-handoff/references/parallel-orchestration.md`.

### D. Keep the pack healthy
| Task | Command |
|---|---|
| After editing any slice | `bash $R build --feature F` then `validate` |
| Which approved slices changed since approval? | `bash $R stale --feature F` (also shown by `sdlc-state.sh resume`) |
| Coverage and risk gaps across the pack | `bash skills/sdlc-session-handoff/scripts/sdlc-graph.sh gaps` |
| Retire a requirement | Mark it "Withdrawn" in place; never renumber approved IDs |
| A slice grew past about 300 lines | Split it by sub-journey (`build` warns) |

Details and edge cases (requirement spanning a boundary, duplicate legacy IDs, very large specs): `skills/sdlc-requirements-analyzer/references/splitting-existing-docs.md` and `slicing-guide.md`.

## 6. Switch clients without losing your place
Example: you start in Claude Code and continue in OpenCode (or Cursor, Copilot, Antigravity).

1. **In the first client**, before you stop (skills do this at each gate; you can also ask: *"Checkpoint our progress"*):
   ```bash
   bash skills/sdlc-session-handoff/scripts/sdlc-state.sh checkpoint --client claude-code --feature notif \
        --phase design --gate design=in-review --next "Human review of design, then run threat model"
   git add -A && git commit -m "chore: checkpoint notif design"
   ```
2. **In the second client**, pull the branch and ask: *"Resume the SDLC work."* It runs `sdlc-state.sh resume`, which shows the handoff note,
   what changed in the repo since, and whether the codebase map is stale. It then continues from the recorded next action.
3. The second client re-reads **only** the changed files, does not redo approved gates, and checks that approved artifacts still exist.

Useful commands:
| Need | Command |
|---|---|
| Where are we? | `sdlc-state.sh resume` |
| Is the map stale? | `sdlc-state.sh map-status` (then `map-stamp` after refreshing) |
| Close an open question | `sdlc-state.sh checkpoint --feature F --close-question "exact text"` |
| Who covers REQ-001? | `sdlc-graph.sh find --rel implements --to REQ-001` |
| What is uncovered or risky? | `sdlc-graph.sh gaps` |
| Load a backlog into the graph | `backlog-to-graph.sh --file docs/backlog/F-backlog.json --apply` |
| Repair after a merge conflict | `sdlc-state.sh render`, `sdlc-graph.sh normalize`, then `validate` |

Keep in mind: always commit `.sdlc/`, never put secrets in memory files, and treat memory as a hint. If the commit differs, verify before trusting it.

## 7. Run the scans yourself
```bash
bash skills/sdlc-security-review/scripts/scan-all.sh --feature <slug>       # all scanners, merged
bash skills/sdlc-security-review/scripts/scan-secrets.sh --feature <slug>
bash skills/sdlc-security-review/scripts/scan-deps.sh --feature <slug>
bash skills/sdlc-security-review/scripts/scan-sast.sh --feature <slug>
SDLC_STRICT=1 bash skills/sdlc-security-review/scripts/scan-all.sh --feature <slug>   # non-zero on findings

python scripts/sdlc.py scan --feature <slug>                                # same runner via the CLI
python skills/sdlc-security-review/scripts/sarif.py validate .sdlc/reports/<slug>-findings.sarif
```
Reports land in `.sdlc/reports/`: `<slug>-findings.sarif` (SARIF 2.1.0 for GitHub Code Scanning and IDEs)
and `<slug>-findings.json` (normalized, schema `.sdlc/schema/findings.schema.json`). Missing tools fall
back to labeled heuristics and record `ran`/`fallback`/`skipped` per scanner. Secret values are never
written. The output contract is in `skills/sdlc-security-review/references/sarif.md`.

## 8. Turn on CI enforcement
1. Commit `.github/workflows/security.yml` and `.github/workflows/sync-check.yml`.
2. In GitHub, add branch protection on `main` and require the `security` and `skills-sync-check` checks.
3. If gitleaks asks for a license on your plan, add `GITLEAKS_LICENSE` as a repository secret (see the comment in the workflow).

## 9. Customize in your first week
1. Put your architecture standards and NFR targets in `skills/sdlc-system-design/references/design-principles.md`.
2. Add your compliance and threat priorities to `skills/sdlc-security-review/references/`.
3. Add two or three examples of good stories from your team to `skills/sdlc-backlog-breakdown/references/`.
4. Adjust conventions and approval gates in `AGENTS.md`.
5. Run `bash scripts/sync-skills.sh`, commit, and re-test on a feature whose design and backlog you already know.

## 10. Daily workflow cheat sheet
| I want to... | Say or run |
|---|---|
| Structure a new idea | "Turn this into requirements: ..." |
| Design an approved requirement | "Design this from docs/requirements/x.md" |
| Plan the work | "Break the approved design into a backlog" |
| Create tickets safely | `push-backlog.sh --file ... --dry-run`, then without the flag |
| Check for duplicates | `bash skills/sdlc-backlog-breakdown/scripts/pull-backlog.sh --state all` |
| Review security | "Security review my branch against main" |
| Check if a requirements doc is too big | `req-index.sh analyze --file <doc>` |
| Split a big requirements doc | `req-index.sh skeleton`, refine plan, `split --dry-run`, `split` (see section 5) |
| Load one slice or requirement | `req-index.sh show --feature F --slice S` or `--id REQ-ID` |
| Find slices edited after approval | `req-index.sh stale --feature F` |
| Continue after switching client | "Resume the SDLC work" (runs `sdlc-state.sh resume`) |
| Save progress | "Checkpoint our progress", then commit `.sdlc/` |
| Update a skill | Edit `skills/...`, run `bash scripts/sync-skills.sh`, commit |
| Check for drift | `bash scripts/sync-skills.sh --check` |

## 11. Troubleshooting
| Problem | Fix |
|---|---|
| Skills do not appear in the client | Re-run the sync, commit, restart the client, and check its docs for the current skills folder |
| `ERROR: set github.repo in .sdlc/config.yaml` | Set `github.repo` to `owner/name` or export `SDLC_REPO` |
| `gh CLI not installed or not authenticated` | Install `gh` and run `gh auth login` |
| `jq is required` | Install jq and reopen your shell |
| Project add fails | Run `gh auth refresh -s project` and check `project_number` and `project_owner` |
| Sub-issue link skipped | Your plan may not support sub-issues; the issue body still shows "Part of #N" |
| Scans say a tool is "not installed" | Install it or rely on CI; the skill reports the gap instead of guessing |
| `split`: unassigned or overlapping lines | Fix the ranges so each non-blank source line belongs to exactly one target or `skip`; re-run `--dry-run` |
| `analyze` finds no IDs | Pass `--id-regex '<ERE>'` matching your style, or add IDs first |
| `validate`: depends_on unknown slice / duplicate definition | Fix the slice slug in `depends_on`, or the repeated requirement ID; then `build` |
| Slice reported STALE | It changed after approval; re-review its design and backlog, then checkpoint again with `--slice` |
| `resume` warns the recorded commit is not found | Fetch or check out the branch the previous client used; until then treat the state as unverified |
| Handoff note looks outdated | Run `sdlc-state.sh render`; if state itself is stale, checkpoint again from the current client |
| Duplicate skills in OpenCode | Remove the `.opencode/skills` line from `scripts/sync-skills.sh` and delete that folder |
| Windows script errors | Run from Git Bash or WSL, not PowerShell or cmd |

## 12. Safety defaults to keep
- No issue creation, destructive command, or code change without explicit approval.
- Always dry-run before applying a backlog.
- Never paste secrets into prompts, docs, or issues; reports reference `file:line` only.
- Treat scanner output as evidence to triage, not as the final verdict.
- Treat shared memory as a hint: verify against the repo, keep secrets out of it, and commit it so other clients can use it.

Questions or improvements? Update the skills in `skills/`, sync, and open a PR; the sync check keeps every client aligned.
