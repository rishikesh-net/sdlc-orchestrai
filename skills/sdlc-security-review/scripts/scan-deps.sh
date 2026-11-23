#!/usr/bin/env bash
# scan-deps.sh - vulnerable dependency check for .NET (NuGet) and Node (npm) projects.
# Env: SDLC_STRICT=1 -> exit 1 when vulnerabilities exist. Writes reports to .sdlc/reports/.
set -uo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
OUT="$ROOT/.sdlc/reports"; mkdir -p "$OUT"
FOUND=0

if command -v dotnet >/dev/null 2>&1; then
  targets=$(git -C "$ROOT" ls-files '*.sln' '*.slnx' 2>/dev/null)
  [[ -n "$targets" ]] || targets=$(git -C "$ROOT" ls-files '*.csproj' 2>/dev/null)
  if [[ -z "$targets" ]]; then echo "[deps] no .NET solution/projects found"; fi
  : > "$OUT/deps-dotnet.txt"
  while IFS= read -r t; do
    [[ -n "$t" ]] || continue
    echo "[deps] dotnet list package --vulnerable: $t"
    dotnet list "$ROOT/$t" package --vulnerable --include-transitive >> "$OUT/deps-dotnet.txt" 2>&1
  done <<<"$targets"
  if grep -q "has the following vulnerable packages" "$OUT/deps-dotnet.txt" 2>/dev/null; then
    FOUND=1; echo "[deps] .NET vulnerable packages found:"; grep -E "^\s+>|has the following" "$OUT/deps-dotnet.txt" | head -40
  else
    echo "[deps] .NET: no vulnerable packages reported"
  fi
else
  echo "[deps] dotnet not installed - skipped .NET check"
fi

if command -v npm >/dev/null 2>&1; then
  pkgs=$(git -C "$ROOT" ls-files '*package.json' 2>/dev/null | grep -v node_modules || true)
  if [[ -z "$pkgs" ]]; then echo "[deps] no package.json found"; fi
  while IFS= read -r p; do
    [[ -n "$p" ]] || continue
    d="$ROOT/$(dirname "$p")"
    if [[ ! -f "$d/package-lock.json" && ! -f "$d/yarn.lock" && ! -f "$d/pnpm-lock.yaml" ]]; then
      echo "[deps] $p: no lockfile - skipped (commit a lockfile)"; FOUND=1; continue
    fi
    echo "[deps] npm audit (high+): $p"
    if ! (cd "$d" && npm audit --audit-level=high > "$OUT/deps-npm-$(echo "$p" | tr '/' '_').txt" 2>&1); then
      FOUND=1; echo "[deps] vulnerabilities in $p (see $OUT)"; head -25 "$OUT/deps-npm-$(echo "$p" | tr '/' '_').txt"
    else
      echo "[deps] $p: no high/critical advisories"
    fi
  done <<<"$pkgs"
else
  echo "[deps] npm not installed - skipped Node check"
fi
[[ "${SDLC_STRICT:-0}" == "1" && $FOUND -eq 1 ]] && exit 1
exit 0
