# Handoff

_Generated from `.sdlc/state.json`. Do not edit by hand._

Last updated: 2026-11-25T14:53:10Z by opencode at commit 646fdd1 (code had uncommitted changes)

## framework-improvements - phase: implementation

**Next action:** Phase 3 wrap-up: PR #2 merged; optional Jira/Linear/Azure DevOps adapters, or CI hardening (pin semgrep, tighten JS/TS detection)

| Gate | Status |
|---|---|
| design | approved |
| implementation | approved |

**Artifacts**
- `.github/workflows/security.yml`
- `.sdlc/schema/findings.schema.json`
- `.sdlc/schema/parallel-manifest.schema.json`
- `scripts/sdlc.py`
- `scripts/tests/test_backlog_adapters.py`
- `scripts/tests/test_slices.py`
- `skills/sdlc-backlog-breakdown/references/tracker-adapters.md`
- `skills/sdlc-backlog-breakdown/scripts/adapters/common.sh`
- `skills/sdlc-backlog-breakdown/scripts/adapters/github.sh`
- `skills/sdlc-backlog-breakdown/scripts/adapters/local.sh`
- `skills/sdlc-feature-implementer/SKILL.md`
- `skills/sdlc-security-review/references/sarif.md`
- `skills/sdlc-security-review/scripts/sarif.py`
- `skills/sdlc-session-handoff/references/parallel-orchestration.md`
- `skills/sdlc-session-handoff/scripts/sdlc-state.sh`

**Branch:** `main`

**Recent notes**
- 2026-11-24T17:37:14Z (opencode): Phase 3 item 3A implemented: adapter contract, GitHub parity, local Markdown tracker, tracker precedence, CRLF-safe jq helpers, graph external_key handling, docs and tests
- 2026-11-24T17:52:51Z (opencode): Phase 3 item 6 implemented: sdlc slices plan/show/check, scoped work orders + manifest, design/threat/backlog fan-in checks, templates and orchestration reference
- 2026-11-25T13:46:25Z (opencode): CI fix: security.yml now auto-detects CodeQL languages (detect job + dynamic matrix), analyzes without uploading (upload:false + output), saves SARIF as artifacts, makes Code Scanning uploads non-fatal on private/no-GHAS repos, and installs semgrep for real SAST; docs synced
- 2026-11-25T14:02:02Z (opencode): CI fix PR #2 green: security.yml auto-detects CodeQL languages, uploads non-fatal + SARIF artifacts, semgrep SAST; also fixed gitleaks pull-requests:read permission on PR events and aligned sdlc-state.sh PHASES with the Python runner (implementation). All checks pass.
- 2026-11-25T14:53:10Z (opencode): PR #2 merged via merge commit 646fdd1 (security workflow green on private repo without GHAS). Branch fix/ci-security-workflow deleted locally and remotely; main synced to origin/main.
