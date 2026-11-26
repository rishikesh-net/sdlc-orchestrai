#!/usr/bin/env bash
# _scan_common.sh - shared helpers for scan-*.sh. Sourced, not executed directly.
#
# Provides:
#   SCAN_ROOT, SCAN_OUT, SCAN_FEATURE, SCAN_STRICT, SCAN_PY, SCAN_SARIF
#   scan_set_feature SLUG      sanitize and set the feature/report slug
#   scan_convert ARGS...       convert one tool's raw output (see sarif.py convert)
#   scan_merge                 merge per-scanner outputs into <feature>-findings.*
#   scan_scanner_count NAME    findings for one scanner (0 if absent)
#   scan_finish LABEL [NAMES]  merge, print summary, strict exit decision
#
# Reports are written to .sdlc/reports/<feature>-findings.sarif and .json.
# Secret values are never written to reports.

SCAN_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCAN_ROOT="${SDLC_SCAN_ROOT:-$(git -C "$SCAN_SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || pwd)}"
SCAN_OUT="$SCAN_ROOT/.sdlc/reports"
mkdir -p "$SCAN_OUT"
SCAN_FEATURE="${SDLC_FEATURE:-repo}"
SCAN_STRICT="${SDLC_STRICT:-0}"
SCAN_SARIF="$SCAN_SCRIPT_DIR/sarif.py"

scan_slug() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '-'; }

scan_set_feature() {
  local slug
  slug="$(scan_slug "$1")"
  SCAN_FEATURE="${slug:-repo}"
}

scan_find_python() {
  if [[ -n "${SDLC_PYTHON:-}" ]]; then printf '%s' "$SDLC_PYTHON"; return 0; fi
  if command -v python3 >/dev/null 2>&1; then printf 'python3'; return 0; fi
  if command -v python >/dev/null 2>&1; then printf 'python'; return 0; fi
  printf ''
}

SCAN_PY="$(scan_find_python)"

scan_load_config() {
  [[ -n "$SCAN_PY" && -f "$SCAN_SARIF" ]] || return 0
  local line k v
  while IFS='=' read -r k v; do
    case "$k" in
      SDLC_CONFIG_STRICT)
        if [[ -z "${SDLC_STRICT:-}" && "$v" == "1" ]]; then SCAN_STRICT=1; fi
        ;;
      SDLC_SEC_*)
        if [[ "$v" == "auto" || "$v" == "enabled" || "$v" == "disabled" ]]; then
          printf -v "$k" '%s' "$v"
          export "$k"
        fi
        ;;
    esac
  done < <("$SCAN_PY" "$SCAN_SARIF" config --root "$SCAN_ROOT" --shell 2>/dev/null || true)
}

scan_mode() {
  local var="SDLC_SEC_$1"
  printf '%s' "${!var:-auto}"
}

scan_load_config

scan_require_python() {
  [[ -n "$SCAN_PY" ]] || {
    echo "ERROR: Python 3 is required for SARIF reports (install Python or set SDLC_PYTHON)" >&2
    exit 2
  }
}

scan_convert() {
  scan_require_python
  "$SCAN_PY" "$SCAN_SARIF" convert --feature "$SCAN_FEATURE" --out-dir "$SCAN_OUT" "$@"
}

scan_merge() {
  scan_require_python
  "$SCAN_PY" "$SCAN_SARIF" merge --feature "$SCAN_FEATURE" --out-dir "$SCAN_OUT" >/dev/null
}

scan_finding_count() {
  scan_require_python
  "$SCAN_PY" "$SCAN_SARIF" count --feature "$SCAN_FEATURE" --out-dir "$SCAN_OUT" 2>/dev/null || echo 0
}

scan_scanner_count() {
  scan_require_python
  local file="$SCAN_OUT/$SCAN_FEATURE-$(scan_slug "$1").json"
  "$SCAN_PY" -c 'import json,sys;print(len(json.load(open(sys.argv[1])).get("findings",[])))' "$file" 2>/dev/null || echo 0
}

scan_finish() { # label [scanner...|all]
  local label="$1" names="${2:-}" total self=0 name
  scan_merge || true
  total="$(scan_finding_count)"
  if [[ -n "$names" && "$names" != "all" ]]; then
    for name in $names; do self=$((self + $(scan_scanner_count "$name"))); done
  else
    self="$total"
  fi
  printf '[%s] findings: %s (merged: %s; report: .sdlc/reports/%s-findings.sarif)\n' \
    "$label" "$self" "$total" "$SCAN_FEATURE"
  if [[ "$SCAN_STRICT" == "1" && "$self" -gt 0 ]]; then return 1; fi
  return 0
}
