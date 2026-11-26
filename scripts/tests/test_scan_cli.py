"""Contract test for `python scripts/sdlc.py scan --only ...` delegation.

Ensures the CLI loads the Python scanner module in-process and honors the target
repo's `.sdlc/config.yaml` (no bash). Runs on Windows, macOS, and Linux.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDLC_PY = ROOT / "scripts" / "sdlc.py"

CONFIG = """\
tracker: local
security:
  strict: false
  scanners:
    trivy: disabled
"""


@unittest.skipIf(shutil.which("git") is None, "git is required")
class ScanCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-scan-cli-"))
        (self.tmp / ".sdlc").mkdir()
        (self.tmp / ".sdlc" / "config.yaml").write_text(CONFIG, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_iac_records_skipped_without_bash(self):
        env = os.environ.copy()
        env["SDLC_SCAN_ROOT"] = str(self.tmp)
        env["PYTHONIOENCODING"] = "utf-8"
        for key in ("SDLC_STRICT", "SDLC_FEATURE"):
            env.pop(key, None)

        proc = subprocess.run(
            [sys.executable, str(SDLC_PY), "scan", "--only", "iac", "--feature", "cli"],
            cwd=str(ROOT), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        report = self.tmp / ".sdlc" / "reports" / "cli-findings.json"
        self.assertTrue(report.is_file(), proc.stdout + proc.stderr)
        data = json.loads(report.read_text(encoding="utf-8"))
        scanners = {s["name"]: s["status"] for s in data["scanners"]}
        self.assertEqual(scanners.get("trivy"), "skipped")


if __name__ == "__main__":
    unittest.main()
