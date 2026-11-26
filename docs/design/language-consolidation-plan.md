# Design Plan: Single-Runtime Python Pack

**Status:** Approved (design)
**Goal:** Make SDLCOrchestrAI run on **Python 3.8+ standard library only**. Remove the `bash`/`jq`/Git Bash/WSL runtime dependency and the non-runtime language noise (`Shell`, `Go Template`, `C#`, `TypeScript`, `PowerShell`, `Batchfile`) without changing CLI contracts, outputs, or efficiency.

**Locked decisions**
1. **Architecture:** in-process Python modules behind `scripts/sdlc.py` (no new standalone CLIs).
2. **Launchers:** keep `scripts/sdlc.cmd` / `scripts/sdlc.ps1` for Windows UX and mark them `linguist-vendored`.
3. **Templates:** rename `*.md.tmpl` -> `*.template.md`.
4. **Back-compat:** delete `.sh` files immediately (no long-lived shims); update all call sites in the same phase and note the change.
5. **Dead scripts:** implement minimal Python equivalents for `sdlc-graph.sh` / `backlog-to-graph.sh`.

---

## 1. Audit (current repository)

| Area | Finding |
|---|---|
| Shell footprint | 14 tracked `.sh` (~1,300 lines); `jq` x73, `awk` x40, `sed` x30, `gh` x20 |
| CLI | `scripts/sdlc.py` already implements `init`, `render`, `resume`, `checkpoint`, `verify`, `story`, `install`, `validate`; `scan` delegates to `bash scan-all.sh` (`scripts/sdlc.py:1218-1229`) |
| Duplicates/shims | `scripts/sync-skills.sh` duplicates Python `sync-skills`; `skills/sdlc-session-handoff/scripts/sdlc-state.sh` is a 17-line shim |
| Security scanners | `scan-{all,secrets,sast,deps,iac}.sh` + `_scan_common.sh`; config modes via `sarif.py config --shell`; `sarif.py` supports `--type sarif` |
| Backlog | `push/pull-backlog.sh` + `adapters/{common,github,local}.sh` (jq-heavy) |
| Requirements | `req-index.sh` = 548 lines (jq/awk), **no tests today** |
| Language noise | 11 `*.md.tmpl`, `test-scaffold.example.cs`, `test-scaffold.example.tsx`, `sdlc.ps1`, `sdlc.cmd`, `scripts/sdlc` |
| Windows gaps | `test_backlog_adapters.py` and `test_scan_sast.py` skip on Windows (`bash`/`jq`); `check-env` warns when `jq` is missing (`scripts/sdlc.py:194-198`) |
| Dead references | Skills reference `sdlc-graph.sh` and `backlog-to-graph.sh`, which do not exist |
| CI | `.github/workflows/security.yml:68,89` and `.github/workflows/sync-check.yml:32` call bash scripts |

---

## 2. Target state

- **Single runtime:** Python 3.8+ standard library (`json`, `subprocess`, `pathlib`, `re`, `shutil`, `urllib`). No `bash`, `jq`, `awk`, or `pip` packages required for the core pack.
- **Single entry point:** `python scripts/sdlc.py <command>`.
- **Full OS parity:** all tests pass on Windows, Linux, and macOS with zero skips.
- **Clean language profile:** Python + Markdown; launchers are `linguist-vendored`.
- **Unchanged contracts:** identical flags, exit codes, file formats (JSON/Markdown), SARIF + normalized findings, and tracker write-back.

---

## 3. Architecture

`scripts/sdlc.py` remains the CLI and dispatch layer. Logic lives in importable skill-local modules; `sdlc.py` imports them in-process (no `bash`, no subprocess-to-Python chains).

| Module | Location | Responsibility |
|---|---|---|
| `sdlc_common.py` | `scripts/sdlc_common.py` | Repo root discovery, config parsing, slug/logging, shared IO |
| `scan.py` | `skills/sdlc-security-review/scripts/scan.py` | `secrets`, `sast`, `deps`, `iac`, `all` |
| `sarif.py` | `skills/sdlc-security-review/scripts/sarif.py` | SARIF/findings conversion and merge (existing) |
| `backlog.py` | `skills/sdlc-backlog-breakdown/scripts/backlog.py` | `push` / `pull` + local/github adapters |
| `req_index.py` | `skills/sdlc-requirements-analyzer/scripts/req_index.py` | Requirements pack commands |
| `sdlc.py` subcommands | `scripts/sdlc.py` | `scan`, `backlog push\|pull`, `req <...>`, `graph`, `backlog-to-graph` |

Rules:
- Modules are import-safe (`main()` guarded) and importable without side effects.
- `sarif.py` imports `sdlc_common.py`; the security module imports both.
- `install.py` copies `scripts/sdlc_common.py` (plus existing items); `skills/` is copied wholesale so skill-local modules ship automatically.

---

## 4. Phased plan

Each phase is independently shippable and updates docs, tests, CI, and `install.py` in the same change.

### Phase 0 — Guardrails (no behavior change)
- Add a CI matrix: `ubuntu-latest`, `windows-latest`, `macos-latest`.
- Add contract/golden tests:
  - `scan-*.sh` -> SARIF/findings shape (extend `test_sarif.py`, `test_scan_sast.py`).
  - `push/pull-backlog.sh` -> plan/apply output (extend `test_backlog_adapters.py`).
  - `req-index.sh` -> `analyze`, `build`, `validate`, `show`, `split --dry-run`, `stale` (new `test_req_index.py`).
- Add differential harness: `SDLC_IMPL=python|shell|shadow`. In `shadow`, run both implementations and diff normalized output; CI runs shadow on fixtures until parity.
- Add a light benchmark fixture for `req` and `scan`.

**Exit criteria:** matrix green; golden outputs captured; shadow harness documented.

### Phase 1 — Zero-risk cleanup
- Delete `scripts/sync-skills.sh` (Python `sync-skills` already exists) and `skills/sdlc-session-handoff/scripts/sdlc-state.sh` (shim); update references to `python scripts/sdlc.py`.
- Rename `skills/*/templates/*.md.tmpl` -> `*.template.md`; update `scripts/sdlc.py` template paths (pr-body, codebase-map) and all SKILL/reference mentions.
- Move `test-scaffold.example.{cs,tsx}` into `skills/sdlc-feature-implementer/references/test-scaffolding.md` as fenced code blocks; update the SKILL.
- Keep `scripts/sdlc.cmd`, `scripts/sdlc.ps1`, `scripts/sdlc`; add `.gitattributes` `linguist-vendored` for them.

**Exit criteria:** `Go Template`, `C#`, `TypeScript` no longer counted (0%); Shell reduced; no behavior change; tests green.

### Phase 2 — Security scanners -> `scan.py`
- Implement `scan.py` with `secrets|sast|deps|iac|all`, `--feature`, `--strict`, `--only`.
- Reuse `sarif.py` by import (refactor import-safe) and `sdlc_common.py` for config/root.
- Preserve external scanners and `auto|enabled|disabled` config from `.sdlc/config.yaml` (`scan_load_config`/`scan_mode` behavior), rule IDs/severities/messages, and `ran|fallback|skipped` statuses.
- Replace `git grep | cut | while read` heuristics with Python `re` over `git grep -l` / `git ls-files`; skip `.git`, `node_modules`, `bin`, `obj`, `dist`, `build`.
- `scripts/sdlc.py scan` calls the module in-process; remove the `bash` call and the "install Git Bash" error (`scripts/sdlc.py:1218-1229`).
- Update `.github/workflows/security.yml` to `python scripts/sdlc.py scan --feature ci` (and `SDLC_STRICT=1` where used).
- Delete `_scan_common.sh`, `scan-all.sh`, `scan-{secrets,sast,deps,iac}.sh`; update `references/sarif.md`, `SKILL.md`.
- Remove Windows skips in `test_scan_sast.py`; add secrets/deps/iac skip-path tests.

**Exit criteria:** all scanners run on Windows without bash; SARIF/findings unchanged; CI green.

### Phase 3 — Backlog -> `backlog.py` (removes `jq`)
- Implement `backlog.py` with `push` / `pull` and local/github adapters as Python modules/classes.
- Preserve `--file`, `--dry-run`, `--only`, `--tracker`; idempotency via `external.key`; labels; parent/dependency linking; Projects add; JSON write-back; output table; dry-run note.
- Use `subprocess.run(["gh", ...])` plus `json`; no `jq`.
- `check-env`: drop the jq prerequisite; local tracker is pure Python.
- Replace the bash `gh` shim in tests with a cross-platform fake `gh`; remove `os.name == "nt"` and `_bash_available` skips.
- Update `references/tracker-adapters.md`, `SKILL.md`, `GETTING_STARTED.md`.
- Delete `push-backlog.sh`, `pull-backlog.sh`, `adapters/*.sh` (5 files).

**Exit criteria:** push/pull work on all OSes without bash/jq; all backlog tests run on Windows.

### Phase 4 — Requirements index -> `req_index.py` (highest risk)
- Port `analyze`, `skeleton`, `split` (+`--dry-run`), `build`, `validate`, `show`, `stale`, `to-graph`, `init-pack`, `new-slice`.
- Replace awk/jq with Python frontmatter parsing, ID regex, line ranges, hashing, JSON, coverage checks; preserve `_source/`, `_split-report.md`, `index.json`, and content hashes.
- Land Phase 0 golden tests first; run `SDLC_IMPL=shadow` against `req-index.sh` on fixtures until normalized outputs match, then flip default to Python.
- Expose via `python scripts/sdlc.py req <...>`; update `.github/workflows/sync-check.yml` to `python scripts/sdlc.py req validate --feature ...`.
- Delete `req-index.sh`; update analyzer SKILL/references.

**Exit criteria:** byte/semantically stable outputs; shadow parity; CI green; zero skips.

### Phase 5 — Final sweep
- Delete remaining `.sh` files; remove or reclassify `scripts/sdlc` (already vendored if kept).
- Implement minimal Python `graph` and `backlog-to-graph` commands to replace the dead `sdlc-graph.sh` / `backlog-to-graph.sh` references; update the skills that mention them.
- Update `install.py PACK_ITEMS` (add `scripts/sdlc_common.py`; drop deleted files).
- Update `GETTING_STARTED.md` (remove Git Bash/WSL and `jq` prerequisites), `README.md`, `AGENTS.md`, and every `bash ...` example.
- Run `python scripts/sdlc.py sync-skills`, the full unittest suite on the 3-OS matrix, `check-env`, and an end-to-end dry-run push + scan in a temp repo.
- Add a guard CI check that fails if a tracked `.sh` reappears or `jq`/`bash ` returns to executable docs.

**Exit criteria:** no `.sh` tracked; language profile Python + Markdown (+ vendored launchers); all commands documented as `python scripts/sdlc.py`; guard active.

---

## 5. Efficiency

- One Python process per command; import modules instead of spawning `sarif.py`/`jq`.
- Stream files, precompile regexes, prefer `git ls-files` / `git grep` for tracked-set scanning.
- Skip heavy directories (`.git`, `node_modules`, `bin`, `obj`, `dist`, `build`, `.sdlc`).
- Lazy-import command-specific modules to keep `--help`/`check-env` fast.
- Benchmark gate: `req analyze` and `scan` no worse than ~2x current on the large fixture; log results.

---

## 6. Compatibility

- CLI flags, exit codes, output tables, JSON/Markdown shapes, SARIF 2.1.0, and tracker write-back stay identical.
- `.sh` deletion is immediate (pre-1.0); release notes call it out. Call sites (docs, skills, CI, agents) are updated in the same phase.
- `scripts/sdlc.py` remains the stable entry point; no new top-level executables.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `req-index` behavior drift | Golden tests + `shadow` differential parity; port last |
| Backlog edge cases (linking/labels/ids) | Golden plan tests; fake `gh` fixtures; idempotency tests |
| Windows path/encoding issues | 3-OS CI from Phase 0; `pathlib`, explicit UTF-8 |
| Scanner output changes | Reuse `sarif.py` converters; SARIF/findings snapshot tests |
| Install/distribution gaps | Update `PACK_ITEMS`; `sync-check` generation check |
| Module import side effects | Guard with `main()`; import-safe modules |

---

## 8. Deliverables checklist

- [ ] CI matrix (ubuntu/windows/macos) + guard check
- [ ] `scripts/sdlc_common.py`
- [ ] `scan.py` + delete 6 scan `.sh`
- [ ] `backlog.py` + delete 5 backlog `.sh`; `jq` removed
- [ ] `req_index.py` + delete `req-index.sh`; shadow parity
- [ ] Delete `sync-skills.sh`, `sdlc-state.sh`, remaining `.sh`
- [ ] Minimal `graph` / `backlog-to-graph` Python commands
- [ ] Templates renamed to `*.template.md`; examples moved to Markdown
- [ ] Launchers kept + `.gitattributes linguist-vendored`
- [ ] Docs/CI/AGENTS/install.py updated
- [ ] Zero skipped tests across OSes; language profile clean
