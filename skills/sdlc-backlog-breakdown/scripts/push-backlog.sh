#!/usr/bin/env bash
# push-backlog.sh - create/update GitHub issues from a neutral backlog JSON (idempotent).
#
# Usage:
#   push-backlog.sh --file docs/backlog/<feature>-backlog.json [--dry-run] [--only <epic-id>]
#
# Requirements: bash, jq, git; gh (authenticated) unless --dry-run.
# Config: .sdlc/config.yaml  (github.repo, github.project_number, github.project_owner)
#         env SDLC_REPO overrides the repo.
# Idempotency: each issue title is prefixed "[<id>] ". Existing issues are found via
#         external.key in the JSON, or by title prefix search, then updated instead of duplicated.
# Results are written back to the JSON under items[].external (not in --dry-run).
set -euo pipefail

FILE=""; DRY=0; ONLY=""
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) FILE="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$FILE" && -f "$FILE" ]] || { echo "ERROR: --file <backlog.json> is required and must exist" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required" >&2; exit 2; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG="$ROOT/.sdlc/config.yaml"

cfg() { # first "key: value" line in config.yaml, quotes/comments stripped
  [[ -f "$CONFIG" ]] || return 0
  sed -nE "s/^[[:space:]]*$1:[[:space:]]*\"?([^\"#]*)\"?[[:space:]]*(#.*)?$/\1/p" "$CONFIG" \
    | head -1 | sed -E 's/[[:space:]]+$//'
}

REPO="${SDLC_REPO:-$(cfg repo)}"
PROJECT="$(cfg project_number)"
POWNER="$(cfg project_owner)"
[[ -n "$REPO" && "$REPO" != "your-org/your-repo" ]] || { echo "ERROR: set github.repo in .sdlc/config.yaml (or SDLC_REPO)" >&2; exit 2; }
[[ -n "$POWNER" ]] || POWNER="${REPO%%/*}"

HAVE_GH=0
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then HAVE_GH=1; fi
if [[ $DRY -eq 0 && $HAVE_GH -eq 0 ]]; then
  echo "ERROR: gh CLI not installed or not authenticated (run: gh auth login)" >&2; exit 2
fi

# ---- validate ---------------------------------------------------------------------------
jq -e '.schema_version==1 and (.items|type=="array")' "$FILE" >/dev/null \
  || { echo "ERROR: $FILE is not a valid backlog (schema_version 1 with items[])" >&2; exit 2; }
DUPS=$(jq -r '[.items[].id] | group_by(.) | map(select(length>1) | .[0]) | join(", ")' "$FILE")
[[ -z "$DUPS" ]] || { echo "ERROR: duplicate ids: $DUPS" >&2; exit 2; }
BAD=$(jq -r '[.items[] | select(.parent != null and .parent != "") | select(.parent as $p | [$FILE_IDS[] | select(. == $p)] | length == 0) | .id] | join(", ")' \
  --argjson FILE_IDS "$(jq '[.items[].id]' "$FILE")" "$FILE" 2>/dev/null || true)
[[ -z "$BAD" ]] || { echo "ERROR: unknown parent for: $BAD" >&2; exit 2; }

# ---- helpers ----------------------------------------------------------------------------
item_json() { jq -c --arg id "$1" '.items[] | select(.id==$id)' "$FILE"; }

issue_ref() { # id -> "#N" if known, else empty
  local n; n=$(jq -r --arg id "$1" '.items[] | select(.id==$id) | .external.key // empty' "$FILE")
  [[ -n "$n" ]] && printf '#%s' "$n"
  return 0
}

labels_for() {
  jq -r '
    [ (if .type=="epic" then "epic" else "type:\(.type)" end),
      (if (.priority // null) != null then "priority:\(.priority)" else empty end),
      (if (.estimate // null) != null then "estimate:\(.estimate)" else empty end) ]
    + (.labels // []) | unique | join(",")' <<<"$1"
}

body_for() {
  local item="$1" id us ref parent d n pending=""
  id=$(jq -r .id <<<"$item")
  jq -r '.body_markdown // ""' <<<"$item"
  us=$(jq -r '.user_story // empty' <<<"$item")
  if [[ -n "$us" ]]; then printf '\n**User story:** %s\n' "$us"; fi
  if jq -e '(.acceptance_criteria // []) | length > 0' <<<"$item" >/dev/null; then
    printf '\n### Acceptance criteria\n'
    jq -r '.acceptance_criteria[] | "- [ ] " + .' <<<"$item"
  fi
  ref=$(jq -r '(.req_refs // []) | join(", ")' <<<"$item")
  if [[ -n "$ref" ]]; then printf '\n**Requirements:** %s\n' "$ref"; fi
  ref=$(jq -r '.design_ref // empty' <<<"$item")
  if [[ -n "$ref" ]]; then printf '**Design:** `%s`\n' "$ref"; fi
  parent=$(jq -r '.parent // empty' <<<"$item")
  if [[ -n "$parent" ]]; then
    n=$(issue_ref "$parent"); printf '\n**Part of:** %s\n' "${n:-$parent}"
  fi
  local deps=""
  for d in $(jq -r '(.depends_on // [])[]' <<<"$item"); do
    n=$(issue_ref "$d"); deps+="${deps:+, }${n:-$d}"
  done
  if [[ -n "$deps" ]]; then printf '**Blocked by:** %s\n' "$deps"; fi
  printf '\n<!-- sdlc-id: %s | managed by push-backlog.sh; edit backlog JSON, not this marker -->\n' "$id"
}

save_external() { # id number url
  local tmp; tmp="$(mktemp)"
  jq --arg id "$1" --arg n "$2" --arg url "$3" \
    '(.items[] | select(.id==$id) | .external) = {tracker:"github", key:$n, url:$url}' "$FILE" > "$tmp" \
    && mv "$tmp" "$FILE"
}

find_existing() { # id -> "number<TAB>url" or empty
  [[ $HAVE_GH -eq 1 ]] || return 0
  gh issue list --repo "$REPO" --state all --search "$1 in:title" --json number,title,url --limit 30 2>/dev/null \
    | jq -r --arg p "[$1] " '.[] | select(.title | startswith($p)) | "\(.number)\t\(.url)"' | head -1
}

# ---- order: epics, then stories, then tasks/spikes; optional --only <epic> ---------------------
IDS=$(jq -r --arg only "$ONLY" '
  . as $root
  | [ $root.items[]
      | select($only == "" or .id == $only or .parent == $only
               or (.parent as $p | [$root.items[] | select(.id == $p and .parent == $only)] | length > 0)) ]
  | sort_by(if .type=="epic" then 0 elif .type=="story" then 1 else 2 end)
  | .[].id' "$FILE")
[[ -n "$IDS" ]] || { echo "Nothing to do (no items matched)." ; exit 0; }

echo "Repo: $REPO   File: $FILE   Mode: $([[ $DRY -eq 1 ]] && echo DRY-RUN || echo APPLY)"
[[ -z "$PROJECT" ]] || echo "Project: $POWNER #$PROJECT"
printf '\n%-10s %-6s %-9s %-8s %s\n' ID TYPE ACTION ISSUE TITLE

CREATED=0; UPDATED=0; FAILED=0; PLAN=()
declare -A ACTION NUM URLS

# ---- pass 1: plan or create -------------------------------------------------------------------
for id in $IDS; do
  item=$(item_json "$id"); title=$(jq -r .title <<<"$item"); type=$(jq -r .type <<<"$item")
  num=$(jq -r '.external.key // empty' <<<"$item"); url=$(jq -r '.external.url // empty' <<<"$item")
  if [[ -z "$num" ]]; then
    found=$(find_existing "$id" || true)
    if [[ -n "$found" ]]; then num="${found%%$'\t'*}"; url="${found#*$'\t'}"; fi
  fi
  if [[ -n "$num" ]]; then ACTION[$id]="update"; NUM[$id]="$num"; URLS[$id]="$url"
  else ACTION[$id]="create"; fi
  printf '%-10s %-6s %-9s %-8s %s\n' "$id" "$type" "${ACTION[$id]}" "${num:+#$num}" "$title"
done

if [[ $DRY -eq 1 ]]; then
  echo; echo "Dry run complete. No changes were made."
  [[ $HAVE_GH -eq 1 ]] || echo "Note: gh unavailable, so existing issues were not looked up; 'create' may become 'update'."
  exit 0
fi

# ensure labels exist
echo; echo "Ensuring labels..."
jq -r '.items[] | (if .type=="epic" then "epic" else "type:\(.type)" end),
        (if (.priority // null) != null then "priority:\(.priority)" else empty end),
        (if (.estimate // null) != null then "estimate:\(.estimate)" else empty end),
        ((.labels // [])[])' "$FILE" | sort -u | while IFS= read -r l; do
  [[ -n "$l" ]] && gh label create "$l" --repo "$REPO" --force >/dev/null 2>&1 || true
done

echo "Applying..."
for id in $IDS; do
  item=$(item_json "$id"); title="[$id] $(jq -r .title <<<"$item")"
  labels=$(labels_for "$item"); tmp="$(mktemp)"; body_for "$item" > "$tmp"
  if [[ "${ACTION[$id]}" == "create" ]]; then
    if out=$(gh issue create --repo "$REPO" --title "$title" --body-file "$tmp" --label "$labels" 2>&1); then
      url=$(grep -Eo 'https://[^ ]+/issues/[0-9]+' <<<"$out" | tail -1)
      n="${url##*/}"; NUM[$id]="$n"; URLS[$id]="$url"; save_external "$id" "$n" "$url"
      CREATED=$((CREATED+1)); echo "  created #$n  [$id]"
    else
      FAILED=$((FAILED+1)); echo "  FAILED create [$id]: $out" >&2; rm -f "$tmp"; continue
    fi
  else
    n="${NUM[$id]}"
    if gh issue edit "$n" --repo "$REPO" --title "$title" --body-file "$tmp" --add-label "$labels" >/dev/null 2>&1; then
      save_external "$id" "$n" "${URLS[$id]:-}"; UPDATED=$((UPDATED+1)); echo "  updated #$n  [$id]"
    else
      FAILED=$((FAILED+1)); echo "  FAILED update #$n [$id]" >&2
    fi
  fi
  rm -f "$tmp"
done

# ---- pass 2: relink (parents/blockers now have numbers), sub-issues, project ---------------------
echo "Linking..."
for id in $IDS; do
  item=$(item_json "$id"); n=$(jq -r '.external.key // empty' <<<"$item"); [[ -n "$n" ]] || continue
  parent=$(jq -r '.parent // empty' <<<"$item")
  has_deps=$(jq -r '((.depends_on // []) | length) > 0' <<<"$item")
  if [[ -n "$parent" || "$has_deps" == "true" ]]; then
    tmp="$(mktemp)"; body_for "$item" > "$tmp"
    gh issue edit "$n" --repo "$REPO" --body-file "$tmp" >/dev/null 2>&1 || echo "  warn: could not refresh body of #$n" >&2
    rm -f "$tmp"
  fi
  if [[ -n "$parent" ]]; then
    pn=$(jq -r --arg p "$parent" '.items[] | select(.id==$p) | .external.key // empty' "$FILE")
    if [[ -n "$pn" ]]; then
      cid=$(gh api "repos/$REPO/issues/$n" --jq .id 2>/dev/null || true)
      if [[ -n "$cid" ]]; then
        gh api -X POST "repos/$REPO/issues/$pn/sub_issues" -F sub_issue_id="$cid" >/dev/null 2>&1 \
          || echo "  note: sub-issue link #$n -> #$pn skipped (already linked or feature unavailable); 'Part of' text is in the body"
      fi
    fi
  fi
  if [[ -n "$PROJECT" ]]; then
    u=$(jq -r '.external.url // empty' <<<"$item")
    [[ -z "$u" ]] || gh project item-add "$PROJECT" --owner "$POWNER" --url "$u" >/dev/null 2>&1 \
      || echo "  warn: could not add #$n to project $PROJECT (needs 'project' scope: gh auth refresh -s project)" >&2
  fi
done

echo; echo "Summary: created=$CREATED updated=$UPDATED failed=$FAILED"
echo "Issue numbers/URLs were written back to $FILE - commit it."
[[ $FAILED -eq 0 ]]
