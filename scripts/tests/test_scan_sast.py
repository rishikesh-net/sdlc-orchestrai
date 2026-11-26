"""Tests for the heuristic SAST fallback in scan.py.

Verifies that the app-source allowlist and the case-sensitive SQL rule avoid
tooling noise. Runs on Windows, macOS, and Linux (git is the only requirement).
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECURITY_DIR = ROOT / "skills" / "sdlc-security-review" / "scripts"
sys.path.insert(0, str(SECURITY_DIR))

import scan  # noqa: E402


@unittest.skipIf(shutil.which("git") is None, "git is required")
class HeuristicSastScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-sast-"))
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "app.ts").write_text(
            'export function q(id: string) {\n'
            '  return "SELECT * FROM users WHERE id = " + id;\n'
            '}\n',
            encoding="utf-8",
        )
        # Lowercase select(...) and jq-style concatenation must not match the case-sensitive SQL rule.
        (self.tmp / "src" / "ui.ts").write_text(
            'const picked = "select " + value;\n'
            'const other = items.select(0) + 1;\n',
            encoding="utf-8",
        )
        # Shell/tooling code is outside the SAST allowlist (secrets scanning still covers it).
        (self.tmp / "tool.sh").write_text(
            'jq \'select(.a) + 1\' file\n'
            'msg="referenced " + .\n',
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

        self._saved = (scan.ROOT, scan.OUT, scan.FEATURE, scan.STRICT, scan.CFG)
        scan.ROOT = self.tmp
        scan.OUT = self.tmp / ".sdlc" / "reports"
        scan.OUT.mkdir(parents=True, exist_ok=True)
        scan.FEATURE = "scope"
        scan.STRICT = False
        scan.CFG = {"strict": False, "scanners": {}}

    def tearDown(self):
        scan.ROOT, scan.OUT, scan.FEATURE, scan.STRICT, scan.CFG = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_app_source_sql_concat_is_reported(self):
        findings = scan.heuristic_sast()

        sql = [f for f in findings if f["rule"] == "heuristic-sast.sql-concat"]
        self.assertEqual(len(sql), 1, findings)
        self.assertEqual(sql[0]["file"], "src/app.ts")
        self.assertEqual(sql[0]["line"], 2)
        self.assertEqual(sql[0]["severity"], "medium")

        files = {f["file"] for f in findings}
        self.assertNotIn("src/ui.ts", files, findings)
        self.assertNotIn("tool.sh", files, findings)

        scan.emit("heuristic-sast", findings, "fallback")
        report = json.loads((scan.OUT / "scope-heuristic-sast.json").read_text(encoding="utf-8"))
        self.assertEqual(report["scanner"], "heuristic-sast")
        self.assertEqual(report["status"], "fallback")
        self.assertEqual(len(report["findings"]), len(findings))


if __name__ == "__main__":
    unittest.main()
