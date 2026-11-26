"""Differential test harness for the shell -> Python migration (Phase 0).

The migration ports bash/jq scripts to Python. To prove parity, tests can run the
current implementation and the new implementation and compare normalized output.

Select the implementation with the ``SDLC_IMPL`` environment variable:

* ``shell`` (default): run the shell command only.
* ``python``: run the Python command only (fails if none is registered yet).
* ``shadow``: run both, normalize, and require identical exit code + stdout.

Commands are argument lists (never ``shell=True``) so quoting and paths behave the
same on Windows, macOS, and Linux.

Example (later phases)::

    from _diff_harness import compare, normalize_json_text

    compare(
        ["python", "skills/sdlc-requirements-analyzer/scripts/req_index.py",
         "analyze", "--file", "docs/requirements/sample.md", "--json"],
        [sys.executable, "scripts/sdlc.py", "req", "analyze",
         "--file", "docs/requirements/sample.md", "--json"],
        normalize=normalize_json_text,
        label="req analyze",
    )
"""

from __future__ import annotations

import dataclasses
import difflib
import json
import os
import re
import subprocess
from typing import Any, Callable, Dict, Iterable, Optional, Sequence

VALID_MODES = ("python", "shell", "shadow")
DEFAULT_MODE = "shell"

VOLATILE_KEYS = frozenset({
    "startTime",
    "endTime",
    "invocationId",
    "guid",
    "versionControlProvenance",
    "artifactLocationUri",
})


class HarnessError(RuntimeError):
    """Configuration/usage error in the harness."""


class DiffMismatch(HarnessError):
    """The shell and Python implementations produced different results."""


@dataclasses.dataclass(frozen=True)
class RunResult:
    label: str
    cmd: Sequence[str]
    code: int
    stdout: str
    stderr: str


def impl_mode() -> str:
    """Return the selected implementation mode (validated)."""
    mode = os.environ.get("SDLC_IMPL", DEFAULT_MODE).strip().lower()
    if mode not in VALID_MODES:
        raise HarnessError(f"SDLC_IMPL must be one of {VALID_MODES}, got {mode!r}")
    return mode


def run_cmd(
    label: str,
    cmd: Sequence[str],
    cwd: Optional[os.PathLike] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 600,
) -> RunResult:
    """Run *cmd* without a shell and capture text output."""
    proc = subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return RunResult(label, list(cmd), proc.returncode, proc.stdout, proc.stderr)


def normalize_text(text: str, roots: Iterable[os.PathLike] = ()) -> str:
    """Normalize line endings, slashes, temp roots, and trailing whitespace."""
    out = text.replace("\r\n", "\n").replace("\r", "\n").replace("\\", "/")
    for root in roots:
        value = str(root).replace("\\", "/").rstrip("/")
        if value:
            out = out.replace(value, "<ROOT>")
    out = "\n".join(line.rstrip() for line in out.split("\n"))
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _normalize_json_value(value: Any, drop_keys: Iterable[str]) -> Any:
    drop = set(drop_keys)
    if isinstance(value, dict):
        return {
            key: _normalize_json_value(val, drop)
            for key, val in sorted(value.items())
            if key not in drop
        }
    if isinstance(value, list):
        return [_normalize_json_value(item, drop) for item in value]
    return value


def normalize_json_text(text: str, drop_keys: Iterable[str] = VOLATILE_KEYS) -> str:
    """Parse JSON, drop volatile fields, and re-serialize with sorted keys."""
    return json.dumps(
        _normalize_json_value(json.loads(text), drop_keys),
        sort_keys=True,
        indent=2,
    )


def _unified_diff(shell_text: str, python_text: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            shell_text.splitlines(keepends=True),
            python_text.splitlines(keepends=True),
            fromfile=f"{label}:shell",
            tofile=f"{label}:python",
        )
    )


def compare(
    shell_cmd: Sequence[str],
    python_cmd: Optional[Sequence[str]],
    cwd: Optional[os.PathLike] = None,
    env: Optional[Dict[str, str]] = None,
    normalize: Optional[Callable[[str], str]] = None,
    label: str = "command",
    compare_stderr: bool = False,
    timeout: int = 600,
) -> RunResult:
    """Run the selected implementation(s) and compare results in shadow mode.

    Returns the result of the implementation that should be treated as canonical
    (shell for ``shell``/``shadow``, python for ``python``).
    """
    mode = impl_mode()
    normalizer = normalize or normalize_text

    if mode == "shell":
        return run_cmd("shell", shell_cmd, cwd=cwd, env=env, timeout=timeout)

    if python_cmd is None:
        raise HarnessError(
            f"{label}: no Python command is registered yet (SDLC_IMPL={mode})"
        )
    python_result = run_cmd("python", python_cmd, cwd=cwd, env=env, timeout=timeout)
    if mode == "python":
        return python_result

    shell_result = run_cmd("shell", shell_cmd, cwd=cwd, env=env, timeout=timeout)
    if shell_result.code != python_result.code:
        raise DiffMismatch(
            f"{label}: exit code differs "
            f"(shell={shell_result.code}, python={python_result.code})\n"
            f"--- shell stderr ---\n{shell_result.stderr}\n"
            f"--- python stderr ---\n{python_result.stderr}"
        )

    shell_out = normalizer(shell_result.stdout)
    python_out = normalizer(python_result.stdout)
    if shell_out != python_out:
        raise DiffMismatch(
            f"{label}: stdout differs after normalization\n"
            + _unified_diff(shell_out, python_out, label)
        )

    if compare_stderr:
        shell_err = normalizer(shell_result.stderr)
        python_err = normalizer(python_result.stderr)
        if shell_err != python_err:
            raise DiffMismatch(
                f"{label}: stderr differs after normalization\n"
                + _unified_diff(shell_err, python_err, label)
            )

    return shell_result


def assert_same(**kwargs: Any) -> RunResult:
    """Alias for :func:`compare` with an intention-revealing name."""
    return compare(**kwargs)
