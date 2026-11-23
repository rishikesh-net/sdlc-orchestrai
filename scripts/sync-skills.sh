#!/usr/bin/env bash
# sync-skills.sh - publish canonical skills/ to each client's folder.
#   Claude Code -> .claude/skills/        Copilot / VS Code -> .github/skills/
#   OpenCode    -> .opencode/skills/      (OpenCode also reads .claude/skills/ as a fallback)
#   Antigravity -> .agent/skills/         (IDE/client project-level skills)
#   Extra targets: SDLC_SYNC_EXTRA="path1 path2" (relative to repo root), e.g. .agents/skills for the
#   Antigravity SDK/CLI wrappers that use the .agents/ folder.
#   Cursor      -> .cursor/rules/*.mdc    (stubs that point at skills/<name>/SKILL.md)
# Usage: scripts/sync-skills.sh          copy/generate
#        scripts/sync-skills.sh --check  exit 1 if any copy has drifted (use in CI)
# Verify folder names against each client's current docs; they change between releases.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/skills"
CHECK=0; [[ "${1:-}" == "--check" ]] && CHECK=1
DRIFT=0

gen_cursor_rules() { # $1 = output dir
  mkdir -p "$1"
  for dir in "$SRC"/*/; do
    name="$(basename "$dir")"
    desc="$(sed -n '/^description:/{s/^description:[[:space:]]*//;p;q}' "$dir/SKILL.md" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    cat > "$1/$name.mdc" <<MDC
---
description: "$desc"
alwaysApply: false
---
Follow the skill defined in \`skills/$name/SKILL.md\` (read it fully, plus any files it references
in \`references/\`, \`templates/\`, and \`scripts/\`). Shared rules and approval gates: @AGENTS.md
MDC
  done
}

sync_dir() { # $1 = target dir
  if [[ $CHECK -eq 1 ]]; then
    if ! diff -rq "$SRC" "$1" >/dev/null 2>&1; then echo "DRIFT: $1 differs from skills/"; DRIFT=1; fi
  else
    rm -rf "$1"; mkdir -p "$(dirname "$1")"; cp -R "$SRC" "$1"; echo "synced -> ${1#$ROOT/}"
  fi
}

sync_dir "$ROOT/.claude/skills"
sync_dir "$ROOT/.github/skills"
sync_dir "$ROOT/.opencode/skills"
sync_dir "$ROOT/.agent/skills"
for extra in ${SDLC_SYNC_EXTRA:-}; do sync_dir "$ROOT/$extra"; done

if [[ $CHECK -eq 1 ]]; then
  tmp="$(mktemp -d)"; gen_cursor_rules "$tmp"
  if ! diff -rq "$tmp" "$ROOT/.cursor/rules" >/dev/null 2>&1; then echo "DRIFT: .cursor/rules differs from generated stubs"; DRIFT=1; fi
  rm -rf "$tmp"
  [[ $DRIFT -eq 0 ]] && echo "All client copies are in sync." || { echo "Run scripts/sync-skills.sh and commit."; exit 1; }
else
  gen_cursor_rules "$ROOT/.cursor/rules"; echo "generated -> .cursor/rules/*.mdc"
fi
