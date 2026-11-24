#!/usr/bin/env bash
# scan-secrets.sh - detect committed secrets. Never prints or stores secret values (file:line only).
# Tools: gitleaks, else trufflehog, else a conservative labeled regex fallback.
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
rm -f "$OUT/$SCAN_FEATURE-gitleaks.json" "$OUT/$SCAN_FEATURE-gitleaks.sarif" \
      "$OUT/$SCAN_FEATURE-trufflehog.json" "$OUT/$SCAN_FEATURE-trufflehog.sarif" \
      "$OUT/$SCAN_FEATURE-heuristic-secrets.json" "$OUT/$SCAN_FEATURE-heuristic-secrets.sarif" 2>/dev/null || true

heuristic_secrets() {
  local tsv="$OUT/$SCAN_FEATURE-heuristic-secrets.tsv"
  : > "$tsv"
  emit() { # rule severity message ERE
    local rule="$1" sev="$2" msg="$3" ere="$4" f l
    git -C "$ROOT" grep -nIiE -e "$ere" -- . \
      ':!*.md' ':!*.lock' ':!package-lock.json' ':!node_modules' ':!bin' ':!obj' \
      ':!dist' ':!build' ':!*.min.js' ':!.sdlc' ':!skills/sdlc-security-review' 2>/dev/null \
      | cut -d: -f1,2 | while IFS=: read -r f l; do
          [[ -n "$f" && -n "$l" ]] && printf '%s\t%s\t%s\t%s\t%s\n' "$rule" "$f" "$l" "$sev" "$msg" >> "$tsv"
        done
  }
  emit heuristic-secrets.aws-access-key high "AWS access key id pattern (value redacted)" 'AKIA[0-9A-Z]{16}'
  emit heuristic-secrets.private-key critical "Private key block (value redacted)" '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'
  emit heuristic-secrets.database-uri high "Database URI with embedded credentials (value redacted)" 'postgres(ql)?://[^[:space:]:/@]+:[^[:space:]@]+@'
  emit heuristic-secrets.credential-assignment high "Credential-like assignment (value redacted)" "(password|pwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*['\"][^'\"[:space:]]{8,}['\"]"
  emit heuristic-secrets.password-argument medium "Password passed on a command line/config" '(password|pwd)=[^;"[:space:]]{4,}'
  emit heuristic-secrets.jwt high "JSON Web Token pattern (value redacted)" 'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'
  emit heuristic-secrets.github-token high "GitHub token pattern (value redacted)" 'gh[pousr]_[A-Za-z0-9]{30,}'
  emit heuristic-secrets.stripe-key critical "Stripe live key pattern (value redacted)" 'sk_live_[0-9A-Za-z]{20,}'
  emit heuristic-secrets.slack-token high "Slack token pattern (value redacted)" 'xox[baprs]-[0-9A-Za-z-]{10,}'
  scan_convert --type lines --input "$tsv" --scanner heuristic-secrets --status fallback --root "$ROOT"
}

if command -v gitleaks >/dev/null 2>&1; then
  echo "[secrets] gitleaks (redacted)"
  RAW="$OUT/$SCAN_FEATURE-secrets-gitleaks.raw.json"
  gitleaks detect --source "$ROOT" --redact --no-banner \
    --report-format json --report-path "$RAW" >/dev/null 2>&1
  if [[ -s "$RAW" ]]; then
    scan_convert --type gitleaks --input "$RAW" --scanner gitleaks --status ran --root "$ROOT"
    echo "[secrets] gitleaks findings: $(scan_scanner_count gitleaks)"
  else
    echo "[secrets] gitleaks produced no report; using regex fallback"
    heuristic_secrets
  fi
elif command -v trufflehog >/dev/null 2>&1; then
  echo "[secrets] trufflehog (verified only, redacted)"
  RAW="$OUT/$SCAN_FEATURE-secrets-trufflehog.raw.jsonl"
  trufflehog filesystem "$ROOT" --only-verified --json > "$RAW" 2>/dev/null
  scan_convert --type trufflehog --input "$RAW" --scanner trufflehog --status ran --root "$ROOT"
  echo "[secrets] trufflehog findings: $(scan_scanner_count trufflehog)"
else
  echo "[secrets] gitleaks/trufflehog not installed - using regex fallback (low coverage; install gitleaks for real scanning)"
  heuristic_secrets
fi

scan_finish secrets "gitleaks trufflehog heuristic-secrets"
