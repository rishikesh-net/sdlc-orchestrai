"""Tests for skills/sdlc-security-review/scripts/sarif.py (stdlib unittest, no deps).

Run from the repo root:
  python -m unittest discover -s scripts/tests -v
"""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SARIF_DIR = ROOT / "skills" / "sdlc-security-review" / "scripts"
SARIF_PY = SARIF_DIR / "sarif.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SARIF_DIR))

import sarif  # noqa: E402  (path set up above)


def load_fixture(name: str):
    with open(FIXTURES / name, "r", encoding="utf-8") as f:
        return json.load(f)


class SeverityTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(sarif.normalize_severity("ERROR"), "high")
        self.assertEqual(sarif.normalize_severity("WARNING"), "medium")
        self.assertEqual(sarif.normalize_severity("moderate"), "medium")
        self.assertEqual(sarif.normalize_severity("note"), "low")
        self.assertEqual(sarif.normalize_severity(None), "info")
        self.assertEqual(sarif.normalize_severity("bogus"), "info")

    def test_sarif_levels(self):
        self.assertEqual(sarif.SEVERITY_TO_LEVEL["critical"], "error")
        self.assertEqual(sarif.SEVERITY_TO_LEVEL["medium"], "warning")
        self.assertEqual(sarif.SEVERITY_TO_LEVEL["info"], "note")


class ConverterTests(unittest.TestCase):
    def test_semgrep(self):
        findings = sarif.from_semgrep(load_fixture("semgrep.json"), "semgrep", Path("/repo"))
        self.assertEqual(len(findings), 2)
        first = findings[0]
        self.assertEqual(first["severity"], "high")
        self.assertEqual(first["rule"], "semgrep.javascript.express.security.audit.xss")
        self.assertEqual(first["file"], "src/app.ts")
        self.assertEqual(first["line"], 42)
        self.assertEqual(findings[1]["severity"], "medium")

    def test_gitleaks_never_copies_secret(self):
        findings = sarif.from_gitleaks(load_fixture("gitleaks.json"), "gitleaks", Path("D:/repo"))
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["severity"], "high")
        self.assertIn("value redacted", findings[0]["message"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            sarif.write_scanner_outputs(out, "demo", "gitleaks", findings, "ran")
            for name in ("demo-gitleaks.json", "demo-gitleaks.sarif"):
                text = (out / name).read_text(encoding="utf-8")
                self.assertNotIn("CANARY", text)
                self.assertNotIn("CANARY_DO_NOT_LEAK", text)

    def test_npm_audit(self):
        findings = sarif.from_npm_audit(load_fixture("npm-audit.json"), "npm-audit", None, "web/package.json")
        self.assertEqual(len(findings), 2)
        by_rule = {f["rule"]: f for f in findings}
        self.assertEqual(by_rule["npm.lodash"]["severity"], "high")
        self.assertIn("4.17.21", by_rule["npm.lodash"]["remediation"])
        self.assertEqual(by_rule["npm.left-pad"]["severity"], "medium")

    def test_dotnet(self):
        findings = sarif.from_dotnet(load_fixture("dotnet.json"), "dotnet", None)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "nuget.Newtonsoft.Json")
        self.assertEqual(findings[0]["severity"], "high")
        self.assertTrue(findings[0]["file"].endswith("Api/Api.csproj"))

    def test_trufflehog(self):
        raw = "\n".join([
            json.dumps({
                "DetectorName": "AWS",
                "SourceMetadata": {"Data": {"Filesystem": {"file": "config/aws.json", "line": 5}}},
            }),
            "not json",
        ])
        findings = sarif.from_trufflehog(raw, "trufflehog", None)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "trufflehog.AWS")
        self.assertEqual(findings[0]["severity"], "high")
        self.assertNotIn("AKIA", json.dumps(findings))

    def test_lines(self):
        text = (FIXTURES / "hits.tsv").read_text(encoding="utf-8")
        findings = sarif.from_lines(text, "heuristic-sast", None)
        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0]["confidence"], "needs-verification")
        self.assertEqual(findings[0]["line"], 12)


class MergeTests(unittest.TestCase):
    def test_merge_dedupes_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            semgrep_findings = sarif.from_semgrep(load_fixture("semgrep.json"), "semgrep", Path("/repo"))
            sarif.write_scanner_outputs(out, "demo", "semgrep", semgrep_findings, "ran", "1.2.3")
            # Duplicate the same finding under the same scanner to prove dedupe.
            sarif.write_scanner_outputs(out, "demo", "semgrep", semgrep_findings, "ran", "1.2.3")
            sarif.write_scanner_outputs(
                out, "demo", "heuristic-sast",
                sarif.from_lines((FIXTURES / "hits.tsv").read_text(encoding="utf-8"), "heuristic-sast", None),
                "fallback",
            )

            combined = sarif.merge_feature(out, "demo")
            self.assertEqual(len(combined["findings"]), 5)
            self.assertEqual([s["name"] for s in combined["scanners"]], ["heuristic-sast", "semgrep"])
            self.assertEqual(
                [s["status"] for s in combined["scanners"]], ["fallback", "ran"])

            sarif_path = out / "demo-findings.sarif"
            self.assertTrue(sarif_path.is_file())
            with redirect_stdout(io.StringIO()) as buf:
                rc = sarif.validate_sarif(sarif_path)
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertIn("OK:", buf.getvalue())

    def test_validate_rejects_broken_sarif(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.sarif"
            bad.write_text(json.dumps({"version": "1.0", "runs": []}), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(sarif.validate_sarif(bad), 1)

    def test_merge_ignores_raw_tool_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "demo-npm.raw.raw.json").write_text(
                json.dumps(load_fixture("npm-audit.json")), encoding="utf-8")
            combined = sarif.merge_feature(out, "demo")
            self.assertEqual(combined["findings"], [])
            self.assertEqual(combined["scanners"], [])

    def test_feature_slug(self):
        self.assertEqual(sarif.feature_slug(""), "repo")
        self.assertEqual(sarif.feature_slug("a  b/c"), "a--b-c")

    def test_append_keeps_prior_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            first = sarif.from_npm_audit(load_fixture("npm-audit.json"), "npm-audit", None, "web/package.json")
            sarif.write_scanner_outputs(out, "demo", "npm-audit", first[:1], "ran")
            second = sarif.from_dotnet(load_fixture("dotnet.json"), "dotnet", None)
            rc = sarif.main([
                "convert", "--type", "dotnet", "--input", str(FIXTURES / "dotnet.json"),
                "--scanner", "dotnet", "--feature", "demo", "--out-dir", str(out),
                "--status", "ran", "--append",
            ])
            self.assertEqual(rc, 0)
            combined = sarif.merge_feature(out, "demo")
            rules = {f["rule"] for f in combined["findings"]}
            self.assertIn("npm.lodash", rules)
            self.assertIn("nuget.Newtonsoft.Json", rules)
            self.assertGreaterEqual(len(second), 1)


class CliTests(unittest.TestCase):
    def test_convert_merge_count_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            base = [sys.executable, str(SARIF_PY)]
            conv = subprocess.run(
                base + ["convert", "--type", "semgrep", "--input", str(FIXTURES / "semgrep.json"),
                        "--scanner", "semgrep", "--feature", "cli", "--out-dir", str(out),
                        "--status", "ran", "--root", "/repo"],
                capture_output=True, text=True)
            self.assertEqual(conv.returncode, 0, conv.stderr)

            merged = subprocess.run(
                base + ["merge", "--feature", "cli", "--out-dir", str(out)],
                capture_output=True, text=True)
            self.assertEqual(merged.returncode, 0, merged.stderr)

            count = subprocess.run(
                base + ["count", "--feature", "cli", "--out-dir", str(out)],
                capture_output=True, text=True)
            self.assertEqual(count.stdout.strip(), "2")

            valid = subprocess.run(
                base + ["validate", str(out / "cli-findings.sarif")],
                capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)


if __name__ == "__main__":
    unittest.main()
