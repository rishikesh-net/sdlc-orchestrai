"""Shared helpers for SDLCOrchestrAI Python tools (standard library only)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Return the repository root for *start* (default: current directory)."""
    env_root = os.environ.get("SDLC_REPO_ROOT")
    if env_root:
        return Path(env_root).resolve()

    base = Path(start or Path.cwd()).resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass

    current = base
    while True:
        if (current / ".git").exists() or (current / ".sdlc").exists():
            return current
        if current == current.parent:
            break
        current = current.parent
    return Path.cwd().resolve()


def parse_simple_yaml(path: Path) -> Dict[str, Any]:
    """Lightweight YAML parser for key-value and nested maps without PyYAML."""
    if not path.is_file():
        return {}
    data: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, data)]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("- "):
                    continue
                if " #" in line:
                    line = line.split(" #", 1)[0].strip()
                if ":" not in line:
                    continue
                indent = len(raw_line) - len(raw_line.lstrip(" \t"))
                while len(stack) > 1 and indent <= stack[-1][0]:
                    stack.pop()
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                target = stack[-1][1]
                if value == "":
                    child: Dict[str, Any] = {}
                    target[key] = child
                    stack.append((indent, child))
                else:
                    target[key] = value
        return data
    except OSError:
        return {}
