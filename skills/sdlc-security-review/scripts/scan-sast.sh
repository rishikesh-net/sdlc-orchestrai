#!/usr/bin/env bash
# scan-sast.sh - static analysis with Semgrep, or a conservative heuristic fallback.
# CodeQL runs in CI (.github/workflows/security.yml) and remains the primary SAST gate.
# Heuristics scan application source files only (*.cs, *.ts, *.tsx, *.js, *.py, ...).
# Output: .sdlc/reports/<feature>-findings.sarif and .sdlc/reports/<feature>-findings.json
# Env: SDLC_STRICT=1 -> exit 1 when this scanner has findings; SDLC_FEATURE=<slug>.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_scan_common.sh
source "$SCRIPT_DIR/_scan_common.sh"

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --feature) scan_set_feature "${2:-}"; shift 2 ;;
    --strict) SCAN_STRICT=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

ROOT="$SCAN_ROOT"; OUT="$SCAN_OUT"
RAW="$OUT/$SCAN_FEATURE-sast-semgrep.raw.json"
rm -f "$OUT/$SCAN_FEATURE-semgrep.json" "$OUT/$SCAN_FEATURE-semgrep.sarif" \
      "$OUT/$SCAN_FEATURE-heuristic-sast.json" "$OUT/$SCAN_FEATURE-heuristic-sast.sarif" 2>/dev/null || true

heuristic_sast() {
  local tsv="$OUT/$SCAN_FEATURE-heuristic-sast.tsv"
  local -a paths=(
    '*.cs' '*.cshtml' '*.ts' '*.tsx' '*.js' '*.jsx' '*.mjs' '*.cjs'
    '*.py' '*.go' '*.java' '*.kt' '*.rb' '*.php' '*.sql'
  )
  : > "$tsv"
  emit() { # rule severity message ERE [case]
    local rule="$1" sev="$2" msg="$3" ere="$4" f l
    local -a gflags=(-nIiE)
    [[ "${5:-}" == "case" ]] && gflags=(-nIE)
    git -C "$ROOT" grep "${gflags[@]}" -e "$ere" -- "${paths[@]}" \
      ':!node_modules' ':!bin' ':!obj' ':!dist' ':!build' ':!*.min.js' \
      ':!.sdlc' ':!skills/sdlc-security-review' 2>/dev/null \
      | cut -d: -f1,2 | while IFS=: read -r f l; do
          [[ -n "$f" && -n "$l" ]] && printf '%s\t%s\t%s\t%s\t%s\n' "$rule" "$f" "$l" "$sev" "$msg" >> "$tsv"
        done
  }
  emit heuristic-sast.dangerous-html medium "React dangerouslySetInnerHTML - ensure HTML is sanitized" 'dangerouslySetInnerHTML'
  emit heuristic-sast.dynamic-eval high "Dynamic code evaluation (eval/new Function) - review input source" 'eval[[:space:]]*\(|new[[:space:]]+Function[[:space:]]*\('
  emit heuristic-sast.cors-any medium "Permissive CORS policy (AllowAnyOrigin)" 'AllowAnyOrigin'
  emit heuristic-sast.tls-disabled high "TLS certificate validation disabled" 'TrustServerCertificate[[:space:]]*=[[:space:]]*true|VerifyServerCertificate[[:space:]]*=[[:space:]]*false'
  emit heuristic-sast.allow-anonymous low "Anonymous access attribute - verify this is intentional" '\[AllowAnonymous\]'
  emit heuristic-sast.weak-hash low "Weak hash algorithm (MD5/SHA1) - prefer SHA-256+" 'MD5|SHA1'
  emit heuristic-sast.sql-concat medium "Possible SQL string concatenation - use parameters" '\bSELECT\b[^;]*\+' case
  emit heuristic-sast.html-raw medium "Unencoded HTML output - ensure input is trusted/sanitized" 'Html\.Raw\(|innerHTML[[:space:]]*='
  scan_convert --type lines --input "$tsv" --scanner heuristic-sast --status fallback --root "$ROOT"
}

if [[ "$(scan_mode SEMGREP)" == "disabled" ]]; then
  echo "[sast] semgrep disabled in .sdlc/config.yaml"
  scan_convert --type none --scanner semgrep --status skipped --message "disabled in .sdlc/config.yaml"
elif command -v semgrep >/dev/null 2>&1; then
  echo "[sast] semgrep scan"
  semgrep scan --metrics=off --quiet \
    --config p/owasp-top-ten --config p/csharp --config p/react --config p/typescript --config p/secrets \
    --exclude node_modules --exclude bin --exclude obj --exclude dist --exclude build \
    --json --output "$RAW" "$ROOT" >/dev/null 2>&1
  rc=$?
  if [[ -s "$RAW" ]]; then
    scan_convert --type semgrep --input "$RAW" --scanner semgrep --status ran --root "$ROOT" \
      || { echo "[sast] semgrep output could not be parsed (rc=$rc); using heuristic fallback"; heuristic_sast; }
  else
    echo "[sast] semgrep produced no output (rc=$rc); check network/rule access or use the fallback"
    heuristic_sast
  fi
else
  echo "[sast] semgrep not installed - using conservative heuristics on application source files (low coverage; install semgrep for real SAST)"
  heuristic_sast
fi

if [[ -s "$RAW" && -s "$OUT/$SCAN_FEATURE-semgrep.json" ]]; then
  n=$(scan_scanner_count semgrep)
  echo "[sast] semgrep findings: $n"
  echo "[sast] heuristic findings: $(scan_scanner_count heuristic-sast)"
fi

ZIZMOR_RAW="$OUT/$SCAN_FEATURE-sast-zizmor.raw.sarif"
rm -f "$OUT/$SCAN_FEATURE-zizmor.json" "$OUT/$SCAN_FEATURE-zizmor.sarif" "$ZIZMOR_RAW" 2>/dev/null || true
if [[ -d "$ROOT/.github/workflows" ]]; then
  if [[ "$(scan_mode ZIZMOR)" == "disabled" ]]; then
    echo "[sast] zizmor disabled in .sdlc/config.yaml"
    scan_convert --type none --scanner zizmor --status skipped --message "disabled in .sdlc/config.yaml"
  elif command -v zizmor >/dev/null 2>&1; then
    echo "[sast] zizmor GitHub Actions scan"
    zizmor --format sarif "$ROOT/.github/workflows" > "$ZIZMOR_RAW" 2>/dev/null || true
    if [[ -s "$ZIZMOR_RAW" ]]; then
      scan_convert --type sarif --input "$ZIZMOR_RAW" --scanner zizmor --status ran --root "$ROOT" \
        || scan_convert --type none --scanner zizmor --status skipped --message "zizmor SARIF output could not be parsed"
    else
      scan_convert --type none --scanner zizmor --status ran --message "no workflow findings reported"
    fi
  else
    echo "[sast] zizmor not installed - skipped GitHub Actions workflow check"
    scan_convert --type none --scanner zizmor --status skipped --message "zizmor not installed"
  fi
fi

scan_finish sast "semgrep heuristic-sast zizmor"
