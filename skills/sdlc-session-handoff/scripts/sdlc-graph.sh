#!/usr/bin/env bash
# sdlc-graph.sh - knowledge graph of REQ / design / story / issue / PR / threat / finding links.
# Storage: .sdlc/memory/graph.jsonl (one JSON fact per line; sorted and de-duplicated for clean git diffs).
#
# Commands:
#   add-entity   --id ID --kind KIND [--title T] [--source PATH] [--attr key=value ...]   (upsert by id)
#   add-relation --from ID --rel REL --to ID
#   import       --file FILE.jsonl                                  bulk upsert entities and relations
#   show ID                                                          entity plus incoming/outgoing relations
#   list [--kind KIND]
#   find (--from ID | --to ID) [--rel REL]
#   gaps                                                             coverage and risk gaps
#   validate                                                         structure, enums, dangling references
#   normalize                                                        sort and de-duplicate (run after merges)
# Kinds: feature slice requirement nfr design_section adr epic story task spike issue pr threat control finding
# Rels:  implements covers depends_on blocks part_of mitigated_by closes derived_from tracked_by found_in relates_to
set -euo pipefail
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required" >&2; exit 2; }
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
GRAPH="$ROOT/.sdlc/memory/graph.jsonl"
KINDS="feature slice requirement nfr design_section adr epic story task spike issue pr threat control finding"
RELS="implements covers depends_on blocks part_of mitigated_by closes derived_from tracked_by found_in relates_to"
NUMERIC_ATTRS="issue pr number estimate"

die() { echo "ERROR: $*" >&2; exit 2; }
in_list() { local x="$1"; shift; for i in $*; do [[ "$i" == "$x" ]] && return 0; done; return 1; }
ensure() { mkdir -p "$(dirname "$GRAPH")"; [[ -f "$GRAPH" ]] || : > "$GRAPH"; }

normalize_into() { # stdin: JSONL (any order, duplicates) -> stdout: normalized JSONL
  jq -sc '
    ([ .[] | select(.type=="entity") ]   | reverse | unique_by(.id))                as $e
    | ([ .[] | select(.type=="relation") ] | unique_by([.from,.rel,.to]))            as $r
    | ($e[], $r[])'
}

append_and_normalize() { # $1 = JSONL lines to add
  ensure; local tmp; tmp="$(mktemp)"
  { cat "$GRAPH"; printf '%s\n' "$1"; } | normalize_into > "$tmp" && mv "$tmp" "$GRAPH" && chmod 644 "$GRAPH"
}

cmd_add_entity() {
  local id="" kind="" title="" source="" attrs='{}'
  while [[ $# -gt 0 ]]; do
    [[ $# -ge 2 ]] || die "option $1 needs a value"
    case "$1" in
      --id) id="$2" ;; --kind) kind="$2" ;; --title) title="$2" ;; --source) source="$2" ;;
      --attr)
        [[ "$2" == *=* ]] || die "--attr expects key=value"
        local k="${2%%=*}" v="${2#*=}"
        if in_list "$k" $NUMERIC_ATTRS && [[ "$v" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
          attrs=$(jq -c --arg k "$k" --argjson v "$v" '. + {($k):$v}' <<<"$attrs")
        else attrs=$(jq -c --arg k "$k" --arg v "$v" '. + {($k):$v}' <<<"$attrs"); fi ;;
      *) die "unknown option: $1" ;;
    esac; shift 2
  done
  [[ -n "$id" && -n "$kind" ]] || die "--id and --kind are required"
  in_list "$kind" $KINDS || echo "warn: unknown kind '$kind' (known: $KINDS)" >&2
  local line
  line=$(jq -nc --arg id "$id" --arg kind "$kind" --arg title "$title" --arg source "$source" --argjson attrs "$attrs" \
    '{type:"entity", id:$id, kind:$kind}
     + (if $title != "" then {title:$title} else {} end)
     + (if $source != "" then {source:$source} else {} end) + $attrs')
  append_and_normalize "$line"; echo "entity upserted: $id ($kind)"
}

cmd_add_relation() {
  local from="" rel="" to=""
  while [[ $# -gt 0 ]]; do
    [[ $# -ge 2 ]] || die "option $1 needs a value"
    case "$1" in --from) from="$2" ;; --rel) rel="$2" ;; --to) to="$2" ;; *) die "unknown option: $1" ;; esac; shift 2
  done
  [[ -n "$from" && -n "$rel" && -n "$to" ]] || die "--from, --rel and --to are required"
  in_list "$rel" $RELS || echo "warn: unknown relation '$rel' (known: $RELS)" >&2
  append_and_normalize "$(jq -nc --arg f "$from" --arg r "$rel" --arg t "$to" '{type:"relation", from:$f, rel:$r, to:$t}')"
  echo "relation recorded: $from -[$rel]-> $to"
}

cmd_import() {
  local file=""; [[ "${1:-}" == "--file" ]] && file="${2:-}"
  [[ -n "$file" && -f "$file" ]] || die "usage: import --file FILE.jsonl"
  jq -e . "$file" >/dev/null 2>&1 || die "$file is not valid JSONL"
  ensure; local tmp; tmp="$(mktemp)"
  cat "$GRAPH" "$file" | normalize_into > "$tmp" && mv "$tmp" "$GRAPH" && chmod 644 "$GRAPH"
  echo "imported $(jq -c . "$file" | wc -l | tr -d ' ') lines from $file"
}

cmd_show() {
  local id="${1:-}"; [[ -n "$id" ]] || die "usage: show ID"; ensure
  jq -sr --arg id "$id" '
    ([ .[] | select(.type=="entity" and .id==$id) ] | .[0]) as $e
    | if $e == null then "not found: \($id)" else
        ($e | tojson),
        ( [ .[] | select(.type=="relation" and .from==$id) ][] | "  -[\(.rel)]-> \(.to)" ),
        ( [ .[] | select(.type=="relation" and .to==$id) ][]   | "  <-[\(.rel)]- \(.from)" )
      end' "$GRAPH"
}

cmd_list() {
  local kind=""; [[ "${1:-}" == "--kind" ]] && kind="${2:-}"; ensure
  jq -r --arg k "$kind" 'select(.type=="entity" and ($k=="" or .kind==$k)) | "\(.id)\t\(.kind)\t\(.title // "")"' "$GRAPH"
}

cmd_find() {
  local from="" to="" rel=""
  while [[ $# -gt 0 ]]; do
    [[ $# -ge 2 ]] || die "option $1 needs a value"
    case "$1" in --from) from="$2" ;; --to) to="$2" ;; --rel) rel="$2" ;; *) die "unknown option: $1" ;; esac; shift 2
  done
  [[ -n "$from" || -n "$to" ]] || die "usage: find (--from ID | --to ID) [--rel REL]"; ensure
  jq -r --arg f "$from" --arg t "$to" --arg r "$rel" '
    select(.type=="relation" and ($f=="" or .from==$f) and ($t=="" or .to==$t) and ($r=="" or .rel==$r))
    | "\(.from) -[\(.rel)]-> \(.to)"' "$GRAPH"
}

cmd_gaps() {
  ensure
  local out; out="$(jq -rs '
    [ .[] | select(.type=="entity") ]   as $E
    | [ .[] | select(.type=="relation") ] as $R
    | ( $E[] | select(.kind=="requirement" or .kind=="nfr") | . as $e
        | select([ $R[] | select(.rel=="implements" and .to==$e.id) ] | length == 0)
        | "GAP requirement not implemented by any story/task: \(.id)" ),
      ( $E[] | select(.kind=="story") | . as $e
        | select([ $R[] | select(.rel=="implements" and .from==$e.id) ] | length == 0)
        | "GAP story with no requirement link: \(.id)" ),
      ( $E[] | select(.kind=="threat" and (.severity=="high" or .severity=="critical")) | . as $e
        | select([ $R[] | select(.rel=="mitigated_by" and .from==$e.id) ] | length == 0)
        | "GAP high/critical threat without mitigation: \(.id)" ),
      ( $E[] | select(.kind=="finding" and (.severity=="high" or .severity=="critical") and ((.status // "open")=="open")) | . as $e
        | select([ $R[] | select(.rel=="tracked_by" and .from==$e.id) ] | length == 0)
        | "GAP open high/critical finding not tracked by an issue/task: \(.id)" )' "$GRAPH")"
  if [[ -z "$out" ]]; then echo "No gaps found."; else echo "$out"; return 1; fi
}

cmd_validate() {
  ensure
  if [[ ! -s "$GRAPH" ]]; then echo "graph.jsonl: OK (empty)"; return 0; fi
  jq -e . "$GRAPH" >/dev/null 2>&1 || { echo "graph.jsonl: invalid JSON line(s)" >&2; return 1; }
  local errs; errs="$(jq -rs --arg kinds "$KINDS" --arg rels "$RELS" '
    [ .[] | select(.type=="entity") ]   as $E
    | [ .[] | select(.type=="relation") ] as $R
    | ([ $E[].id ]) as $ids
    | ($kinds | split(" ")) as $K
    | ($rels | split(" ")) as $RL
    | ( .[] | select((.type != "entity") and (.type != "relation")) | "ERROR line has unknown type: \(tojson)" ),
      ( $E[] | select((.id // "") == "" or (.kind // "") == "") | "ERROR entity missing id/kind: \(tojson)" ),
      ( $E[] | . as $x | select(($x.kind // "") != "" and (($K | index($x.kind)) == null)) | "WARN unknown kind \($x.kind) on \($x.id)" ),
      ( $R[] | select((.from // "") == "" or (.rel // "") == "" or (.to // "") == "") | "ERROR relation missing from/rel/to: \(tojson)" ),
      ( $R[] | . as $x | select(($x.rel // "") != "" and (($RL | index($x.rel)) == null)) | "WARN unknown relation \($x.rel): \($x.from) -> \($x.to)" ),
      ( $R[] | . as $x | select(($x.from // "") != "" and (($ids | index($x.from)) == null)) | "ERROR dangling relation source: \($x.from) (\($x.rel) -> \($x.to))" ),
      ( $R[] | . as $x | select(($x.to // "") != "" and (($ids | index($x.to)) == null)) | "ERROR dangling relation target: \($x.to) (\($x.from) \($x.rel))" ),
      ( [ $E[].id ] | group_by(.)[] | select(length > 1) | "ERROR duplicate entity id: \(.[0])" )' "$GRAPH")"
  if [[ -n "$errs" ]]; then echo "$errs"; fi
  if grep -q '^ERROR' <<<"$errs"; then echo "graph.jsonl: INVALID" >&2; return 1; fi
  echo "graph.jsonl: OK$(grep -q '^WARN' <<<"$errs" && echo ' (with warnings)' || true)"
}

cmd_normalize() {
  ensure; local tmp; tmp="$(mktemp)"
  normalize_into < "$GRAPH" > "$tmp" && mv "$tmp" "$GRAPH" && chmod 644 "$GRAPH"; echo "graph.jsonl normalized."
}

CMD="${1:-}"; shift || true
case "$CMD" in
  add-entity) cmd_add_entity "$@" ;;
  add-relation) cmd_add_relation "$@" ;;
  import) cmd_import "$@" ;;
  show) cmd_show "$@" ;;
  list) cmd_list "$@" ;;
  find) cmd_find "$@" ;;
  gaps) cmd_gaps ;;
  validate) cmd_validate ;;
  normalize) cmd_normalize ;;
  -h|--help|help|"") sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; [[ -n "$CMD" ]] || exit 2 ;;
  *) die "unknown command: $CMD (try --help)" ;;
esac
