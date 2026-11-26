"""Contract test for the merged scanner report produced by scan.py.

Runs with every configurable scanner disabled so the test is deterministic and
does not depend on which external tools are installed. It exercises config
loading, per-scanner skip records, report merging, and SARIF validity.

Runs on Windows, macOS, and Linux (git is the only requirement).
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
SCAN_PY = ROOT / "skills" / "sdlc-security-review" / "scripts" / "scan.py"
SARIF_PY = ROOT / "skills" / "sdlc-security-review" / "scripts" / "sarif.py"

DISABLED_CONFIG = """\
tracker: local
security:
  strict: false
  scanners:
    gitleaks: disabled
    trufflehog: disabled
    semgrep: disabled
    trivy: disabled
    osv_scanner: disabled
    zizmor: disabled
    dotnet: disabled
    npm_audit: disabled
    roslyn: disabled
    eslint_sdl: disabled
    squawk: disabled
"""

SKIPPED_SCANNERS = {"semgrep", "dotnet", "npm-audit", "osv-scanner", "trivy"}
SECRETS_SCANNERS = {"gitleaks", "trufflehog", "heuristic-secrets"}
ALLOWED_STATUSES = {"ran", "fallback", "skipped"}


@unittest.skipIf(shutil.which("git") is None, "git is required")
class ScanAllContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-scan-all-"))
        (self.tmp / ".sdlc").mkdir()
        (self.tmp / ".sdlc" / "config.yaml").write_text(DISABLED_CONFIG, encoding="utf-8")
        (self.tmp / "src").mkdir()
        (self.tmp / "src" / "app.ts").write_text("export const ok = true;\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merged_report_contract_with_scanners_disabled(self):
        env = os.environ.copy()
        env["SDLC_SCAN_ROOT"] = str(self.tmp)
        env["PYTHONIOENCODING"] = "utf-8"
        for key in ("SDLC_STRICT", "SDLC_FEATURE"):
            env.pop(key, None)

        proc = subprocess.run(
            [sys.executable, str(SCAN_PY), "all", "--feature", "contract"],
            cwd=str(self.tmp), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        reports = self.tmp / ".sdlc" / "reports"
        findings_path = reports / "contract-findings.json"
        sarif_path = reports / "contract-findings.sarif"
        self.assertTrue(findings_path.is_file(), proc.stdout + proc.stderr)
        self.assertTrue(sarif_path.is_file())

        data = json.loads(findings_path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["feature"], "contract")
        self.assertIsInstance(data["findings"], list)

        by_name = {scanner["name"]: scanner for scanner in data["scanners"]}
        self.assertTrue(set(by_name), "expected at least one scanner record")

        # A secrets scanner always runs (tool or regex fallback).
        self.assertTrue(SECRETS_SCANNERS & set(by_name), sorted(by_name))
        # Every configured-but-disabled scanner is recorded as skipped.
        for name in SKIPPED_SCANNERS:
            self.assertIn(name, by_name)
            self.assertEqual(by_name[name]["status"], "skipped")
        for name, scanner in by_name.items():
            self.assertIn(scanner["status"], ALLOWED_STATUSES, name)

        # The merged SARIF is structurally valid 2.1.0.
        valid = subprocess.run(
            [sys.executable, str(SARIF_PY), "validate", str(sarif_path)],
            capture_output=True, text=True,
        )
        self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)


if __name__ == "__main__":
    unittest.main()
