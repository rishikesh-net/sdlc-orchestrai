#!/usr/bin/env python3
"""Phase 0 benchmark baseline for the shell -> Python migration.

This is a manual tool (not a unittest). It records baseline timings for the two
hot paths that later phases rewrite, so regressions are obvious:

* ``req-index.sh analyze`` on a synthetic large requirements document.
* ``sarif.py convert`` + ``merge`` over a synthetic batch of scanner findings
  (the Python side of the scanning pipeline).

Usage:
    python scripts/tests/bench_phase0.py [--runs N] [--req-lines N] [--findings N]

The ``req`` benchmark is skipped on Windows and when bash/jq are unavailable. The
``scan`` benchmark is expected to carry over to the Phase 2 ``scan.py`` port.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ_INDEX = ROOT / "skills" / "sdlc-requirements-analyzer" / "scripts" / "req-index.sh"
SARIF_PY = ROOT / "skills" / "sdlc-security-review" / "scripts" / "sarif.py"


def _median(values):
    return statistics.median(values) if values else float("nan")


def _time_runs(runs, func):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        func()
        times.append(time.perf_counter() - start)
    return times


def _make_repo(tmp: Path) -> Path:
    (tmp / "docs" / "requirements").mkdir(parents=True)
    (tmp / "src").mkdir()
    (tmp / "src" / "app.ts").write_text("export const ok = true;\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    return tmp


def _make_big_doc(tmp: Path, target_lines: int) -> Path:
    lines = ["# Large Requirements", "", "## Overview", "", "Synthetic benchmark input.", ""]
    n = 0
    while len(lines) < target_lines:
        n += 1
        lines += [
            f"## Capability {n}",
            "",
            f"- REQ-CAP{n:03d}-001 The system shall support capability {n}.",
            f"- REQ-CAP{n:03d}-002 The system shall report capability {n} errors clearly.",
            f"- NFR-CAP{n:03d}-001 Capability {n} shall respond within 300 ms.",
            "",
        ]
    doc = tmp / "docs" / "requirements" / "big.md"
    doc.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return doc


def bench_req(tmp: Path, runs: int, target_lines: int) -> None:
    if os.name == "nt" or shutil.which("bash") is None or shutil.which("jq") is None:
        print("[req] skipped (POSIX bash + jq required)")
        return
    _make_big_doc(tmp, target_lines)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = ["bash", str(REQ_INDEX), "analyze", "--file", "docs/requirements/big.md", "--json"]

    def run():
        proc = subprocess.run(cmd, cwd=str(tmp), capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise SystemExit(f"[req] failed: {proc.stderr}")
        json.loads(proc.stdout)

    times = _time_runs(runs, run)
    print(
        f"[req] analyze  runs={runs}  median={_median(times):.3f}s  "
        f"min={min(times):.3f}s"
    )


def bench_scan(tmp: Path, runs: int, findings: int) -> None:
    out = tmp / ".sdlc" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    tsv = out / "bench-sast.tsv"
    rows = []
    for i in range(findings):
        rows.append(
            f"heuristic-sast.bench\tfile{i % 50}.ts\t{i + 1}\tmedium\tSynthetic finding {i}"
        )
    tsv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def run():
        subprocess.run(
            [
                sys.executable, str(SARIF_PY), "convert", "--type", "lines",
                "--input", str(tsv), "--scanner", "heuristic-sast",
                "--feature", "bench", "--out-dir", str(out),
                "--status", "fallback", "--root", str(tmp),
            ],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [
                sys.executable, str(SARIF_PY), "merge",
                "--feature", "bench", "--out-dir", str(out),
            ],
            check=True, capture_output=True, text=True,
        )

    times = _time_runs(runs, run)
    print(
        f"[scan] convert+merge findings={findings} runs={runs}  "
        f"median={_median(times):.3f}s  min={min(times):.3f}s"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Phase 0 benchmark baseline")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--req-lines", type=int, default=400)
    parser.add_argument("--findings", type=int, default=500)
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="sdlc-bench-") as raw:
        tmp = _make_repo(Path(raw))
        bench_req(tmp, args.runs, args.req_lines)
        bench_scan(tmp, args.runs, args.findings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
