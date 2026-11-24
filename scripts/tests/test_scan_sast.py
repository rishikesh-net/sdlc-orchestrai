"""Integration test for the heuristic SAST fallback scope.

Runs on POSIX (CI). Skipped on Windows because the scanner expects a bash-native path.
Verifies that app-source allowlisting and the case-sensitive SQL rule avoid tooling noise.
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
SCAN_SAST = ROOT / "skills" / "sdlc-security-review" / "scripts" / "scan-sast.sh"


@unittest.skipIf(os.name == "nt", "scanner integration test requires POSIX bash paths")
@unittest.skipIf(shutil.which("bash") is None, "bash is not available")
@unittest.skipIf(shutil.which("git") is None, "git is not available")
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

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_only_app_source_sql_concat_is_reported(self):
        env = os.environ.copy()
        env["SDLC_SCAN_ROOT"] = str(self.tmp)
        env["SDLC_PYTHON"] = sys.executable
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            ["bash", str(SCAN_SAST), "--feature", "scope"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        findings_path = self.tmp / ".sdlc" / "reports" / "scope-findings.json"
        sarif_path = self.tmp / ".sdlc" / "reports" / "scope-findings.sarif"
        self.assertTrue(findings_path.is_file(), proc.stderr)
        self.assertTrue(sarif_path.is_file())

        data = json.loads(findings_path.read_text(encoding="utf-8"))
        self.assertEqual([s["name"] for s in data["scanners"]], ["heuristic-sast"])
        self.assertEqual(data["scanners"][0]["status"], "fallback")

        sql = [f for f in data["findings"] if f["rule"] == "heuristic-sast.sql-concat"]
        self.assertEqual(len(sql), 1, data["findings"])
        self.assertEqual(sql[0]["file"], "src/app.ts")
        self.assertEqual(sql[0]["line"], 2)
        self.assertEqual(sql[0]["severity"], "medium")

        files = {f["file"] for f in data["findings"]}
        self.assertNotIn("src/ui.ts", files, data["findings"])
        self.assertNotIn("tool.sh", files, data["findings"])


if __name__ == "__main__":
    unittest.main()
