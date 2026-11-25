# Getting Started with SDLCOrchestrAI

Go from a fresh repository to your first feature flowing through requirements, system design, threat modeling, backlog tickets, and a tested PR in **about 10 minutes**.

---

## 1. Prerequisites

| Tool | Needed for | Check |
|---|---|---|
| **Python 3.8+** | Universal CLI (`scripts/sdlc.py`) | `python --version` |
| **Git** | Branches and version control | `git --version` |
| **An AI client** | Claude Code, Copilot, Cursor, OpenCode, or Antigravity | — |
| **GitHub CLI (`gh`)** | *Optional* — only needed when pushing to GitHub Issues/PRs | `gh --version` |
| **Git Bash / WSL** | *Windows only* — needed for `push-backlog.sh`, `req-index.sh`, `scan-*.sh` | `bash --version` |

Optional security/stack tools: `gitleaks`, `semgrep`, `dotnet`, `npm` (missing tools are reported clearly by `check-env` and never block setup).

---

## 2. Install & Sync (2 Minutes)

1. **Copy the pack files** into the **root of your repository** (skip `scripts/tests/` and `docs/`):
   `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `skills/`, `scripts/sdlc*`, `scripts/sync-skills.sh`, `.sdlc/config.yaml`, `.sdlc/schema/`, and `.github/workflows/security.yml`.
   *(If `.gitignore` or `.github/` already exist, merge instead of overwriting.)*

2. **Choose your tracker in `.sdlc/config.yaml`:**
   - **Fastest 2-minute trial (zero auth):**
     ```yaml
     tracker: local
     local:
       output_dir: docs/backlog/tickets
     ```
   - **Team setup (GitHub Issues & Projects):**
     ```yaml
     tracker: github
     github:
       repo: your-org/your-repo
       project_number: ""     # optional GitHub Projects v2 number
       project_owner: ""      # optional; defaults to repo owner
     ```
     *(If using `github`, authenticate once: `gh auth login`.)*

3. **Run the environment check and sync skills to your client:**
   ```bash
   python scripts/sdlc.py check-env
   python scripts/sdlc.py sync-skills
   ```
   *(Shortcuts: `scripts/sdlc.cmd` on Windows, `./scripts/sdlc` on macOS/Linux.)*

4. **Verify your AI client sees the skills** by opening the repo and asking:
   > *"Which sdlc- skills do you have available?"*
   You should see all 6 skills (`sdlc-requirements-analyzer`, `sdlc-system-design`, `sdlc-backlog-breakdown`, `sdlc-feature-implementer`, `sdlc-security-review`, `sdlc-session-handoff`).

---

## 3. Your First Feature End-to-End

Try a small, real feature first. **Review each artifact before moving to the next step**—the human approval gates are where rework is prevented.

### Step 1: Requirements
- **Prompt:**
  > *Here's the feature request: customers should be able to choose which email notifications they receive. Turn it into requirements.*
- **Output:** `docs/requirements/<feature>.md` with `REQ-` / `NFR-` IDs, actors, and open questions.
- **Check:**
  ```bash
  python scripts/sdlc.py verify --gate requirements --feature <feature>
  ```

### Step 2: System Design & Threat Model
- **Prompt:**
  > *Design this feature from `docs/requirements/<feature>.md`.*
- **Output:** `docs/design/<feature>.md`, ADRs in `docs/adr/`, and `docs/security/<feature>-threats.md`.
- **Check (verifies every `REQ-ID` is covered in the design):**
  ```bash
  python scripts/sdlc.py verify --gate design --feature <feature>
  ```

### Step 3: Backlog Breakdown
- **Prompt:**
  > *Break the approved design into a backlog.*
- **Output:** `docs/backlog/<feature>-backlog.md` and `<feature>-backlog.json` (epics, 1–3 day vertical-slice stories, Given/When/Then criteria).
- **Check (verifies schema and 100% `REQ-ID` coverage):**
  ```bash
  python scripts/sdlc.py verify --gate backlog --feature <feature>
  ```

### Step 4: Dry Run, Then Create Tickets
- **Preview first (writes nothing):**
  ```bash
  bash skills/sdlc-backlog-breakdown/scripts/push-backlog.sh --file docs/backlog/<feature>-backlog.json --dry-run
  ```
- **Apply when satisfied** (re-running is idempotent and updates instead of duplicating):
  ```bash
  bash skills/sdlc-backlog-breakdown/scripts/push-backlog.sh --file docs/backlog/<feature>-backlog.json
  ```

### Step 5: Implement Story to PR
1. Inspect story criteria and start an isolated branch (`feat/<id>-<slug>`):
   ```bash
   python scripts/sdlc.py story show E1-S1
   python scripts/sdlc.py story start E1-S1
   ```
2. Ask your agent:
   > *"Implement story E1-S1 using sdlc-feature-implementer."*
   The agent scaffolds Given/When/Then tests first (TDD), implements minimal code, and runs local tests (`dotnet test` / `npm test`).
3. Verify the implementation gate and generate the PR body:
   ```bash
   python scripts/sdlc.py verify --gate implementation
   python scripts/sdlc.py story pr-body E1-S1 --output .sdlc/pr-body.md
   gh pr create --body-file .sdlc/pr-body.md
   ```

### Step 6: Pre-Merge Security Review
- **Prompt:**
  > *Security review my branch against main.*
- **Output:** `docs/security/<name>-review.md` with OWASP/stack findings and merge verdict.

---

## 4. Daily Cheat Sheet

| I want to... | Run or ask |
|---|---|
| Check environment & config | `python scripts/sdlc.py check-env` |
| Sync edited skills to clients | `python scripts/sdlc.py sync-skills` |
| Verify gate & `REQ-ID` coverage | `python scripts/sdlc.py verify --gate <gate> --feature <slug>` |
| Preview ticket creation | `bash skills/sdlc-backlog-breakdown/scripts/push-backlog.sh --file ... --dry-run` |
| Start implementing a story | `python scripts/sdlc.py story start E1-S1` |
| Generate PR description | `python scripts/sdlc.py story pr-body E1-S1 --output .sdlc/pr-body.md` |
| Run local security scans | `python scripts/sdlc.py scan --feature <slug>` |

---

## 5. Advanced Workflows (When You Need Them)

- **Large requirements (>40 REQs or >400 lines):** Use a vertical-slice pack (`docs/requirements/<feature>/`) with `skills/sdlc-requirements-analyzer/scripts/req-index.sh` (`analyze`, `skeleton`, `split --dry-run`, `split`, `show --slice`). See [splitting-existing-docs.md](skills/sdlc-requirements-analyzer/references/splitting-existing-docs.md).
- **Switching AI clients mid-feature (opt-in):** Run `python scripts/sdlc.py checkpoint --client <name> --feature <slug> --phase <phase> --next "..."` and commit `.sdlc/`, then run `python scripts/sdlc.py resume` in the new client. See [state-protocol.md](skills/sdlc-session-handoff/references/state-protocol.md).
- **CI enforcement:** Commit `.github/workflows/security.yml` and `.github/workflows/sync-check.yml`, and set your .NET/Node versions in `security.yml` if applicable.
- **Customize for your team:** Edit `skills/sdlc-system-design/references/design-principles.md`, `skills/sdlc-security-review/references/`, and `AGENTS.md`, then re-run `python scripts/sdlc.py sync-skills`.

---

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| Agent does not see `sdlc-*` skills | Run `python scripts/sdlc.py sync-skills` and restart the client session |
| Antigravity wrapper reads `.agents/` | Run `SDLC_SYNC_EXTRA=".agents/skills" python scripts/sdlc.py sync-skills` |
| `python` fails on Windows Store alias | Run via `scripts/sdlc.cmd <cmd>` (auto-detects installed Python) |
| `gh CLI not installed or not authenticated` | Use `tracker: local` for offline tickets, or install `gh` and run `gh auth login` |
| `jq is required` (Bash scripts) | Install `jq` (`winget install jqlang.jq`, `brew install jq`, `apt install jq`) |
| Windows `.sh` script errors | Run `.sh` scripts from Git Bash or WSL, not PowerShell/CMD |
| Duplicate skills in OpenCode | Remove `.opencode/skills` from `scripts/sync-skills.sh` and `scripts/sdlc.py` (OpenCode also reads `.claude/skills/`) |
