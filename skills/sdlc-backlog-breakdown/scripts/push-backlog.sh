#!/usr/bin/env bash
# push-backlog.sh - create/update tracker tickets from a neutral backlog JSON (idempotent).
#
# Usage:
#   push-backlog.sh --file docs/backlog/<feature>-backlog.json [--dry-run] [--only <epic-id>]
#                   [--tracker github|local]
#
# Tracker precedence: --tracker > SDLC_TRACKER > .sdlc/config.yaml tracker: > github.
# Requirements: bash, jq, git; gh (authenticated) unless --dry-run or tracker: local.
# Idempotency: each ticket title is prefixed "[<id>] ". Existing tickets are found via
#   external.key in the JSON, or by id/title lookup in the adapter, then updated.
# Results are written back to the JSON under items[].external (not in --dry-run).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=adapters/common.sh
source "$SCRIPT_DIR/adapters/common.sh"

FILE=""; DRY=0; ONLY=""
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) FILE="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --tracker) BL_TRACKER_ARG="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$FILE" && -f "$FILE" ]] || { echo "ERROR: --file <backlog.json> is required and must exist" >&2; exit 2; }
bl_require_jq

TRACKER="$(bl_tracker)"
bl_load_adapter "$TRACKER"
adapter_init

# ---- validate ---------------------------------------------------------------------------
jq -e '.schema_version==1 and (.items|type=="array")' "$FILE" >/dev/null \
  || { echo "ERROR: $FILE is not a valid backlog (schema_version 1 with items[])" >&2; exit 2; }
DUPS=$(bl_jqr '[.items[].id] | group_by(.) | map(select(length>1) | .[0]) | join(", ")' "$FILE")
[[ -z "$DUPS" ]] || { echo "ERROR: duplicate ids: $DUPS" >&2; exit 2; }
BAD=$(bl_jqr '[.items[] | select(.parent != null and .parent != "") | select(.parent as $p | [$FILE_IDS[] | select(. == $p)] | length == 0) | .id] | join(", ")' \
  --argjson FILE_IDS "$(jq '[.items[].id]' "$FILE")" "$FILE" 2>/dev/null || true)
[[ -z "$BAD" ]] || { echo "ERROR: unknown parent for: $BAD" >&2; exit 2; }

# ---- helpers ----------------------------------------------------------------------------
item_json() { bl_jqc --arg id "$1" '.items[] | select(.id==$id)' "$FILE"; }

fmt_issue() { [[ -n "$1" ]] || return 0; if [[ "$1" =~ ^[0-9]+$ ]]; then printf '#%s' "$1"; else printf '%s' "$1"; fi; }

issue_ref() { # id -> "#N" for numeric tracker keys, else the raw key
  local n; n=$(bl_jqr --arg id "$1" '.items[] | select(.id==$id) | .external.key // empty' "$FILE")
  [[ -n "$n" ]] || return 0
  fmt_issue "$n"
}

labels_for() {
  bl_jqr '
    [ (if .type=="epic" then "epic" else "type:\(.type)" end),
      (if (.priority // null) != null then "priority:\(.priority)" else empty end),
      (if (.estimate // null) != null then "estimate:\(.estimate)" else empty end) ]
    + (.labels // []) | unique | join(",")' <<<"$1"
}

body_for() {
  local item="$1" id us ref parent d n deps=""
  id=$(bl_jqr .id <<<"$item")
  bl_jqr '.body_markdown // ""' <<<"$item"
  us=$(bl_jqr '.user_story // empty' <<<"$item")
  if [[ -n "$us" ]]; then printf '\n**User story:** %s\n' "$us"; fi
  if jq -e '(.acceptance_criteria // []) | length > 0' <<<"$item" >/dev/null; then
    printf '\n### Acceptance criteria\n'
    bl_jqr '.acceptance_criteria[] | "- [ ] " + .' <<<"$item"
  fi
  ref=$(bl_jqr '(.req_refs // []) | join(", ")' <<<"$item")
  if [[ -n "$ref" ]]; then printf '\n**Requirements:** %s\n' "$ref"; fi
  ref=$(bl_jqr '.design_ref // empty' <<<"$item")
  if [[ -n "$ref" ]]; then printf '**Design:** `%s`\n' "$ref"; fi
  parent=$(bl_jqr '.parent // empty' <<<"$item")
  if [[ -n "$parent" ]]; then
    n=$(issue_ref "$parent"); printf '\n**Part of:** %s\n' "${n:-$parent}"
  fi
  for d in $(bl_jqr '(.depends_on // [])[]' <<<"$item"); do
    n=$(issue_ref "$d"); deps+="${deps:+, }${n:-$d}"
  done
  if [[ -n "$deps" ]]; then printf '**Blocked by:** %s\n' "$deps"; fi
  printf '\n<!-- sdlc-id: %s | managed by push-backlog.sh; edit backlog JSON, not this marker -->\n' "$id"
}

save_external() { # id key url
  local tmp; tmp="$(mktemp)"
  jq --arg id "$1" --arg k "$2" --arg url "$3" --arg tracker "$ADAPTER_NAME" \
    '(.items[] | select(.id==$id) | .external) = {tracker:$tracker, key:$k, url:$url}' "$FILE" > "$tmp" \
    && mv "$tmp" "$FILE"
}

# ---- order: epics, then stories, then tasks/spikes; optional --only <epic> ---------------------
IDS=$(bl_jqr --arg only "$ONLY" '
  . as $root
  | [ $root.items[]
      | select($only == "" or .id == $only or .parent == $only
               or (.parent as $p | [$root.items[] | select(.id == $p and .parent == $only)] | length > 0)) ]
  | sort_by(if .type=="epic" then 0 elif .type=="story" then 1 else 2 end)
  | .[].id' "$FILE")
[[ -n "$IDS" ]] || { echo "Nothing to do (no items matched)." ; exit 0; }

printf '%s   File: %s   Mode: %s\n' "$(adapter_describe)" "$FILE" \
  "$([[ $DRY -eq 1 ]] && echo DRY-RUN || echo APPLY)"
PDESC="$(adapter_project_desc 2>/dev/null || true)"
[[ -z "$PDESC" ]] || echo "$PDESC"
printf '\n%-10s %-6s %-9s %-8s %s\n' ID TYPE ACTION ISSUE TITLE

CREATED=0; UPDATED=0; FAILED=0
declare -A ACTION NUM URLS

# ---- pass 1: plan or create -------------------------------------------------------------------
for id in $IDS; do
  item=$(item_json "$id"); title=$(bl_jqr .title <<<"$item"); type=$(bl_jqr .type <<<"$item")
  num=$(bl_jqr '.external.key // empty' <<<"$item"); url=$(bl_jqr '.external.url // empty' <<<"$item")
  if [[ -z "$num" ]]; then
    found=$(adapter_find "$id" || true)
    if [[ -n "$found" ]]; then num="${found%%$'\t'*}"; url="${found#*$'\t'}"; fi
  fi
  if [[ -n "$num" ]]; then ACTION[$id]="update"; NUM[$id]="$num"; URLS[$id]="$url"
  else ACTION[$id]="create"; fi
  printf '%-10s %-6s %-9s %-8s %s\n' "$id" "$type" "${ACTION[$id]}" "$(fmt_issue "$num")" "$title"
done

if [[ $DRY -eq 1 ]]; then
  echo; echo "Dry run complete. No changes were made."
  if declare -F adapter_dry_run_note >/dev/null; then
    NOTE="$(adapter_dry_run_note || true)"; [[ -z "$NOTE" ]] || echo "$NOTE"
  fi
  exit 0
fi

# ensure labels exist (adapter-specific; local is a no-op)
echo; echo "Ensuring labels..."
adapter_sync_labels "$FILE"

echo "Applying..."
for id in $IDS; do
  item=$(item_json "$id"); title="[$id] $(bl_jqr .title <<<"$item")"
  labels=$(labels_for "$item"); tmp="$(mktemp)"; body_for "$item" > "$tmp"
  if [[ "${ACTION[$id]}" == "create" ]]; then
    if out=$(adapter_create "$id" "$title" "$tmp" "$labels" 2>&1); then
      key="${out%%$'\t'*}"; url="${out#*$'\t'}"
      if [[ -z "$key" || "$url" == "$out" ]]; then
        FAILED=$((FAILED+1)); echo "  FAILED create [$id]: malformed adapter response: $out" >&2; rm -f "$tmp"; continue
      fi
      NUM[$id]="$key"; URLS[$id]="$url"; save_external "$id" "$key" "$url"
      CREATED=$((CREATED+1)); echo "  created $(fmt_issue "$key")  [$id]"
    else
      FAILED=$((FAILED+1)); echo "  FAILED create [$id]: $out" >&2; rm -f "$tmp"; continue
    fi
  else
    n="${NUM[$id]}"
    if out=$(adapter_update "$n" "$title" "$tmp" "$labels" 2>&1); then
      save_external "$id" "$n" "${URLS[$id]:-}"; UPDATED=$((UPDATED+1)); echo "  updated $(fmt_issue "$n")  [$id]"
    else
      FAILED=$((FAILED+1)); echo "  FAILED update $(fmt_issue "$n") [$id]: $out" >&2
    fi
  fi
  rm -f "$tmp"
done

# ---- pass 2: relink (parents/blockers now have keys), sub-issues/tickets, project ----------------
echo "Linking..."
for id in $IDS; do
  item=$(item_json "$id"); n=$(bl_jqr '.external.key // empty' <<<"$item"); [[ -n "$n" ]] || continue
  parent=$(bl_jqr '.parent // empty' <<<"$item")
  has_deps=$(bl_jqr '((.depends_on // []) | length) > 0' <<<"$item")
  if [[ -n "$parent" || "$has_deps" == "true" ]]; then
    tmp="$(mktemp)"; body_for "$item" > "$tmp"
    adapter_refresh "$n" "$tmp" >/dev/null 2>&1 \
      || echo "  warn: could not refresh body of $(fmt_issue "$n")" >&2
    rm -f "$tmp"
  fi
  if [[ -n "$parent" ]]; then
    pn=$(bl_jqr --arg p "$parent" '.items[] | select(.id==$p) | .external.key // empty' "$FILE")
    [[ -z "$pn" ]] || adapter_link "$n" "$pn"
  fi
  u=$(bl_jqr '.external.url // empty' <<<"$item")
  adapter_project_add "$n" "$u"
done

echo; echo "Summary: created=$CREATED updated=$UPDATED failed=$FAILED"
echo "Tracker references were written back to $FILE - commit it."
[[ $FAILED -eq 0 ]]
