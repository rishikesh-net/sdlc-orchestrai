#!/usr/bin/env bash
# scan-secrets.sh - detect committed secrets. Never prints secret values (file:line only).
# Uses gitleaks, else trufflehog, else a conservative regex fallback.
# Env: SDLC_STRICT=1 -> exit 1 when findings exist.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
OUT="$ROOT/.sdlc/reports"; mkdir -p "$OUT"
FOUND=0
if command -v gitleaks >/dev/null 2>&1; then
  echo "[secrets] gitleaks (redacted)"
  gitleaks detect --source "$ROOT" --redact --no-banner \
    --report-format json --report-path "$OUT/secrets-gitleaks.json" >/dev/null 2>&1
  rc=$?
  if [[ $rc -ne 0 ]]; then
    FOUND=1
    echo "[secrets] findings: $(jq 'length' "$OUT/secrets-gitleaks.json" 2>/dev/null || echo '?') (see $OUT/secrets-gitleaks.json; values redacted)"
    jq -r '.[] | "  \(.RuleID)  \(.File):\(.StartLine)"' "$OUT/secrets-gitleaks.json" 2>/dev/null | head -50
  else
    echo "[secrets] gitleaks: no findings"
  fi
elif command -v trufflehog >/dev/null 2>&1; then
  echo "[secrets] trufflehog (filesystem, verified only)"
  trufflehog filesystem "$ROOT" --only-verified --json 2>/dev/null \
    | jq -r 'select(.DetectorName) | "  \(.DetectorName)  \(.SourceMetadata.Data.Filesystem.file):\(.SourceMetadata.Data.Filesystem.line)"' \
    > "$OUT/secrets-trufflehog.txt"
  if [[ -s "$OUT/secrets-trufflehog.txt" ]]; then FOUND=1; head -50 "$OUT/secrets-trufflehog.txt"; else echo "[secrets] trufflehog: no verified findings"; fi
else
  echo "[secrets] gitleaks/trufflehog not installed - using regex fallback (low coverage; install gitleaks for real scanning)"
  if git -C "$ROOT" rev-parse >/dev/null 2>&1; then
    hits=$(git -C "$ROOT" grep -nIiE \
      -e 'AKIA[0-9A-Z]{16}' \
      -e '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----' \
      -e 'postgres(ql)?://[^[:space:]:/@]+:[^[:space:]@]+@' \
      -e "(password|pwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*['\"][^'\"[:space:]]{8,}['\"]" \
      -e '(password|pwd)=[^;"[:space:]]{4,}' \
      -- . ':!*.lock' ':!package-lock.json' ':!*.md' 2>/dev/null | cut -d: -f1,2)
  else
    hits=""
  fi
  if [[ -n "$hits" ]]; then FOUND=1; echo "[secrets] possible secrets (file:line only):"; echo "$hits" | sed 's/^/  /' | head -50; else echo "[secrets] regex fallback: no matches"; fi
fi
[[ "${SDLC_STRICT:-0}" == "1" && $FOUND -eq 1 ]] && exit 1
exit 0
