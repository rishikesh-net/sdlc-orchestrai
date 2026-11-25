#!/usr/bin/env bash
# sdlc-state.sh - thin compatibility shim delegating to scripts/sdlc.py.
# Kept so existing CI/docs invocations continue to work; canonical logic lives in scripts/sdlc.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "import sys" >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1 && python -c "import sys" >/dev/null 2>&1; then
  PY="python"
else
  echo "ERROR: Python 3 is required to run sdlc-state.sh" >&2
  exit 1
fi

exec "$PY" "$ROOT/scripts/sdlc.py" "$@"
