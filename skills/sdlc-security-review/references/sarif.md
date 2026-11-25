# Scanner reports: SARIF + normalized findings

Every security scanner writes deterministic reports to `.sdlc/reports/` (git-ignored). Reports are
**evidence for triage**, not the final review. Secret values are never written to a report.

## Files per run

| File | Purpose |
|---|---|
| `<feature>-findings.sarif` | Merged SARIF 2.1.0 for GitHub Code Scanning, VS Code, and IDE plugins |
| `<feature>-findings.json` | Merged normalized findings; schema `.sdlc/schema/findings.schema.json` |
| `<feature>-<scanner>.sarif` / `.json` | Per-scanner output kept for debugging |
| `<feature>-deps-dotnet-*.txt` | Raw `dotnet list package --vulnerable` text when JSON output is unavailable |

`<feature>` defaults to `repo`; set it with `--feature <slug>` or `SDLC_FEATURE`. Use a feature slug for
a feature review and `ci` in automation.

## Commands

```bash
# all scanners, then merge (recommended)
bash skills/sdlc-security-review/scripts/scan-all.sh --feature <slug>
python scripts/sdlc.py scan --feature <slug>          # same via the cross-platform CLI

# one scanner
bash skills/sdlc-security-review/scripts/scan-secrets.sh --feature <slug>
bash skills/sdlc-security-review/scripts/scan-sast.sh --feature <slug>
bash skills/sdlc-security-review/scripts/scan-deps.sh --feature <slug>

# report helpers
python skills/sdlc-security-review/scripts/sarif.py validate .sdlc/reports/<slug>-findings.sarif
python skills/sdlc-security-review/scripts/sarif.py count --feature <slug> --out-dir .sdlc/reports
```

Exit codes: `0` by default even with findings; `SDLC_STRICT=1` (or `--strict`) returns `1` when the
invoked scanner has findings. `scan-all.sh` aggregates all scanners.

## Tool fallbacks

| Scanner | Primary | Fallback |
|---|---|---|
| Secrets | gitleaks (redacted) | trufflehog (verified only) | labeled regex heuristics |
| SAST | Semgrep (OWASP/C#/React/TS rules) | conservative heuristics on application source files only (`*.cs`, `*.cshtml`, `*.ts`, `*.tsx`, `*.js`, `*.jsx`, `*.mjs`, `*.cjs`, `*.py`, `*.go`, `*.java`, `*.kt`, `*.rb`, `*.php`, `*.sql`) |
| Dependencies | `dotnet list package --vulnerable --format json`, `npm audit --json` | skipped with a recorded status |

The SQL-concatenation heuristic is case-sensitive (`\bSELECT\b...`) so tooling such as jq
`select(...) +` (or shell string concatenation) is not reported. Secrets scanning still covers shell
scripts, config, and other text files; only SAST heuristics use the application-source allowlist.

Missing tools are recorded in `<feature>-findings.json` under `scanners[].status`
(`ran` | `fallback` | `skipped`) so a reviewer can tell "no findings" from "not scanned". Heuristic
findings are medium/low confidence and should be confirmed manually before filing issues.

## Severity mapping

| Normalized | SARIF level | Typical source |
|---|---|---|
| `critical` | `error` | committed live secret, RCE-class SAST rule |
| `high` | `error` | gitleaks finding, high npm/NuGet advisory, semgrep `ERROR` |
| `medium` | `warning` | npm `moderate`, semgrep `WARNING`, heuristic SAST |
| `low` | `note` | hardening, semgrep `INFO`, weak-algorithm heuristic |
| `info` | `note` | observations |

## GitHub Code Scanning

`.github/workflows/security.yml` runs `scan-all.sh --feature ci` on pull requests and uploads
`ci-findings.sarif` with `category: sdlc-scanners`. The job is **non-blocking**: upload gives reviewers
inline annotations, while CodeQL and `SDLC_STRICT=1` jobs remain the enforcement layer.

Inline annotations in **Security > Code scanning** require GitHub Code Scanning, which is free on public
repos but needs GitHub Advanced Security (GHAS) on private repos. When it is unavailable the upload steps
are non-fatal and the SARIF is always saved as a workflow artifact (`sdlc-scans-sarif`,
`codeql-<language>-sarif`). CodeQL runs only for languages with committed source (C#,
JavaScript/TypeScript, Python), detected by the workflow's `detect` job.

## Curated findings vs scanner evidence

- `.sdlc/reports/<feature>-findings.json` — raw scanner evidence (this document). Regenerated on each run.
- `docs/security/<name>-findings.json` — curated findings written by the agent after triage, in the
  backlog schema, so `push-backlog.sh` can file them as issues.

Never paste secret values into `docs/security/`; cite `file:line`, state the secret type, and recommend
rotation.
