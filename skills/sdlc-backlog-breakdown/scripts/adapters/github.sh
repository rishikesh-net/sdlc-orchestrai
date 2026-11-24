#!/usr/bin/env bash
# github.sh - GitHub Issues tracker adapter (gh CLI). Sourced by push/pull scripts.
#
# Config (.sdlc/config.yaml):
#   tracker: github
#   github:
#     repo: owner/name            # env SDLC_REPO overrides
#     project_number: ""          # optional GitHub Projects (v2) number
#     project_owner: ""           # optional; defaults to the repo owner
#
# Requires: gh (authenticated with repo scope; add project scope for Projects), jq.

ADAPTER_NAME="github"
_GITHUB_REPO=""
_GITHUB_PROJECT=""
_GITHUB_POWNER=""
_GITHUB_HAVE_GH=0

_g_ref() { if [[ "$1" =~ ^[0-9]+$ ]]; then printf '#%s' "$1"; else printf '%s' "$1"; fi; }

adapter_init() {
  _GITHUB_REPO="${SDLC_REPO:-$(bl_cfg repo)}"
  _GITHUB_PROJECT="$(bl_cfg project_number)"
  _GITHUB_POWNER="$(bl_cfg project_owner)"
  [[ -n "$_GITHUB_REPO" && "$_GITHUB_REPO" != "your-org/your-repo" ]] \
    || bl_die "set github.repo in .sdlc/config.yaml (or SDLC_REPO)"
  [[ -n "$_GITHUB_POWNER" ]] || _GITHUB_POWNER="${_GITHUB_REPO%%/*}"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    _GITHUB_HAVE_GH=1
  fi
  if [[ "${DRY:-0}" -eq 0 && "$_GITHUB_HAVE_GH" -eq 0 ]]; then
    bl_die "gh CLI not installed or not authenticated (run: gh auth login)"
  fi
}

adapter_describe() { printf 'Repo: %s' "$_GITHUB_REPO"; }

adapter_project_desc() {
  [[ -n "$_GITHUB_PROJECT" ]] || return 0
  printf 'Project: %s #%s' "$_GITHUB_POWNER" "$_GITHUB_PROJECT"
}

adapter_dry_run_note() {
  [[ "$_GITHUB_HAVE_GH" -eq 1 ]] \
    || printf "Note: gh unavailable, so existing issues were not looked up; 'create' may become 'update'."
}

adapter_find() { # id -> "number<TAB>url" or empty
  [[ "$_GITHUB_HAVE_GH" -eq 1 ]] || return 0
  gh issue list --repo "$_GITHUB_REPO" --state all --search "$1 in:title" \
    --json number,title,url --limit 30 2>/dev/null \
    | bl_jqr --arg p "[$1] " '.[] | select(.title | startswith($p)) | "\(.number)\t\(.url)"' | head -1
}

adapter_sync_labels() { # FILE
  bl_jqr '.items[] | (if .type=="epic" then "epic" else "type:\(.type)" end),
          (if (.priority // null) != null then "priority:\(.priority)" else empty end),
          (if (.estimate // null) != null then "estimate:\(.estimate)" else empty end),
          ((.labels // [])[])' "$1" | sort -u | while IFS= read -r l; do
    [[ -n "$l" ]] && gh label create "$l" --repo "$_GITHUB_REPO" --force >/dev/null 2>&1 || true
  done
}

adapter_create() { # id title bodyfile labels -> "number<TAB>url"
  local id="$1" title="$2" body="$3" labels="$4" out url
  if out=$(gh issue create --repo "$_GITHUB_REPO" --title "$title" --body-file "$body" --label "$labels" 2>&1); then
    url=$(grep -Eo 'https://[^ ]+/issues/[0-9]+' <<<"$out" | tail -1)
    if [[ -z "$url" ]]; then
      printf 'could not parse issue URL from gh output: %s' "$out"
      return 1
    fi
    printf '%s\t%s' "${url##*/}" "$url"
  else
    printf '%s' "$out"
    return 1
  fi
}

adapter_update() { # key title bodyfile labels
  local out
  if out=$(gh issue edit "$1" --repo "$_GITHUB_REPO" --title "$2" --body-file "$3" --add-label "$4" 2>&1); then
    return 0
  fi
  printf '%s' "$out"
  return 1
}

adapter_refresh() { # key bodyfile
  gh issue edit "$1" --repo "$_GITHUB_REPO" --body-file "$2" >/dev/null 2>&1
}

adapter_link() { # childkey parentkey
  local child="$1" parent="$2" cid
  cid=$(gh api "repos/$_GITHUB_REPO/issues/$child" --jq .id 2>/dev/null || true)
  [[ -n "$cid" ]] || return 0
  gh api -X POST "repos/$_GITHUB_REPO/issues/$parent/sub_issues" -F sub_issue_id="$cid" >/dev/null 2>&1 \
    || echo "  note: sub-issue link $(_g_ref "$child") -> $(_g_ref "$parent") skipped (already linked or feature unavailable); 'Part of' text is in the body" >&2
  return 0
}

adapter_project_add() { # key url
  [[ -n "$_GITHUB_PROJECT" ]] || return 0
  [[ -n "$2" ]] || return 0
  gh project item-add "$_GITHUB_PROJECT" --owner "$_GITHUB_POWNER" --url "$2" >/dev/null 2>&1 \
    || echo "  warn: could not add $(_g_ref "$1") to project $_GITHUB_PROJECT (needs 'project' scope: gh auth refresh -s project)" >&2
  return 0
}

adapter_pull() { # state label limit -> JSON array [{number,title,state,labels,url}]
  local state="$1" label="$2" limit="$3"
  local -a args
  args=(issue list --repo "$_GITHUB_REPO" --state "$state" --limit "$limit" --json number,title,state,labels,url)
  [[ -z "$label" ]] || args+=(--label "$label")
  gh "${args[@]}" | jq '[.[] | {number,title,state,url,labels:[.labels[].name]}]'
}
