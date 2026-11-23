#!/usr/bin/env bash
# req-index.sh - requirement packs: split a large requirements document into slices, build and validate the index.
#
# A pack is docs/requirements/<feature>/ with: 00-index.md, glossary.md, nfr.md, slices/NN-<slug>.md, pack.json,
# index.json (generated). Small features can stay as a single docs/requirements/<feature>.md.
#
# Commands (all need bash, jq, awk, git):
#   analyze  --file F [--id-regex RE] [--json]        size, outline, ID stats, and a recommendation (single file vs pack)
#   skeleton --file F --feature SLUG [--title T] [--level N] [--id-policy keep|renumber] [--out PLAN.json]
#                                                     draft a split plan from the document's headings (then refine it)
#   split    --plan PLAN.json [--dry-run] [--allow-unassigned] [--force]
#                                                     split an existing document into a pack, verbatim, with a coverage check
#   init-pack --feature SLUG [--title T]              scaffold an empty pack for new large requirements
#   new-slice --feature SLUG --slug S --title T --prefix P [--priority Must] [--depends a,b] [--summary TEXT]
#   build    --feature SLUG                           regenerate index.json and the slice table in 00-index.md
#   validate --feature SLUG                           check structure, IDs, dependencies, sizes, index freshness
#   show     --feature SLUG (--index | --slice S | --id REQ-ID)   print the smallest useful piece
#   stale    --feature SLUG                           slices changed since their recorded approval hash
#   to-graph --feature SLUG [--apply]                 slices and requirements as knowledge-graph facts
# Env: SDLC_REQ_DIR (default docs/requirements)
set -eu

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
REQ_BASE="$ROOT/${SDLC_REQ_DIR:-docs/requirements}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TPL="$SCRIPT_DIR/../templates"
GRAPH_SH="$SCRIPT_DIR/../../sdlc-session-handoff/scripts/sdlc-graph.sh"
DEFAULT_PACK_RE='(REQ|NFR)-([A-Z][A-Z0-9]*-)?[0-9]+'
ANALYZE_RE='(REQ|FR|NFR|BR|UC|US|SR)-?[0-9]+([.][0-9]+)*|(REQ|NFR)-[A-Z][A-Z0-9]*-[0-9]+'
SLICE_LINES_WARN=300
SLICE_TOKENS_WARN=4500

die() { echo "ERROR: $*" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || die "jq is required"
valid_feature() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; }
pack_dir() { echo "$REQ_BASE/$1"; }
relpath() { echo "${1#"$ROOT"/}"; }

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -c1-16
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -c1-16
  else openssl dgst -sha256 "$1" | awk '{print substr($NF,1,16)}'; fi
}
approx_tokens() { local c; c="$(wc -c < "$1" | tr -d ' ')"; echo $(( (c + 3) / 4 )); }

# ---- front matter / body / ids ---------------------------------------------------------------------
fm_get() { # file key
  awk -v key="$2" 'NR==1 && $0!="---"{exit} NR>1 && $0=="---"{exit}
    NR>1 && index($0,key ":")==1 { v=substr($0,length(key)+2); sub(/^[ \t]+/,"",v); sub(/[ \t\r]+$/,"",v); print v; exit }' "$1"
}
body_of() { awk 'NR==1&&$0=="---"{fm=1;next} fm&&$0=="---"{fm=0;next} !fm{print}' "$1"; }
ids_stream() { # stdin text; $1 regex; prints D<TAB>id (definition position) and R<TAB>id (any occurrence)
  awk -v RE="$1" '
    /^```/ {f=!f; next}
    f {next}
    { x=$0; sub(/^[ \t|*>#-]+/,"",x)
      if (match(x, "^(" RE ")")) print "D\t" substr(x,1,RLENGTH)
      r=$0
      while (match(r, RE)) { print "R\t" substr(r,RSTART,RLENGTH); r=substr(r,RSTART+RLENGTH) } }'
}
def_titles() { # stdin text; $1 regex; prints id<TAB>title
  awk -v RE="$1" '
    /^```/ {f=!f; next}
    f {next}
    { x=$0; sub(/^[ \t|*>#-]+/,"",x)
      if (match(x, "^(" RE ")")) { id=substr(x,1,RLENGTH); t=substr(x,RLENGTH+1)
        sub(/^[ \t*:.|)-]+/,"",t); sub(/[ \t]*\|.*$/,"",t); gsub(/\*\*/,"",t); sub(/\r$/,"",t)
        if (length(t)>100) t=substr(t,1,100); print id "\t" t } }'
}
fill_tpl() { # template-file key=value ...  (single-line values); stdout
  local f="$1" c; shift; c="$(cat "$f")"
  local kv k v
  for kv in "$@"; do k="${kv%%=*}"; v="${kv#*=}"
    c="$(printf '%s\n' "$c" | awk -v k="{{$k}}" -v v="$v" '{ out=""; line=$0
      while ((i=index(line,k))>0) { out=out substr(line,1,i-1) v; line=substr(line,i+length(k)) } print out line }')"
  done
  printf '%s\n' "$c"
}
pack_re() { local r; r="$(jq -r '.id_regex // empty' "$1/pack.json" 2>/dev/null || true)"; echo "${r:-$DEFAULT_PACK_RE}"; }
slice_file() { # pack slug -> path of slice file
  local f; for f in "$1"/slices/*-"$2".md "$1"/slices/"$2".md; do [[ -f "$f" ]] && { echo "$f"; return 0; }; done; return 1
}
need_feature() { [[ -n "${1:-}" ]] || die "--feature is required"; valid_feature "$1" || die "invalid feature slug: $1"; }

# ======================================================================================================
# analyze
# ======================================================================================================
analysis_json() { # file regex -> JSON on stdout
  local file="$1" re="$2" lines words chars toks outline ids defs shall
  lines="$(awk 'END{print NR}' "$file")"; words="$(wc -w < "$file" | tr -d ' ')"; chars="$(wc -c < "$file" | tr -d ' ')"
  toks=$(( (chars + 3) / 4 ))
  outline="$(awk '
    /^```/ {f=!f; next}
    !f && /^#+[ \t]/ { n++; l=$0; lvl=0; while (substr(l,lvl+1,1)=="#") lvl++; t=substr(l,lvl+1); sub(/^[ \t]+/,"",t); sub(/\r$/,"",t); L[n]=lvl; S[n]=NR; T[n]=t }
    END { total=NR; for (i=1;i<=n;i++) { e=total; for (j=i+1;j<=n;j++) if (L[j]<=L[i]) { e=S[j]-1; break }
            if (L[i]<=3) printf "%d\t%d\t%d\t%d\t%s\n", L[i], S[i], e, e-S[i]+1, T[i] } }' "$file")"
  ids="$(ids_stream "$re" < "$file")"
  shall="$(grep -ciE '\b(shall|must)\b' "$file" || true)"
  local outline_json ids_json
  outline_json="$(printf '%s\n' "$outline" | jq -R -s -c '
    split("\n") | map(select(length>0) | split("\t")) | map({level:(.[0]|tonumber), start:(.[1]|tonumber), end:(.[2]|tonumber), lines:(.[3]|tonumber), title:.[4],
      hint:( if (.[4] | test("non-?functional|nfr|performance|security|privacy|compliance";"i")) then "nfr?"
             elif (.[4] | test("glossary|definitions|terminology|abbreviations";"i")) then "glossary?"
             elif (.[4] | test("revision|history|table of contents|contents|change log|document control";"i")) then "skip?"
             elif (.[4] | test("introduction|overview|scope|purpose|background|assumptions|constraints";"i")) then "overview?"
             else "" end)})')"
  ids_json="$(printf '%s\n' "$ids" | jq -R -s -c '
    split("\n") | map(select(length>0) | split("\t") | {k:.[0], id:.[1]}) as $all
    | ($all | map(.id) | unique) as $u
    | ($all | map(select(.k=="D") | .id) | group_by(.) | map(select(length>1) | .[0])) as $dups
    | { distinct: ($u|length), duplicate_definitions: $dups,
        prefixes: ($u | map(sub("[0-9][0-9.]*$";"")) | group_by(.) | map({prefix:.[0], count:length})) }')"
  local reqs; reqs="$(jq -n --argjson i "$ids_json" --argjson s "${shall:-0}" 'if $i.distinct > 0 then $i.distinct else $s end')"
  jq -n --arg file "$(relpath "$file")" --argjson lines "$lines" --argjson words "$words" --argjson toks "$toks" \
        --argjson outline "$outline_json" --argjson ids "$ids_json" --argjson shall "${shall:-0}" --argjson reqs "$reqs" '
    ( [ (if $lines > 400 then "\($lines) lines (over 400)" else empty end),
        (if $reqs > 40 then "about \($reqs) requirements (over 40)" else empty end),
        (if $toks > 6000 then "about \($toks) tokens (over 6000)" else empty end) ] ) as $why
    | { file:$file, lines:$lines, words:$words, approx_tokens:$toks, shall_must_lines:$shall,
        estimated_requirements:$reqs, ids:$ids, outline:$outline,
        recommendation: (if ($why|length) > 0 then "pack" else "single-file" end), reasons:$why }'
}
cmd_analyze() {
  local file="" re="$ANALYZE_RE" json=0
  while [[ $# -gt 0 ]]; do case "$1" in
    --file) file="${2:-}"; shift 2 ;; --id-regex) re="${2:-}"; shift 2 ;; --json) json=1; shift ;; *) die "unknown option: $1" ;; esac; done
  [[ -n "$file" ]] || die "--file is required"; [[ "$file" = /* ]] || file="$ROOT/$file"; [[ -f "$file" ]] || die "not found: $file"
  local out; out="$(analysis_json "$file" "$re")"
  if [[ $json -eq 1 ]]; then echo "$out" | jq .; return 0; fi
  echo "$out" | jq -r '
    "File: \(.file)", "Size: \(.lines) lines, \(.words) words, about \(.approx_tokens) tokens",
    "Requirements (estimate): \(.estimated_requirements)  [distinct IDs: \(.ids.distinct), shall/must lines: \(.shall_must_lines)]",
    ( if (.ids.prefixes|length) > 0 then "ID prefixes: " + (.ids.prefixes | map("\(.prefix)(\(.count))") | join(" ")) else "ID prefixes: none detected (pass --id-regex if the document uses another style)" end ),
    ( if (.ids.duplicate_definitions|length) > 0 then "WARNING: IDs defined more than once: " + (.ids.duplicate_definitions | join(", ")) else empty end ),
    "",
    "RECOMMENDATION: \(.recommendation)" + ( if (.reasons|length) > 0 then " (" + (.reasons|join("; ")) + ")" else "" end ),
    "",
    "Outline (level, lines start-end, size, hint):",
    ( .outline[] | "  " + ("  " * (.level - 1)) + "L\(.level) \(.start)-\(.end) (\(.lines) lines) \(.title)" + ( if .hint != "" then "  [" + .hint + "]" else "" end ) )'
}

# ======================================================================================================
# skeleton
# ======================================================================================================
cmd_skeleton() {
  local file="" feature="" title="" level="" policy="keep" out="" re=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --file) file="${2:-}"; shift 2 ;; --feature) feature="${2:-}"; shift 2 ;; --title) title="${2:-}"; shift 2 ;;
    --level) level="${2:-}"; shift 2 ;; --id-policy) policy="${2:-}"; shift 2 ;; --out) out="${2:-}"; shift 2 ;;
    --id-regex) re="${2:-}"; shift 2 ;; *) die "unknown option: $1" ;; esac; done
  [[ -n "$file" ]] || die "--file is required"; need_feature "$feature"
  [[ "$policy" == "keep" || "$policy" == "renumber" ]] || die "--id-policy must be keep or renumber"
  [[ "$file" = /* ]] || file="$ROOT/$file"; [[ -f "$file" ]] || die "not found: $file"
  local a; a="$(analysis_json "$file" "${re:-$ANALYZE_RE}")"
  local total; total="$(echo "$a" | jq .lines)"
  if [[ -z "$level" ]]; then
    level="$(echo "$a" | jq 'if ([.outline[] | select(.level==1)] | length) == 1 and (([.outline[] | select(.level==1)][0].start) <= 3) then 2 else 1 end')"
  fi
  local plan
  plan="$(echo "$a" | jq --arg feature "$feature" --arg title "${title:-$feature}" --arg source "$(relpath "$file")" --arg policy "$policy" \
      --argjson level "$level" --argjson total "$total" --arg re "$re" '
    def slugify: ascii_downcase | gsub("^[0-9]+([.][0-9]+)*[.)]?[ \t]*";"") | gsub("[^a-z0-9]+";"-") | ltrimstr("-") | rtrimstr("-") | .[0:40];
    ([.outline[] | select(.level == $level)]) as $secs
    | (if ($secs|length) > 0 then ($secs[0].start - 1) else 0 end) as $pre
    | ($secs | map(. + {slug:(.title|slugify)})) as $s
    | ($s | to_entries | map(.value + {idx:.key})) as $S
    | ($S | map(select(.hint == "" ))) as $slices
    | { feature:$feature, title:$title, source:$source, id_policy:$policy }
      + (if $re != "" then {id_regex:$re} else {} end)
      + { slices: ( $slices | to_entries | map( .key as $i | .value | {
            slug: (if .slug == "" then "slice-\($i+1)" else .slug end),
            title: (.title | gsub("^[0-9]+([.][0-9]+)*[.)]?[ \t]*";"")),
            prefix: ((.slug | gsub("[^a-z0-9]";"") | ascii_upcase | .[0:4]) as $p | (if ($p|length) < 2 then "S\($i+1)" else $p end)),
            summary: "TODO", priority: "Must", depends_on: [], ranges: [[.start, .end]] } ) ),
          cross_cutting: {
            overview: { ranges: ( (if $pre >= 1 then [[1,$pre]] else [] end) + ($S | map(select(.hint=="overview?") | [.start,.end])) ) },
            nfr:      { prefix:"GEN", ranges: ($S | map(select(.hint=="nfr?") | [.start,.end])) },
            glossary: { ranges: ($S | map(select(.hint=="glossary?") | [.start,.end])) } },
          skip: ($S | map(select(.hint=="skip?") | [.start,.end])),
          skip_reason: "TODO: confirm these sections (table of contents / revision history) can be skipped" }
    | .slices |= (reduce .[] as $x ([]; . + [ $x + {slug: ( if (map(.slug) | index($x.slug)) != null then "\($x.slug)-\(length+1)" else $x.slug end) } ]))
    | .slices |= (reduce .[] as $x ([]; . + [ $x + {prefix: ( if (map(.prefix) | index($x.prefix)) != null then "\($x.prefix[0:3])\(length+1)" else $x.prefix end) } ]))')"
  if [[ -n "$out" ]]; then printf '%s\n' "$plan" | jq . > "$out"; echo "Plan skeleton written to $out. Review slices, ranges, prefixes, cross-cutting and skip, then run: req-index.sh split --plan $out --dry-run" >&2
  else printf '%s\n' "$plan" | jq .; fi
}

# ======================================================================================================
# split
# ======================================================================================================
cmd_split() {
  local plan="" dry=0 allow=0 force=0
  while [[ $# -gt 0 ]]; do case "$1" in
    --plan) plan="${2:-}"; shift 2 ;; --dry-run) dry=1; shift ;; --allow-unassigned) allow=1; shift ;; --force) force=1; shift ;;
    *) die "unknown option: $1" ;; esac; done
  [[ -n "$plan" && -f "$plan" ]] || die "--plan PLAN.json is required"
  jq -e '(.feature|type=="string") and (.source|type=="string") and (.slices|type=="array" and length>0)' "$plan" >/dev/null 2>&1 \
    || die "plan needs feature (string), source (string) and slices (non-empty array)"
  local feature source policy re title
  feature="$(jq -r .feature "$plan")"; need_feature "$feature"
  source="$(jq -r .source "$plan")"; [[ "$source" = /* ]] || source="$ROOT/$source"; [[ -f "$source" ]] || die "source not found: $source"
  policy="$(jq -r '.id_policy // "keep"' "$plan")"; [[ "$policy" == "keep" || "$policy" == "renumber" ]] || die "id_policy must be keep or renumber"
  re="$(jq -r '.id_regex // empty' "$plan")"; title="$(jq -r '.title // .feature' "$plan")"
  local bad; bad="$(jq -r '.slices[] | select((.slug // "" | test("^[a-z0-9][a-z0-9-]*$") | not) or ((.ranges // []) | length == 0)) | .slug // "(missing slug)"' "$plan")"
  [[ -z "$bad" ]] || die "slices need a lowercase slug (a-z0-9-) and at least one range: $bad"
  local dupslug; dupslug="$(jq -r '[.slices[].slug] | group_by(.) | map(select(length>1) | .[0]) | join(", ")' "$plan")"
  [[ -z "$dupslug" ]] || die "duplicate slice slugs: $dupslug"
  if [[ "$policy" == "renumber" ]]; then
    local badp; badp="$(jq -r '.slices[] | select((.prefix // "") | test("^[A-Z][A-Z0-9]{1,7}$") | not) | .slug' "$plan")"
    [[ -z "$badp" ]] || die "renumber needs an uppercase prefix (2-8 chars, A-Z0-9) on every slice: $badp"
    local pdup; pdup="$(jq -r '[.slices[].prefix, (.cross_cutting.nfr.prefix // "GEN")] | group_by(.) | map(select(length>1) | .[0]) | join(", ")' "$plan")"
    [[ -z "$pdup" ]] || die "prefixes must be unique (including nfr prefix, default GEN): $pdup"
  fi
  local N; N="$(awk 'END{print NR}' "$source")"
  local tmpd; tmpd="$(mktemp -d)"
  jq -r '
    ( .slices[] | .slug as $s | (.ranges // [])[] | "slice:\($s)\t\(.[0])\t\(.[1])" ),
    ( (.cross_cutting // {}) | to_entries[] | .key as $k | (.value.ranges // [])[] | "\($k)\t\(.[0])\t\(.[1])" ),
    ( (.skip // [])[] | "skip\t\(.[0])\t\(.[1])" )' "$plan" > "$tmpd/assign.tsv"
  local unknown; unknown="$(cut -f1 "$tmpd/assign.tsv" | sort -u | grep -vE '^(slice:.*|nfr|glossary|overview|skip)$' || true)"
  [[ -z "$unknown" ]] || die "unknown cross_cutting targets (allowed: nfr, glossary, overview): $unknown"
  # coverage check
  awk -F'\t' -v N="$N" '
    FNR==NR {
      if ($2 !~ /^[0-9]+$/ || $3 !~ /^[0-9]+$/) { print "ERR bad range for " $1 ": " $2 "," $3; next }
      if ($2 < 1 || $3 < $2 || $3 > N) { print "ERR out of bounds for " $1 ": " $2 "-" $3 " (source has " N " lines)"; next }
      for (i=$2; i<=$3; i++) { if (i in owner) { key=$1 " / " owner[i]; ov[key]++ } else owner[i]=$1 }
      next }
    { if ($0 ~ /[^ \t\r]/) { if (FNR in owner) cnt[owner[FNR]]++; else un[++nu]=FNR } }
    END {
      for (k in ov) print "ERR overlap (" k "): " ov[k] " line(s)"
      for (t in cnt) print "COUNT\t" t "\t" cnt[t]
      s=0
      for (i=1; i<=nu; i++) { if (s==0) { s=un[i]; p=un[i] } else if (un[i]==p+1) p=un[i]; else { print "UNASSIGNED\t" s "\t" p; s=un[i]; p=un[i] } }
      if (s!=0) print "UNASSIGNED\t" s "\t" p
      print "UNASSIGNED_TOTAL\t" nu+0 }' "$tmpd/assign.tsv" "$source" > "$tmpd/coverage.txt"
  local errs; errs="$(grep '^ERR' "$tmpd/coverage.txt" || true)"
  local unassigned; unassigned="$(awk -F'\t' '$1=="UNASSIGNED_TOTAL"{print $2}' "$tmpd/coverage.txt")"
  echo "Source: $(relpath "$source") ($N lines)   Feature: $feature   ID policy: $policy"
  echo "Coverage (non-blank lines per target):"
  awk -F'\t' '$1=="COUNT"{printf "  %-28s %s\n", $2, $3}' "$tmpd/coverage.txt" | sort
  if [[ -n "$errs" ]]; then echo "$errs" >&2; die "plan has errors (fix ranges so no range overlaps or runs past the end)"; fi
  if [[ "${unassigned:-0}" -gt 0 ]]; then
    echo "Unassigned non-blank lines: $unassigned (not in any slice, cross-cutting target, or skip)"
    awk -F'\t' '$1=="UNASSIGNED"{print "  lines " $2 "-" $3}' "$tmpd/coverage.txt" | head -20
    if [[ $allow -eq 0 ]]; then die "every non-blank line must be assigned or skipped. Fix the plan, or pass --allow-unassigned to park them in _unassigned.md"; fi
  else echo "Unassigned non-blank lines: 0 (full coverage)"; fi
  if [[ $dry -eq 1 ]]; then echo; echo "Dry run complete. Nothing written."; rm -rf "$tmpd"; return 0; fi

  local pack; pack="$(pack_dir "$feature")"
  if [[ -d "$pack" && -n "$(ls -A "$pack" 2>/dev/null)" && $force -eq 0 ]]; then die "$(relpath "$pack") already exists and is not empty (use --force to overwrite)"; fi
  rm -rf "$pack"; mkdir -p "$pack/slices" "$pack/_source"
  cp "$source" "$pack/_source/$(basename "$source")"
  local base; base="$(basename "$source")"

  extract() { # target -> verbatim blocks with provenance comments
    awk -F'\t' -v T="$1" '$1==T{print $2 "\t" $3}' "$tmpd/assign.tsv" | sort -n | while IFS=$'\t' read -r s e; do
      printf '<!-- source: %s L%s-L%s -->\n' "$base" "$s" "$e"; sed -n "${s},${e}p" "$source"; printf '\n'; done
  }
  # slices
  local i=0 slug stitle sprefix sprio sdeps ssum
  : > "$tmpd/order.txt"
  while IFS=$'\t' read -r slug stitle sprefix sprio sdeps ssum; do
    i=$((i+1)); local nn; nn="$(printf '%02d' "$i")"
    [[ "$sprefix" == "-" ]] && sprefix=""; [[ "$sprio" == "-" ]] && sprio=""; [[ "$sdeps" == "-" ]] && sdeps=""; [[ "$ssum" == "-" ]] && ssum=""
    local f="$pack/slices/$nn-$slug.md"
    { printf -- '---\nslice: %s\ntitle: %s\nprefix: %s\nstatus: draft\npriority: %s\nowner:\ndepends_on: %s\nsummary: %s\nsource: %s\n---\n\n# %s\n\n' \
        "$slug" "$stitle" "$sprefix" "$sprio" "$sdeps" "$ssum" "$base" "$stitle"
      extract "slice:$slug"; } > "$f"
    echo "$f" >> "$tmpd/order.txt"
  done < <(jq -r '.slices[] | [.slug, (.title // .slug), ((.prefix // "") | if .=="" then "-" else . end), ((.priority // "") | if .=="" then "-" else . end),
                   ((.depends_on // []) | join(", ") | if .=="" then "-" else . end), ((.summary // "") | if .=="" then "-" else . end)] | @tsv' "$plan")
  # cross-cutting
  local has_nfr has_gl nfr_prefix; nfr_prefix="$(jq -r '.cross_cutting.nfr.prefix // "GEN"' "$plan")"
  { printf -- '---\nslice: nfr\ntitle: Cross-cutting requirements\nprefix: %s\nstatus: draft\nsummary: Non-functional and cross-cutting requirements shared by all slices\n---\n\n# Cross-cutting requirements\n\n' "$nfr_prefix"
    if grep -q '^nfr	' "$tmpd/assign.tsv"; then extract nfr; else fill_tpl "$TPL/requirements-nfr.md.tmpl" | awk 'f{print} /^# /{f=1}'; fi; } > "$pack/nfr.md"
  { printf -- '---\nslice: glossary\ntitle: Glossary\nstatus: draft\n---\n\n# Glossary\n\n'
    if grep -q '^glossary	' "$tmpd/assign.tsv"; then extract glossary; else printf '| Term | Meaning |\n|---|---|\n|  |  |\n'; fi; } > "$pack/glossary.md"
  if [[ "$unassigned" -gt 0 ]]; then
    { printf '# Unassigned lines (parked by --allow-unassigned)\n\nMove each block into a slice, then delete this file.\n\n'
      awk -F'\t' '$1=="UNASSIGNED"{print $2 "\t" $3}' "$tmpd/coverage.txt" | while IFS=$'\t' read -r s e; do
        printf '<!-- source: %s L%s-L%s -->\n' "$base" "$s" "$e"; sed -n "${s},${e}p" "$source"; printf '\n'; done; } > "$pack/_unassigned.md"
  fi
  # index
  local overview_file="$tmpd/overview.md"
  if grep -q '^overview	' "$tmpd/assign.tsv"; then extract overview > "$overview_file"; else printf 'TODO: problem statement, goals, non-goals, actors.\n' > "$overview_file"; fi
  fill_tpl "$TPL/requirements-index.md.tmpl" "FEATURE=$feature" "TITLE=$title" "SOURCE=_source/$base" \
    | awk -v f="$overview_file" '$0=="{{OVERVIEW}}"{while((getline l<f)>0)print l; next}{print}' > "$pack/00-index.md"

  # ID policy
  local pack_re_value="${re:-$ANALYZE_RE}"
  if [[ "$policy" == "renumber" ]]; then pack_re_value="$DEFAULT_PACK_RE"; fi
  jq -n --arg feature "$feature" --arg policy "$policy" --arg re "$pack_re_value" --arg src "_source/$base" --arg orig "$(relpath "$source")" \
    '{schema_version:1, feature:$feature, id_policy:$policy, id_regex:$re, source:$src, split_from:$orig, created_by:"req-index.sh split"}' > "$pack/pack.json"
  if [[ "$policy" == "renumber" ]]; then renumber_pack "$pack" "${re:-$ANALYZE_RE}" "$nfr_prefix" "$tmpd"; fi

  cmd_build --feature "$feature" >/dev/null
  write_split_report "$pack" "$plan" "$tmpd" "$base" "$N" "$policy"
  echo
  echo "Split complete: $(relpath "$pack")/"
  echo "  slices:  $(ls "$pack"/slices/*.md | wc -l | tr -d ' ')    original kept at: $(relpath "$pack")/_source/$base"
  echo "  report:  $(relpath "$pack")/_split-report.md"
  echo "Next: review each slice (status is draft), then: req-index.sh validate --feature $feature"
  rm -rf "$tmpd"
}

renumber_pack() { # pack old_regex nfr_prefix tmpd  -> rewrites IDs; writes id-map.json
  local pack="$1" oldre="$2" nfrp="$3" tmpd="$4" newre="$DEFAULT_PACK_RE"
  : > "$tmpd/idmap.tsv"; : > "$tmpd/conflicts.txt"
  local f prefix kindc
  local targets=(); local g; for g in "$pack"/slices/*.md; do targets+=("$g"); done; targets+=("$pack/nfr.md")
  for f in "${targets[@]}"; do
    prefix="$(fm_get "$f" prefix)"; [[ "$f" == */nfr.md ]] && prefix="$nfrp"
    local nreq=0 nnfr=0 id new
    while IFS= read -r id; do
      [[ -n "$id" ]] || continue
      if [[ "$id" =~ ^(REQ|NFR)-[A-Z][A-Z0-9]*-[0-9]+$ ]]; then continue; fi
      if awk -F'\t' -v id="$id" '$1==id{f=1} END{exit !f}' "$tmpd/idmap.tsv"; then echo "$id	$(basename "$f")" >> "$tmpd/conflicts.txt"; continue; fi
      if [[ "$id" =~ ^NFR ]]; then nnfr=$((nnfr+1)); new="$(printf 'NFR-%s-%03d' "$prefix" "$nnfr")"
      else nreq=$((nreq+1)); new="$(printf 'REQ-%s-%03d' "$prefix" "$nreq")"; fi
      printf '%s\t%s\t%s\n' "$id" "$new" "${f#"$pack"/}" >> "$tmpd/idmap.tsv"
    done < <(body_of "$f" | ids_stream "$oldre" | awk -F'\t' '$1=="D"{print $2}' | awk '!s[$0]++')
  done
  # rewrite every markdown file in the pack (whole-token matches only)
  local all=(); for g in "$pack"/00-index.md "$pack"/glossary.md "$pack"/nfr.md "$pack"/slices/*.md "$pack"/_unassigned.md; do [[ -f "$g" ]] && all+=("$g"); done
  for f in "${all[@]}"; do
    awk -F'\t' -v RE="$oldre" '
      FNR==NR { MAP[$1]=$2; next }
      /^```/ { fence=!fence }
      { line=$0; if (fence) { print; next}
        out=""; rest=line
        while (match(rest, RE)) {
          pre=substr(rest,1,RSTART-1); tok=substr(rest,RSTART,RLENGTH); after=substr(rest,RSTART+RLENGTH)
          prevc=substr(out pre, length(out pre), 1); nextc=substr(after,1,1)
          if ((tok in MAP) && prevc !~ /[A-Za-z0-9_-]/ && nextc !~ /[A-Za-z0-9_-]/) tok=MAP[tok]
          out=out pre tok; rest=after }
        print out rest }' "$tmpd/idmap.tsv" "$f" > "$tmpd/rw.tmp" && mv "$tmpd/rw.tmp" "$f"
  done
  jq -R -s '{schema_version:1, map:(split("\n")|map(select(length>0)|split("\t"))|map({old:.[0], new:.[1], defined_in:.[2]})),
             conflicts:(. as $x | [])}' "$tmpd/idmap.tsv" > "$pack/id-map.json"
  if [[ -s "$tmpd/conflicts.txt" ]]; then
    local c; c="$(awk -F'\t' '{printf "%s (also defined in %s)\n", $1, $2}' "$tmpd/conflicts.txt")"
    jq --arg c "$c" '.conflicts = ($c | split("\n") | map(select(length>0)))' "$pack/id-map.json" > "$tmpd/m.json" && mv "$tmpd/m.json" "$pack/id-map.json"
    echo "WARNING: some legacy IDs are defined in more than one target; the first definition got the new ID (see id-map.json conflicts)." >&2
  fi
}

write_split_report() { # pack plan tmpd base N policy
  local pack="$1" plan="$2" tmpd="$3" base="$4" N="$5" policy="$6"
  {
    echo "# Split report"; echo
    echo "- Source: \`$base\` ($N lines), kept unmodified in \`_source/\`"
    echo "- ID policy: $policy"; echo
    echo "## Targets"; echo
    echo "| Target | Non-blank lines | Source ranges |"; echo "|---|---|---|"
    awk -F'\t' '$1=="COUNT"{c[$2]=$3} END{for(t in c) print t "\t" c[t]}' "$tmpd/coverage.txt" | sort | while IFS=$'\t' read -r t c; do
      r="$(awk -F'\t' -v T="$t" '$1==T{printf "L%s-L%s ", $2, $3}' "$tmpd/assign.tsv")"; echo "| $t | $c | $r |"; done
    echo
    local sk; sk="$(awk -F'\t' '$1=="skip"{printf "L%s-L%s ", $2, $3}' "$tmpd/assign.tsv")"
    echo "## Skipped"; echo; if [[ -n "$sk" ]]; then echo "Ranges: $sk"; echo; echo "Reason: $(jq -r '.skip_reason // "not stated"' "$plan")"; else echo "None."; fi
    echo
    echo "## Unassigned"; echo
    if [[ -f "$pack/_unassigned.md" ]]; then echo "Parked in \`_unassigned.md\`. Move into slices and delete it."; else echo "None. Every non-blank source line was assigned or skipped."; fi
    echo
    if [[ -f "$pack/id-map.json" ]]; then
      echo "## ID mapping"; echo; echo "Old to new IDs are in \`id-map.json\` ($(jq '.map|length' "$pack/id-map.json") mapped)."
      local nc; nc="$(jq '.conflicts|length' "$pack/id-map.json")"; [[ "$nc" -gt 0 ]] && { echo; echo "Conflicts to resolve by hand:"; jq -r '.conflicts[] | "- " + .' "$pack/id-map.json"; }
      echo
    fi
    echo "## Review checklist"; echo
    echo "- [ ] Each slice reads on its own (add missing context from \`glossary.md\` or the index overview)"
    echo "- [ ] Slice \`summary\`, \`priority\`, \`depends_on\`, and \`owner\` filled in"
    echo "- [ ] Requirements that apply to every slice live in \`nfr.md\`, not copied into slices"
    echo "- [ ] Cross-references below are updated to point at slice files or requirement IDs"
    echo
    echo "### Possible dangling references (text like 'section 3.2', 'see above')"; echo
    local refs; refs="$(cd "$pack" && grep -nEi '((section|sect\.|chapter|appendix|§) *[0-9]|see (above|below))' slices/*.md nfr.md glossary.md 2>/dev/null | head -40 || true)"
    if [[ -n "$refs" ]]; then echo '```'; echo "$refs"; echo '```'; else echo "None found."; fi
  } > "$pack/_split-report.md"
}

# ======================================================================================================
# init-pack / new-slice
# ======================================================================================================
cmd_init_pack() {
  local feature="" title=""
  while [[ $# -gt 0 ]]; do case "$1" in --feature) feature="${2:-}"; shift 2 ;; --title) title="${2:-}"; shift 2 ;; *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"
  [[ ! -d "$pack" ]] || die "$(relpath "$pack") already exists"
  mkdir -p "$pack/slices"
  echo '- (new pack)' > /dev/null
  fill_tpl "$TPL/requirements-index.md.tmpl" "FEATURE=$feature" "TITLE=${title:-$feature}" "SOURCE=n/a (new pack)" \
    | awk '$0=="{{OVERVIEW}}"{print "TODO: problem statement, goals, non-goals, actors."; next}{print}' > "$pack/00-index.md"
  fill_tpl "$TPL/requirements-nfr.md.tmpl" > "$pack/nfr.md"
  fill_tpl "$TPL/requirements-glossary.md.tmpl" > "$pack/glossary.md"
  jq -n --arg f "$feature" --arg re "$DEFAULT_PACK_RE" '{schema_version:1, feature:$f, id_policy:"pack", id_regex:$re, created_by:"req-index.sh init-pack"}' > "$pack/pack.json"
  cmd_build --feature "$feature" >/dev/null
  echo "Pack scaffolded at $(relpath "$pack")/. Add capability slices with: req-index.sh new-slice --feature $feature --slug <slug> --title <title> --prefix <PFX>"
}
cmd_new_slice() {
  local feature="" slug="" title="" prefix="" prio="Must" deps="" summary=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --feature) feature="${2:-}"; shift 2 ;; --slug) slug="${2:-}"; shift 2 ;; --title) title="${2:-}"; shift 2 ;; --prefix) prefix="${2:-}"; shift 2 ;;
    --priority) prio="${2:-}"; shift 2 ;; --depends) deps="${2:-}"; shift 2 ;; --summary) summary="${2:-}"; shift 2 ;; *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"; [[ -d "$pack" ]] || die "no pack (run init-pack first)"
  [[ "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "--slug must be lowercase letters, digits, hyphens"
  [[ "$prefix" =~ ^[A-Z][A-Z0-9]{1,7}$ ]] || die "--prefix must be 2-8 uppercase letters/digits (e.g. PREF)"
  [[ -n "$title" ]] || die "--title is required"
  slice_file "$pack" "$slug" >/dev/null && die "slice $slug already exists"
  local clash; clash="$(grep -lE "^prefix: $prefix\$" "$pack"/slices/*.md 2>/dev/null || true)"; [[ -z "$clash" ]] || die "prefix $prefix already used by $(basename "$clash")"
  local n; n="$(ls "$pack"/slices/*.md 2>/dev/null | wc -l | tr -d ' ')"; local nn; nn="$(printf '%02d' $((n+1)))"
  fill_tpl "$TPL/requirements-slice.md.tmpl" "SLUG=$slug" "TITLE=$title" "PREFIX=$prefix" "PRIORITY=$prio" "DEPENDS=$deps" "SUMMARY=$summary" > "$pack/slices/$nn-$slug.md"
  cmd_build --feature "$feature" >/dev/null
  echo "Created $(relpath "$pack")/slices/$nn-$slug.md (IDs will look like REQ-$prefix-001)"
}

# ======================================================================================================
# build / validate
# ======================================================================================================
compute_index() { # feature outfile -> writes JSON; sets globals ERRS/WARNS as newline lists
  local feature="$1" out="$2" pack; pack="$(pack_dir "$feature")"
  [[ -d "$pack" ]] || die "no pack at $(relpath "$pack") (run init-pack or split)"
  local re; re="$(pack_re "$pack")"
  local tmpd; tmpd="$(mktemp -d)"; : > "$tmpd/items.jsonl"; : > "$tmpd/defs.tsv"; : > "$tmpd/refs.tsv"
  local f kind rel slug title status prio prefix summary deps lines toks hash ids depsjson idsjson
  local files=(); local g
  for g in "$pack"/slices/*.md; do [[ -f "$g" ]] && files+=("$g"); done
  [[ -f "$pack/nfr.md" ]] && files+=("$pack/nfr.md"); [[ -f "$pack/glossary.md" ]] && files+=("$pack/glossary.md")
  for f in "${files[@]}"; do
    rel="${f#"$pack"/}"; kind=slice; [[ "$rel" != slices/* ]] && kind=cross
    slug="$(fm_get "$f" slice)"; if [[ -z "$slug" ]]; then slug="$(basename "$f" .md)"; slug="${slug#[0-9][0-9]-}"; fi
    title="$(fm_get "$f" title)"; status="$(fm_get "$f" status)"; prio="$(fm_get "$f" priority)"; prefix="$(fm_get "$f" prefix)"
    summary="$(fm_get "$f" summary)"; deps="$(fm_get "$f" depends_on)"
    lines="$(body_of "$f" | awk 'END{print NR}')"; toks="$(approx_tokens "$f")"; hash="$(hash_file "$f")"
    body_of "$f" | ids_stream "$re" > "$tmpd/ids.tsv"
    ids="$(awk -F'\t' '$1=="D"{print $2}' "$tmpd/ids.tsv" | awk '!s[$0]++')"
    body_of "$f" | def_titles "$re" | awk -F'\t' -v file="$rel" '{print $1 "\t" file "\t" $2}' >> "$tmpd/defs.tsv"
    awk -F'\t' -v file="$rel" '$1=="R"{print $2 "\t" file}' "$tmpd/ids.tsv" | sort -u >> "$tmpd/refs.tsv"
    depsjson="$(printf '%s' "$deps" | tr -d '[]' | tr ',' '\n' | sed 's/^[ \t]*//;s/[ \t]*$//' | awk 'length>0' | jq -R . | jq -sc .)"
    idsjson="$(printf '%s\n' "$ids" | awk 'length>0' | jq -R . | jq -sc .)"
    jq -nc --arg kind "$kind" --arg slug "$slug" --arg file "$rel" --arg title "$title" --arg status "$status" --arg prio "$prio" --arg prefix "$prefix" \
       --arg summary "$summary" --argjson deps "$depsjson" --argjson lines "$lines" --argjson toks "$toks" --arg hash "$hash" --argjson ids "$idsjson" \
       '{kind:$kind, slug:$slug, file:$file, title:$title, status:$status, priority:$prio, prefix:$prefix, summary:$summary, depends_on:$deps,
         lines:$lines, approx_tokens:$toks, hash:$hash, requirement_ids:$ids}' >> "$tmpd/items.jsonl"
  done
  local dups; dups="$(awk -F'\t' '{c[$1]++; f[$1]=f[$1] " " $2} END{for(i in c) if(c[i]>1) print i ":" f[i]}' "$tmpd/defs.tsv" | sort)"
  local undefined; undefined="$(awk -F'\t' 'NR==FNR{d[$1]=1;next} !($1 in d){print $1 " (in " $2 ")"}' "$tmpd/defs.tsv" "$tmpd/refs.tsv" | sort -u)"
  local reqs; reqs="$(jq -R -s 'split("\n") | map(select(length>0) | split("\t")) | map({key:.[0], value:{file:.[1], title:(.[2] // "")}}) | from_entries' "$tmpd/defs.tsv")"
  local idpolicy; idpolicy="$(jq -r '.id_policy // "keep"' "$pack/pack.json" 2>/dev/null || echo keep)"
  jq -n --slurpfile items "$tmpd/items.jsonl" --argjson reqs "$reqs" --arg feature "$feature" --arg re "$re" --arg policy "$idpolicy" \
        --arg dups "$dups" --arg undef "$undefined" --argjson lw "$SLICE_LINES_WARN" --argjson tw "$SLICE_TOKENS_WARN" '
    ($items | map(select(.kind=="slice")) | sort_by(.file)) as $slices
    | ($items | map(select(.kind=="cross")) | sort_by(.file)) as $cross
    | { schema_version:1, feature:$feature, id_policy:$policy, id_regex:$re,
        slices:$slices, cross_cutting:$cross, requirements:$reqs,
        totals:{ slices:($slices|length), requirements:($reqs|length), lines:(($slices+$cross)|map(.lines)|add // 0) },
        errors: ( ($dups | split("\n") | map(select(length>0) | "requirement defined more than once: " + .)) ),
        warnings: ( ($slices | map(select(.lines > $lw or .approx_tokens > $tw) | "slice \(.slug) is large (\(.lines) lines, ~\(.approx_tokens) tokens); consider splitting it"))
                  + ($slices | map(select((.requirement_ids|length)==0) | "slice \(.slug) defines no requirement IDs"))
                  + ($undef | split("\n") | map(select(length>0) | "referenced but never defined: " + .)) ) }' > "$out"
  rm -rf "$tmpd"
}
cmd_build() {
  local feature=""; while [[ $# -gt 0 ]]; do case "$1" in --feature) feature="${2:-}"; shift 2 ;; *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"
  local tmp; tmp="$(mktemp)"; compute_index "$feature" "$tmp"; cp "$tmp" "$pack/index.json"; chmod 644 "$pack/index.json"
  local table; table="$(mktemp)"
  jq -r '
    "| # | Slice | Status | Priority | Requirements | Lines | Depends on | Summary |", "|---|---|---|---|---|---|---|---|",
    ( .slices | to_entries[] | .value as $s | "| \(.key + 1) | [\($s.title // $s.slug)](\($s.file)) | \($s.status) | \($s.priority) | \($s.requirement_ids | length) | \($s.lines) | \($s.depends_on | join(", ")) | \($s.summary) |" )' "$pack/index.json" > "$table"
  [[ -f "$pack/00-index.md" ]] || { fill_tpl "$TPL/requirements-index.md.tmpl" "FEATURE=$feature" "TITLE=$feature" "SOURCE=n/a" | awk '$0=="{{OVERVIEW}}"{print "TODO"; next}{print}' > "$pack/00-index.md"; }
  awk -v tf="$table" '
    /<!-- slices:start/ { print; while ((getline l < tf) > 0) print l; skip=1; next }
    /<!-- slices:end/ { skip=0 }
    !skip { print }' "$pack/00-index.md" > "$tmp" && mv "$tmp" "$pack/00-index.md"; chmod 644 "$pack/00-index.md"
  rm -f "$table"
  jq -r '"Built \(.totals.slices) slices, \(.totals.requirements) requirements, \(.totals.lines) lines. Errors: \(.errors|length)  Warnings: \(.warnings|length)"' "$pack/index.json"
  jq -r '(.errors[] | "  ERROR " + .), (.warnings[] | "  WARN  " + .)' "$pack/index.json"
}
cmd_validate() {
  local feature=""; while [[ $# -gt 0 ]]; do case "$1" in --feature) feature="${2:-}"; shift 2 ;; *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"
  local tmp; tmp="$(mktemp)"; compute_index "$feature" "$tmp"
  local errs=0 warns=0 line
  say_e() { echo "ERROR $*"; errs=$((errs+1)); }; say_w() { echo "WARN  $*"; warns=$((warns+1)); }
  [[ -f "$pack/00-index.md" ]] || say_e "missing 00-index.md"; [[ -f "$pack/pack.json" ]] || say_e "missing pack.json"
  [[ "$(jq '.slices|length' "$tmp")" -gt 0 ]] || say_w "pack has no slices yet"
  while IFS= read -r line; do [[ -n "$line" ]] && say_e "$line"; done < <(jq -r '.errors[]' "$tmp")
  while IFS= read -r line; do [[ -n "$line" ]] && say_w "$line"; done < <(jq -r '.warnings[]' "$tmp")
  while IFS=$'\t' read -r slug file status prio prefix deps; do
    [[ "$status" =~ ^(draft|in-review|approved)$ ]] || say_e "$file: status must be draft | in-review | approved (got '$status')"
    [[ -z "$prio" || "$prio" =~ ^(Must|Should|Could|Won\'t)$ ]] || say_w "$file: priority should be Must | Should | Could | Won't (got '$prio')"
    [[ -n "$prio" ]] || say_w "$file: priority is empty"
    local base; base="$(basename "$file" .md)"; [[ "${base#[0-9][0-9]-}" == "$slug" || "$base" == "$slug" ]] || say_e "$file: filename does not end with the slice slug '$slug'"
    local d; for d in $(echo "$deps" | tr ',' ' '); do [[ -n "$d" ]] && { slice_file "$pack" "$d" >/dev/null || say_e "$file: depends_on unknown slice '$d'"; }; done
  done < <(jq -r '.slices[] | [.slug, .file, .status, .priority, .prefix, (.depends_on|join(" "))] | @tsv' "$tmp")
  local dupslug; dupslug="$(jq -r '[.slices[].slug] | group_by(.) | map(select(length>1)|.[0]) | .[]' "$tmp")"; [[ -z "$dupslug" ]] || say_e "duplicate slice slugs: $dupslug"
  # new-style IDs should carry the slice prefix
  while IFS=$'\t' read -r file prefix ids; do
    [[ -n "$prefix" ]] || continue
    local id; for id in $ids; do [[ "$id" =~ ^(REQ|NFR)-[A-Z][A-Z0-9]*-[0-9]+$ ]] && [[ "$id" != *"-$prefix-"* ]] && say_w "$file: $id does not contain the slice prefix $prefix"; done
  done < <(jq -r '.slices[] | [.file, .prefix, (.requirement_ids|join(" "))] | @tsv' "$tmp")
  if [[ -f "$pack/index.json" ]]; then cmp -s "$pack/index.json" "$tmp" || say_w "index.json is out of date; run: req-index.sh build --feature $feature"; else say_w "index.json missing; run build"; fi
  rm -f "$tmp"
  if [[ $errs -gt 0 ]]; then echo "Pack INVALID: $errs error(s), $warns warning(s)" >&2; return 1; fi
  echo "Pack OK: $warns warning(s)"
}

# ======================================================================================================
# show / stale / to-graph
# ======================================================================================================
cmd_show() {
  local feature="" mode="" arg=""
  while [[ $# -gt 0 ]]; do case "$1" in
    --feature) feature="${2:-}"; shift 2 ;; --index) mode=index; shift ;; --slice) mode=slice; arg="${2:-}"; shift 2 ;; --id) mode=id; arg="${2:-}"; shift 2 ;;
    *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"; [[ -d "$pack" ]] || die "no pack at $(relpath "$pack")"
  [[ -f "$pack/index.json" ]] || cmd_build --feature "$feature" >/dev/null
  case "$mode" in
    index) cat "$pack/00-index.md" ;;
    slice) local f; f="$(slice_file "$pack" "$arg")" || die "unknown slice: $arg"; cat "$f" ;;
    id)
      local file; file="$(jq -r --arg id "$arg" '.requirements[$id].file // empty' "$pack/index.json")"; [[ -n "$file" ]] || die "requirement not found: $arg"
      echo "file: $(relpath "$pack")/$file"; echo "---"
      local re; re="$(pack_re "$pack")"
      body_of "$pack/$file" | awk -v id="$arg" -v RE="$re" '
        { x=$0; sub(/^[ \t|*>#-]+/,"",x); isdef=match(x, "^(" RE ")")
          if (isdef && substr(x,1,RLENGTH)==id) { p=1; n=0 }
          else if (p && (isdef || $0 ~ /^#+ /)) exit
          if (p) { print; if (++n >= 60) exit } }' ;;
    *) die "usage: show --feature SLUG (--index | --slice S | --id REQ-ID)" ;;
  esac
}
cmd_stale() {
  local feature=""; while [[ $# -gt 0 ]]; do case "$1" in --feature) feature="${2:-}"; shift 2 ;; *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"; local state="$ROOT/.sdlc/state.json"
  [[ -f "$state" ]] || { echo "No .sdlc/state.json; nothing to compare."; return 0; }
  local n=0 slug h cur f
  while IFS=$'\t' read -r slug h; do
    [[ -n "$slug" ]] || continue
    if f="$(slice_file "$pack" "$slug")"; then cur="$(hash_file "$f")"
      if [[ "$cur" != "$h" ]]; then echo "STALE  $slug (changed since recorded hash $h; now $cur): re-review design and backlog for this slice"; n=$((n+1)); fi
    else echo "MISSING $slug (slice file no longer exists)"; n=$((n+1)); fi
  done < <(jq -r --arg f "$feature" '(.features[$f].slice_hashes // {}) | to_entries[] | "\(.key)\t\(.value)"' "$state")
  if [[ $n -eq 0 ]]; then echo "All recorded slices are unchanged."; else return 1; fi
}
cmd_to_graph() {
  local feature="" apply=0; while [[ $# -gt 0 ]]; do case "$1" in --feature) feature="${2:-}"; shift 2 ;; --apply) apply=1; shift ;; *) die "unknown option: $1" ;; esac; done
  need_feature "$feature"; local pack; pack="$(pack_dir "$feature")"; cmd_build --feature "$feature" >/dev/null
  local out; out="$(jq -c '
    ( .slices[] | {type:"entity", id:("SLICE-" + .slug), kind:"slice", title:.title, source:.file, status:.status} ),
    ( .requirements | to_entries[] | {type:"entity", id:.key, kind:(if (.key | test("^NFR")) then "nfr" else "requirement" end), title:.value.title, source:.value.file} ),
    ( .slices[] | .slug as $s | .requirement_ids[] | {type:"relation", from:., rel:"part_of", to:("SLICE-" + $s)} ),
    ( .slices[] | .slug as $s | (.depends_on // [])[] | {type:"relation", from:("SLICE-" + $s), rel:"depends_on", to:("SLICE-" + .)} )
    | with_entries(select(.value != ""))' "$pack/index.json")"
  if [[ $apply -eq 1 ]]; then local t; t="$(mktemp)"; printf '%s\n' "$out" > "$t"; bash "$GRAPH_SH" import --file "$t"; rm -f "$t"; else printf '%s\n' "$out"; fi
}

CMD="${1:-}"; shift || true
case "$CMD" in
  analyze) cmd_analyze "$@" ;; skeleton) cmd_skeleton "$@" ;; split) cmd_split "$@" ;;
  init-pack) cmd_init_pack "$@" ;; new-slice) cmd_new_slice "$@" ;;
  build) cmd_build "$@" ;; validate) cmd_validate "$@" ;; show) cmd_show "$@" ;; stale) cmd_stale "$@" ;; to-graph) cmd_to_graph "$@" ;;
  -h|--help|help|"") sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; [[ -n "$CMD" ]] || exit 2 ;;
  *) die "unknown command: $CMD (try --help)" ;;
esac
