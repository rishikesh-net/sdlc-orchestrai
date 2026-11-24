#!/usr/bin/env bash
# scan-deps.sh - vulnerable dependency check for .NET (NuGet) and Node (npm) projects.
# Output: .sdlc/reports/<feature>-findings.sarif and .sdlc/reports/<feature>-findings.json
# Env: SDLC_STRICT=1 -> exit 1 when this scanner has findings; SDLC_FEATURE=<slug>.
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

ROOT="$SCAN_ROOT"; OUT="$SCAN_OUT"
rm -f "$OUT/$SCAN_FEATURE-dotnet.json" "$OUT/$SCAN_FEATURE-dotnet.sarif" \
      "$OUT/$SCAN_FEATURE-npm-audit.json" "$OUT/$SCAN_FEATURE-npm-audit.sarif" 2>/dev/null || true

dotnet_json_found=0
if command -v dotnet >/dev/null 2>&1; then
  targets=$(git -C "$ROOT" ls-files '*.sln' '*.slnx' 2>/dev/null)
  [[ -n "$targets" ]] || targets=$(git -C "$ROOT" ls-files '*.csproj' 2>/dev/null)
  if [[ -z "$targets" ]]; then
    echo "[deps] no .NET solution/projects found"
    scan_convert --type none --scanner dotnet --status skipped --message "No .NET solution or project files found"
  else
    idx=0
    while IFS= read -r t; do
      [[ -n "$t" ]] || continue
      idx=$((idx + 1))
      raw="$OUT/$SCAN_FEATURE-deps-dotnet-$idx.raw.json"
      txt="$OUT/$SCAN_FEATURE-deps-dotnet-$idx.txt"
      echo "[deps] dotnet list package --vulnerable: $t"
      dotnet list "$ROOT/$t" package --vulnerable --include-transitive --format json > "$raw" 2>/dev/null || true
      if [[ -s "$raw" && "$(head -c 1 "$raw")" == "{" ]]; then
        scan_convert --type dotnet --input "$raw" --scanner dotnet --status ran --root "$ROOT" --append
        dotnet_json_found=1
      else
        dotnet list "$ROOT/$t" package --vulnerable --include-transitive > "$txt" 2>&1 || true
        rm -f "$raw"
        echo "[deps] $t: SDK does not support --format json; wrote text report to .sdlc/reports/$(basename "$txt")"
      fi
    done <<<"$targets"
    if [[ "$dotnet_json_found" -eq 0 ]]; then
      scan_convert --type none --scanner dotnet --status fallback \
        --message "dotnet SDK lacks JSON output; findings are in .sdlc/reports/$SCAN_FEATURE-deps-dotnet-*.txt"
    fi
  fi
else
  echo "[deps] dotnet not installed - skipped .NET check"
  scan_convert --type none --scanner dotnet --status skipped --message "dotnet SDK not installed"
fi

if command -v npm >/dev/null 2>&1; then
  pkgs=$(git -C "$ROOT" ls-files '*package.json' 2>/dev/null | grep -v node_modules || true)
  if [[ -z "$pkgs" ]]; then
    echo "[deps] no package.json found"
    scan_convert --type none --scanner npm-audit --status skipped --message "No package.json found"
  else
    idx=0
    while IFS= read -r p; do
      [[ -n "$p" ]] || continue
      d="$ROOT/$(dirname "$p")"
      if [[ ! -f "$d/package-lock.json" && ! -f "$d/yarn.lock" && ! -f "$d/pnpm-lock.yaml" ]]; then
        echo "[deps] $p: no lockfile - skipped (commit a lockfile)"
        continue
      fi
      idx=$((idx + 1))
      raw="$OUT/$SCAN_FEATURE-deps-npm-$idx.raw.json"
      echo "[deps] npm audit (high+): $p"
      (cd "$d" && npm audit --audit-level=high --json > "$raw" 2>/dev/null) || true
      if [[ -s "$raw" ]]; then
        scan_convert --type npm-audit --input "$raw" --scanner npm-audit --status ran \
          --root "$ROOT" --package-path "$p" --append
      else
        echo "[deps] $p: npm audit produced no JSON report"
      fi
    done <<<"$pkgs"
  fi
else
  echo "[deps] npm not installed - skipped Node check"
  scan_convert --type none --scanner npm-audit --status skipped --message "npm not installed"
fi

scan_finish deps "dotnet npm-audit"
