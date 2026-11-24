#!/usr/bin/env bash
# common.sh - shared helpers for backlog tracker adapters. Sourced by push/pull scripts.
# Not executed directly.
#
# Tracker selection precedence: --tracker <name> > SDLC_TRACKER > .sdlc/config.yaml
# (top-level `tracker:`) > github.

BL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BL_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
BL_CONFIG="$BL_ROOT/.sdlc/config.yaml"
BL_TRACKER_ARG=""

bl_die() { echo "ERROR: $*" >&2; exit 2; }
bl_warn() { echo "WARN: $*" >&2; }

bl_cfg() { # key -> first "key: value" line in config.yaml (keys must be unique across sections)
  [[ -f "$BL_CONFIG" ]] || return 0
  sed -nE "s/^[[:space:]]*$1:[[:space:]]*\"?([^\"#]*)\"?[[:space:]]*(#.*)?$/\1/p" "$BL_CONFIG" \
    | head -1 | sed -E 's/[[:space:]]+$//'
}

bl_tracker() { # selected tracker name
  local t="${BL_TRACKER_ARG:-${SDLC_TRACKER:-$(bl_cfg tracker)}}"
  printf '%s' "${t:-github}"
}

bl_require_jq() { command -v jq >/dev/null 2>&1 || bl_die "jq is required"; }

# Windows jq emits CRLF; strip CR so ids, titles, labels, and loop values stay clean.
bl_jqr() { jq -r "$@" | tr -d '\r'; }
bl_jqc() { jq -c "$@" | tr -d '\r'; }

bl_load_adapter() { # tracker -> sources adapters/<tracker>.sh and sets ADAPTER_NAME
  local tracker="$1" avail
  BL_ADAPTER_FILE="$BL_SCRIPT_DIR/adapters/$tracker.sh"
  if [[ ! -f "$BL_ADAPTER_FILE" ]]; then
    avail="$(cd "$BL_SCRIPT_DIR/adapters" 2>/dev/null && ls -1 *.sh 2>/dev/null \
      | sed -E 's/\.sh$//' | grep -v '^common$' | tr '\n' ' ')"
    bl_die "Unknown or unsupported tracker '$tracker'. Available adapters: ${avail:-none}"
  fi
  # shellcheck disable=SC1090
  source "$BL_ADAPTER_FILE"
  [[ -n "${ADAPTER_NAME:-}" ]] || bl_die "Adapter $tracker did not set ADAPTER_NAME"
}

bl_truthy() { [[ "${1:-}" == "1" || "${1:-}" == "true" || "${1:-}" == "yes" ]]; }
