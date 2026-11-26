"""Contract tests for the requirements pack CLI (req_index.py).

Behavioral baselines for analyze, skeleton, split, build, validate, show, stale,
init-pack, and new-slice. Runs on Windows, macOS, and Linux (git only).

Run: python -m unittest discover -s scripts/tests -v
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
SCRIPT = ROOT / "skills" / "sdlc-requirements-analyzer" / "scripts" / "req_index.py"
SDLC_PY = ROOT / "scripts" / "sdlc.py"

SAMPLE_REQUIREMENTS = """\
# Sample Requirements

## Overview

This document captures the notification preferences feature.

## Notifications

REQ-NOTIF-001 The system shall let a signed-in user choose which email notifications they receive.

REQ-NOTIF-002 The system shall send an email when a notification preference is enabled.

- Given a user, When they disable marketing email, Then no marketing email is sent.

## Security

NFR-SEC-001 All preference data shall be encrypted at rest.

NFR-SEC-002 Preference changes shall be recorded in the audit log.

## Glossary

| Term | Meaning |
|---|---|
| Notification | A message sent to a user. |
"""


@unittest.skipIf(shutil.which("git") is None, "git is required")
class ReqIndexContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-req-"))
        (self.tmp / "docs" / "requirements").mkdir(parents=True)
        self.sample = self.tmp / "docs" / "requirements" / "sample.md"
        self.sample.write_text(SAMPLE_REQUIREMENTS, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_req(self, *args, expect: int = 0):
        env = os.environ.copy()
        env.pop("SDLC_REQ_DIR", None)
        env.pop("SDLC_REQ_ROOT", None)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=str(self.tmp), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc

    def test_analyze_json_reports_ids_and_single_file_recommendation(self):
        proc = self.run_req("analyze", "--file", "docs/requirements/sample.md", "--json")
        data = json.loads(proc.stdout)
        self.assertTrue(data["file"].endswith("docs/requirements/sample.md"))
        self.assertEqual(data["ids"]["distinct"], 4)
        self.assertEqual(data["estimated_requirements"], 4)
        self.assertEqual(data["recommendation"], "single-file")
        self.assertGreater(data["lines"], 10)
        titles = [item["title"] for item in data["outline"]]
        self.assertIn("Notifications", titles)
        self.assertIn("Security", titles)

    def test_skeleton_split_build_validate_show_stale(self):
        plan = "docs/requirements/demo.split-plan.json"
        proc = self.run_req(
            "skeleton", "--file", "docs/requirements/sample.md",
            "--feature", "demo", "--title", "Demo", "--out", plan,
        )
        self.assertTrue((self.tmp / plan).is_file(), proc.stdout + proc.stderr)
        plan_data = json.loads((self.tmp / plan).read_text(encoding="utf-8"))
        self.assertEqual(plan_data["feature"], "demo")
        self.assertEqual(plan_data["source"], "docs/requirements/sample.md")
        self.assertEqual(len(plan_data["slices"]), 1)
        self.assertEqual(plan_data["slices"][0]["slug"], "notifications")

        proc = self.run_req("split", "--plan", plan, "--dry-run")
        self.assertIn("Unassigned non-blank lines: 0", proc.stdout)
        self.assertIn("Dry run complete. Nothing written.", proc.stdout)
        self.assertFalse((self.tmp / "docs" / "requirements" / "demo").exists())

        self.run_req("split", "--plan", plan)
        pack = self.tmp / "docs" / "requirements" / "demo"
        for rel_path in ["00-index.md", "pack.json", "nfr.md", "glossary.md",
                         "index.json", "_split-report.md", "slices/01-notifications.md"]:
            self.assertTrue((pack / rel_path).is_file(), rel_path)

        index = json.loads((pack / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["feature"], "demo")
        self.assertEqual(index["totals"]["slices"], 1)
        self.assertEqual(index["totals"]["requirements"], 4)
        self.assertEqual(index["errors"], [])

        proc = self.run_req("build", "--feature", "demo")
        self.assertIn("Built 1 slices", proc.stdout)
        self.assertIn("4 requirements", proc.stdout)

        proc = self.run_req("validate", "--feature", "demo")
        self.assertIn("Pack OK", proc.stdout)

        proc = self.run_req("show", "--feature", "demo", "--index")
        self.assertIn("Notifications", proc.stdout)
        self.assertIn("| # | Slice |", proc.stdout)

        proc = self.run_req("show", "--feature", "demo", "--slice", "notifications")
        self.assertIn("REQ-NOTIF-001", proc.stdout)

        proc = self.run_req("stale", "--feature", "demo")
        self.assertIn("No .sdlc/state.json; nothing to compare.", proc.stdout)

    def test_init_pack_and_new_slice(self):
        self.run_req("init-pack", "--feature", "fresh", "--title", "Fresh Feature")
        pack = self.tmp / "docs" / "requirements" / "fresh"
        for rel_path in ["00-index.md", "pack.json", "nfr.md", "glossary.md", "index.json"]:
            self.assertTrue((pack / rel_path).is_file(), rel_path)

        self.run_req("new-slice", "--feature", "fresh", "--slug", "core",
                     "--title", "Core", "--prefix", "CORE")
        slice_path = pack / "slices" / "01-core.md"
        self.assertTrue(slice_path.is_file())
        text = slice_path.read_text(encoding="utf-8")
        self.assertIn("slice: core", text)
        self.assertIn("prefix: CORE", text)
        self.assertIn("REQ-CORE-001", text)

        proc = self.run_req("build", "--feature", "fresh")
        self.assertIn("Built 1 slices", proc.stdout)
        self.run_req("validate", "--feature", "fresh")

    def test_validate_reports_unknown_dependency(self):
        self.run_req("init-pack", "--feature", "bad", "--title", "Bad")
        self.run_req("new-slice", "--feature", "bad", "--slug", "core",
                     "--title", "Core", "--prefix", "CORE")
        slice_path = self.tmp / "docs" / "requirements" / "bad" / "slices" / "01-core.md"
        text = slice_path.read_text(encoding="utf-8")
        slice_path.write_text(text.replace("depends_on: \n", "depends_on: missing\n", 1),
                              encoding="utf-8")
        proc = self.run_req("validate", "--feature", "bad", expect=1)
        self.assertIn("depends_on unknown slice 'missing'", proc.stdout + proc.stderr)


@unittest.skipIf(shutil.which("git") is None, "git is required")
class ReqIndexCliDelegationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-req-cli-"))
        (self.tmp / "docs" / "requirements").mkdir(parents=True)
        (self.tmp / "docs" / "requirements" / "sample.md").write_text(
            SAMPLE_REQUIREMENTS, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sdlc_req_analyze_delegates(self):
        env = os.environ.copy()
        env["SDLC_REQ_ROOT"] = str(self.tmp)
        for key in ("SDLC_REQ_DIR",):
            env.pop(key, None)
        proc = subprocess.run(
            [sys.executable, str(SDLC_PY), "req", "analyze",
             "--file", "docs/requirements/sample.md", "--json"],
            cwd=str(ROOT), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["ids"]["distinct"], 4)


if __name__ == "__main__":
    unittest.main()
