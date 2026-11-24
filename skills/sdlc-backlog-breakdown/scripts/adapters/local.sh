#!/usr/bin/env bash
# local.sh - offline Markdown tracker adapter. Sourced by push/pull scripts.
#
# Tickets live in <local.output_dir>/<id>.md with YAML front matter and the backlog body.
# No network, no credentials. Idempotent: rerunning updates the same file and preserves `state`.
#
# Config (.sdlc/config.yaml):
#   tracker: local
#   local:
#     output_dir: docs/backlog/tickets    # relative to repo root (env SDLC_LOCAL_DIR overrides)
#
# Requires: jq, git (for repo root resolution by common.sh).

ADAPTER_NAME="local"
_LOCAL_DIR=""

_l_abs_dir() {
  case "$_LOCAL_DIR" in
    /*|[A-Za-z]:[/\\]*) printf '%s' "$_LOCAL_DIR" ;;
    *) printf '%s/%s' "$BL_ROOT" "$_LOCAL_DIR" ;;
  esac
}

_l_target() { printf '%s/%s.md' "$(_l_abs_dir)" "$1"; }
_l_rel_url() { printf '%s/%s.md' "$_LOCAL_DIR" "$1"; }

_l_meta() { # file -> YAML front matter body (between the first two --- lines)
  awk 'BEGIN{n=0} /^---[[:space:]]*$/{n++; if(n==2) exit; next} n==1{print}' "$1" | tr -d '\r'
}

_l_field() { # key file
  _l_meta "$2" | sed -nE "s/^$1:[[:space:]]*(.*)$/\1/p" | head -1
}

_l_title() { # JSON-quoted or plain title -> text
  local raw="$1" t
  [[ -n "$raw" ]] || { printf ''; return 0; }
  if t=$(bl_jqr '.' <<<"$raw" 2>/dev/null); then
    printf '%s' "$t"
  else
    printf '%s' "$raw" | sed -E 's/^"(.*)"$/\1/'
  fi
}

_l_write() { # id bodyfile
  local id="$1" body="$2" item target dir tmp state
  item=$(bl_jqc --arg id "$id" '.items[] | select(.id==$id)' "$FILE")
  [[ -n "$item" ]] || { printf 'backlog item %s not found in %s' "$id" "$FILE"; return 1; }
  target="$(_l_target "$id")"
  dir="$(dirname "$target")"
  mkdir -p "$dir" || return 1

  state="open"
  if [[ -f "$target" ]]; then
    state="$(_l_field state "$target")"
    state="${state:-open}"
  fi

  tmp="$(mktemp "${target}.tmp.XXXXXX")" || return 1
  {
    bl_jqr --arg state "$state" --arg tracker "$ADAPTER_NAME" '
      "---",
      "id: " + .id,
      "title: " + (.title | @json),
      "type: " + .type,
      (if (.parent // "") != "" then "parent: " + .parent else empty end),
      "state: " + $state,
      (if (.priority // null) != null then "priority: " + .priority else empty end),
      "estimate: " + ((.estimate // null) | tostring),
      "labels: " + ((.labels // []) | @json),
      "depends_on: " + ((.depends_on // []) | @json),
      "req_refs: " + ((.req_refs // []) | @json),
      (if (.design_ref // "") != "" then "design_ref: " + (.design_ref | @json) else empty end),
      "tracker: " + $tracker,
      "---"
    ' <<<"$item"
    cat "$body"
    [[ -z "$(tail -c 1 "$body" 2>/dev/null)" ]] || printf '\n'
  } > "$tmp" || { rm -f "$tmp"; return 1; }
  mv "$tmp" "$target"
}

adapter_init() {
  _LOCAL_DIR="${SDLC_LOCAL_DIR:-$(bl_cfg output_dir)}"
  _LOCAL_DIR="${_LOCAL_DIR:-docs/backlog/tickets}"
  _LOCAL_DIR="${_LOCAL_DIR%/}"
  [[ -n "$_LOCAL_DIR" ]] || bl_die "set local.output_dir in .sdlc/config.yaml"
}

adapter_describe() { printf 'Tickets: %s' "$_LOCAL_DIR"; }

adapter_find() { # id -> "id<TAB>relative-url" if the ticket file exists
  local id="$1" target
  target="$(_l_target "$id")"
  [[ -f "$target" ]] || return 0
  printf '%s\t%s' "$id" "$(_l_rel_url "$id")"
}

adapter_sync_labels() { return 0; }

adapter_create() { # id title bodyfile labels -> "id<TAB>relative-url"
  _l_write "$1" "$3" || return 1
  printf '%s\t%s' "$1" "$(_l_rel_url "$1")"
}

adapter_update() { # key title bodyfile labels
  _l_write "$1" "$3"
}

adapter_refresh() { return 0; }
adapter_link() { return 0; }
adapter_project_add() { return 0; }

adapter_pull() { # state label limit -> JSON array [{number,title,state,labels,url}]
  local state="${1:-open}" label="${2:-}" limit="${3:-200}"
  local dir f meta id st labels_json title_json title url count=0
  local -a items=()
  [[ "$limit" =~ ^[0-9]+$ ]] || limit=200
  dir="$(_l_abs_dir)"
  if [[ ! -d "$dir" ]]; then
    printf '[]\n'
    return 0
  fi
  for f in "$dir"/*.md; do
    [[ -f "$f" ]] || continue
    meta="$(_l_meta "$f")"
    id="$(sed -nE 's/^id:[[:space:]]*(.*)$/\1/p' <<<"$meta" | head -1)"
    [[ -n "$id" ]] || continue
    st="$(sed -nE 's/^state:[[:space:]]*(.*)$/\1/p' <<<"$meta" | head -1)"
    st="${st:-open}"
    if [[ "$state" != "all" && "$st" != "$state" ]]; then continue; fi
    labels_json="$(sed -nE 's/^labels:[[:space:]]*(.*)$/\1/p' <<<"$meta" | head -1)"
    labels_json="${labels_json:-[]}"
    jq -e 'type=="array"' <<<"$labels_json" >/dev/null 2>&1 || labels_json='[]'
    if [[ -n "$label" ]] && ! jq -e --arg l "$label" 'index($l) != null' <<<"$labels_json" >/dev/null 2>&1; then
      continue
    fi
    title_json="$(sed -nE 's/^title:[[:space:]]*(.*)$/\1/p' <<<"$meta" | head -1)"
    title="$(_l_title "$title_json")"
    url="$(_l_rel_url "$id")"
    items+=("$(bl_jqc -n --arg n "$id" --arg title "$title" --arg state "$st" \
      --arg url "$url" --argjson labels "$labels_json" \
      '{number:$n,title:$title,state:$state,url:$url,labels:$labels}')")
    count=$((count + 1))
    [[ "$count" -ge "$limit" ]] && break
  done
  if [[ ${#items[@]} -eq 0 ]]; then
    printf '[]\n'
  else
    printf '%s\n' "${items[@]}" | jq -s '.' | tr -d '\r'
  fi
}
