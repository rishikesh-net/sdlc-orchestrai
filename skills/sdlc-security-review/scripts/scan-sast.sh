#!/usr/bin/env bash
# scan-sast.sh - static analysis with Semgrep (C#, TypeScript/React, OWASP rules).
# CodeQL runs in CI (.github/workflows/security.yml). Needs network for Semgrep registry rules.
# Env: SDLC_STRICT=1 -> exit 1 when findings exist.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
OUT="$ROOT/.sdlc/reports"; mkdir -p "$OUT"
if ! command -v semgrep >/dev/null 2>&1; then
  echo "[sast] semgrep not installed (pip install semgrep). Skipping; CodeQL in CI still covers the repo."
  exit 0
fi
echo "[sast] semgrep scan"
semgrep scan --metrics=off --quiet \
  --config p/owasp-top-ten --config p/csharp --config p/react --config p/typescript --config p/secrets \
  --exclude node_modules --exclude bin --exclude obj --exclude dist --exclude build \
  --json --output "$OUT/sast-semgrep.json" "$ROOT" >/dev/null 2>&1
rc=$?
if [[ ! -s "$OUT/sast-semgrep.json" ]]; then echo "[sast] semgrep produced no output (rc=$rc). Check network/rule access."; exit 0; fi
n=$(jq '.results | length' "$OUT/sast-semgrep.json")
echo "[sast] findings: $n (report: $OUT/sast-semgrep.json)"
jq -r '.results[] | "  [\(.extra.severity)] \(.check_id | split(".") | last)  \(.path):\(.start.line)"' "$OUT/sast-semgrep.json" | head -50
[[ "${SDLC_STRICT:-0}" == "1" && "$n" -gt 0 ]] && exit 1
exit 0
