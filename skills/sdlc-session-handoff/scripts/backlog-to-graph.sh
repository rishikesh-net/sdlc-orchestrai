#!/usr/bin/env bash
# backlog-to-graph.sh - convert a backlog JSON (schema in .sdlc/schema/backlog.schema.json) into graph facts.
# Usage: backlog-to-graph.sh --file docs/backlog/<feature>-backlog.json [--apply]
#   Without --apply: prints JSONL to stdout. With --apply: imports into .sdlc/memory/graph.jsonl.
# Produces: entities (epic/story/task/spike with issue number, priority, estimate when known) and relations
#   implements (item -> REQ via req_refs), depends_on, part_of (item -> parent).
set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required" >&2; exit 2; }
FILE=""; APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) FILE="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$FILE" && -f "$FILE" ]] || { echo "ERROR: --file <backlog.json> required" >&2; exit 2; }
jq -e '.schema_version==1 and (.items|type=="array")' "$FILE" >/dev/null || { echo "ERROR: not a valid backlog file" >&2; exit 2; }
OUT="$(jq -c '
  ( .items[] | {type:"entity", id:.id, kind:.type, title:.title}
      + (if (.external.key // null) != null then {issue: ((.external.key | tonumber?) // .external.key)} else {} end)
      + (if (.priority // null) != null then {priority:.priority} else {} end)
      + (if (.estimate // null) != null then {estimate:.estimate} else {} end) ),
  ( .items[] | . as $i | ((.req_refs // [])[] | {type:"relation", from:$i.id, rel:"implements", to:.}) ),
  ( .items[] | . as $i | ((.depends_on // [])[] | {type:"relation", from:$i.id, rel:"depends_on", to:.}) ),
  ( .items[] | select((.parent // "") != "") | {type:"relation", from:.id, rel:"part_of", to:.parent} )' "$FILE")"
if [[ $APPLY -eq 1 ]]; then
  tmp="$(mktemp)"; printf '%s\n' "$OUT" > "$tmp"
  bash "$(dirname "${BASH_SOURCE[0]}")/sdlc-graph.sh" import --file "$tmp"; rm -f "$tmp"
else
  printf '%s\n' "$OUT"
fi
