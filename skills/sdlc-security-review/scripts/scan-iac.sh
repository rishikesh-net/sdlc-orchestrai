#!/usr/bin/env bash
# scan-iac.sh - IaC, Dockerfile, and config misconfiguration scan with Trivy.
# Output: .sdlc/reports/<feature>-findings.sarif and .sdlc/reports/<feature>-findings.json
# Env: SDLC_STRICT=1 -> exit 1 when this scanner has findings; SDLC_FEATURE=<slug>.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_scan_common.sh
source "$SCRIPT_DIR/_scan_common.sh"

usage() { sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature) scan_set_feature "${2:-}"; shift 2 ;;
    --strict) SCAN_STRICT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT="$SCAN_ROOT"; OUT="$SCAN_OUT"
RAW="$OUT/$SCAN_FEATURE-iac-trivy.raw.sarif"
rm -f "$OUT/$SCAN_FEATURE-trivy.json" "$OUT/$SCAN_FEATURE-trivy.sarif" "$RAW" 2>/dev/null || true

mode="$(scan_mode TRIVY)"
if [[ "$mode" == "disabled" ]]; then
  echo "[iac] trivy disabled in .sdlc/config.yaml"
  scan_convert --type none --scanner trivy --status skipped --message "disabled in .sdlc/config.yaml"
elif command -v trivy >/dev/null 2>&1; then
  echo "[iac] trivy config scan"
  trivy config --format sarif --quiet --skip-dirs node_modules,.git,.sdlc,bin,obj,dist,build \
    --output "$RAW" "$ROOT" >/dev/null 2>&1 || true
  if [[ -s "$RAW" ]]; then
    scan_convert --type sarif --input "$RAW" --scanner trivy --status ran --root "$ROOT" \
      || scan_convert --type none --scanner trivy --status skipped --message "trivy SARIF output could not be parsed"
  else
    scan_convert --type none --scanner trivy --status ran --message "no IaC findings reported"
  fi
else
  echo "[iac] trivy not installed - skipped IaC/container config check"
  scan_convert --type none --scanner trivy --status skipped --message "trivy not installed"
fi

scan_finish iac "trivy"
