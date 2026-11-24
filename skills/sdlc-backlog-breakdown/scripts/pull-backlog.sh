#!/usr/bin/env bash
# pull-backlog.sh - list existing tracker tickets so the agent can avoid duplicates.
# Usage: pull-backlog.sh [--state open|closed|all] [--label <label>] [--limit N] [--tracker <name>]
# Output: JSON array [{number,title,state,labels,url}] on stdout. For the local adapter,
#         `number` is the backlog item id and `url` is the relative ticket path.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=adapters/common.sh
source "$SCRIPT_DIR/adapters/common.sh"

STATE="open"; LABEL=""; LIMIT=200; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --state) STATE="${2:-open}"; shift 2 ;;
    --label) LABEL="${2:-}"; shift 2 ;;
    --limit) LIMIT="${2:-200}"; shift 2 ;;
    --tracker) BL_TRACKER_ARG="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,4p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

bl_require_jq
TRACKER="$(bl_tracker)"
bl_load_adapter "$TRACKER"
adapter_init
adapter_pull "$STATE" "$LABEL" "$LIMIT"
