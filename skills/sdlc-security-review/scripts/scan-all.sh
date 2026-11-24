#!/usr/bin/env bash
# scan-all.sh - run every security scanner, then merge one SARIF report per feature.
# Output: .sdlc/reports/<feature>-findings.sarif and .sdlc/reports/<feature>-findings.json
# Env: SDLC_STRICT=1 -> exit 1 when any scanner reports findings; SDLC_FEATURE=<slug>.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_scan_common.sh
source "$SCRIPT_DIR/_scan_common.sh"

usage() { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature) scan_set_feature "${2:-}"; shift 2 ;;
    --strict) SCAN_STRICT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

rm -f "$SCAN_OUT/$SCAN_FEATURE"-*.sarif "$SCAN_OUT/$SCAN_FEATURE"-*.json \
      "$SCAN_OUT/$SCAN_FEATURE"-*.tsv "$SCAN_OUT/$SCAN_FEATURE"-*.raw.json \
      "$SCAN_OUT/$SCAN_FEATURE"-*.raw.jsonl "$SCAN_OUT/$SCAN_FEATURE"-deps-dotnet-*.txt 2>/dev/null || true

run_scan() {
  if [[ "$SCAN_STRICT" == "1" ]]; then
    bash "$SCRIPT_DIR/$1" --feature "$SCAN_FEATURE" --strict
  else
    bash "$SCRIPT_DIR/$1" --feature "$SCAN_FEATURE"
  fi
}

run_scan scan-secrets.sh
run_scan scan-sast.sh
run_scan scan-deps.sh

scan_finish all all
