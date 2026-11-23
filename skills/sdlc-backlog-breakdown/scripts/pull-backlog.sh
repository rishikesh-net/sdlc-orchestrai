#!/usr/bin/env bash
# pull-backlog.sh - list existing GitHub issues so the agent can avoid duplicates.
# Usage: pull-backlog.sh [--state open|closed|all] [--label <label>] [--limit N]
# Output: JSON array [{number,title,state,labels,url}] on stdout.
set -euo pipefail
STATE="open"; LABEL=""; LIMIT=200
while [[ $# -gt 0 ]]; do
  case "$1" in
    --state) STATE="${2:-open}"; shift 2 ;;
    --label) LABEL="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-200}"; shift 2 ;;
    -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
command -v gh >/dev/null 2>&1 || { echo "ERROR: gh CLI required" >&2; exit 2; }
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG="$ROOT/.sdlc/config.yaml"
REPO="${SDLC_REPO:-$(sed -nE 's/^[[:space:]]*repo:[[:space:]]*"?([^"# ]*)"?.*$/\1/p' "$CONFIG" 2>/dev/null | head -1)}"
[[ -n "$REPO" ]] || { echo "ERROR: set github.repo in .sdlc/config.yaml (or SDLC_REPO)" >&2; exit 2; }
args=(issue list --repo "$REPO" --state "$STATE" --limit "$LIMIT" --json number,title,state,labels,url)
[[ -z "$LABEL" ]] || args+=(--label "$LABEL")
gh "${args[@]}" | jq '[.[] | {number,title,state,url,labels:[.labels[].name]}]'
