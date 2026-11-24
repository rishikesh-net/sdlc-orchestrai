"""Tests for `sdlc slices plan/show/check` (parallel requirements-pack orchestration).

Cross-platform: uses only Python + git; no bash or jq required.
Run: python -m unittest discover -s scripts/tests -v
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SDLC = ROOT / "scripts" / "sdlc.py"
WORK_ORDER_TPL = ROOT / "skills" / "sdlc-session-handoff" / "templates" / "slice-work-order.md.tmpl"


def sha16(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


@unittest.skipIf(shutil.which("git") is None, "git is required")
class SlicesCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-slices-"))
        self.pack = self.tmp / "docs" / "requirements" / "demo"
        (self.pack / "slices").mkdir(parents=True)
        (self.tmp / ".sdlc").mkdir()
        tpl_dir = self.tmp / "skills" / "sdlc-session-handoff" / "templates"
        tpl_dir.mkdir(parents=True)
        shutil.copyfile(WORK_ORDER_TPL, tpl_dir / "slice-work-order.md.tmpl")

        self.slices = {
            "alpha": {"file": "slices/01-alpha.md", "status": "approved", "prefix": "ALP",
                      "ids": ["REQ-ALP-001", "NFR-ALP-001"], "deps": []},
            "beta": {"file": "slices/02-beta.md", "status": "draft", "prefix": "BET",
                     "ids": ["REQ-BET-001"], "deps": []},
            "gamma": {"file": "slices/03-gamma.md", "status": "approved", "prefix": "GAM",
                      "ids": ["REQ-GAM-001"], "deps": ["alpha"]},
        }
        for slug, meta in self.slices.items():
            path = self.pack / meta["file"]
            path.write_text(
                f"---\nslice: {slug}\nstatus: {meta['status']}\nprefix: {meta['prefix']}\n---\n\n"
                f"# {slug}\n\n" + "\n".join(f"- {rid}: shall do something testable." for rid in meta["ids"]) + "\n",
                encoding="utf-8")
        self.write_index()
        (self.tmp / "docs" / "design" / "demo").mkdir(parents=True)
        (self.tmp / "docs" / "design" / "demo" / "00-overview.md").write_text(
            "# Overview\n\nShared architecture and data ownership.\n", encoding="utf-8")
        self.write_state()
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_index(self):
        slices = []
        for slug, meta in self.slices.items():
            path = self.pack / meta["file"]
            slices.append({
                "kind": "slice", "slug": slug, "file": meta["file"], "title": slug.title(),
                "status": meta["status"], "priority": "Must", "prefix": meta["prefix"],
                "summary": f"{slug} summary", "depends_on": meta["deps"], "lines": 5,
                "approx_tokens": 20, "hash": sha16(path), "requirement_ids": meta["ids"],
            })
        index = {
            "schema_version": 1, "feature": "demo", "id_policy": "pack",
            "id_regex": "(REQ|NFR)-([A-Z][A-Z0-9]*-)?[0-9]+",
            "slices": slices, "cross_cutting": [], "requirements": {},
            "totals": {"slices": len(slices), "requirements": 4, "lines": 15},
            "errors": [], "warnings": [],
        }
        (self.pack / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")

    def write_state(self):
        state = {
            "schema_version": 1,
            "features": {
                "demo": {
                    "phase": "design", "gates": {"design:alpha": "approved", "design:beta": "in-review"},
                    "artifacts": [], "open_questions": [], "notes": [],
                }
            },
            "updated_by": "test", "updated_at": "2026-01-01T00:00:00Z",
            "repo_sha": "none", "repo_dirty": False,
        }
        (self.tmp / ".sdlc" / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    def sdlc(self, *args):
        return subprocess.run([sys.executable, str(SDLC), "slices", *args],
                              cwd=str(self.tmp), capture_output=True, text=True)

    def manifest(self, stage: str):
        path = self.tmp / ".sdlc" / "parallel" / "demo" / stage / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ plan
    def test_plan_design_skips_unapproved(self):
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "design", "--max-parallel", "4")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = self.manifest("design")
        self.assertEqual([s["slug"] for s in manifest["slices"]], ["alpha", "gamma"])
        self.assertEqual([s["slug"] for s in manifest["skipped"]], ["beta"])
        self.assertEqual(manifest["max_parallel"], 4)
        self.assertEqual(len(manifest["work_order_hash"]), 16)

        order = self.tmp / manifest["slices"][0]["work_order"]
        text = order.read_text(encoding="utf-8")
        self.assertIn("REQ-ALP-001", text)
        self.assertIn("docs/design/demo/00-overview.md", text)
        self.assertNotIn("{{", text)

    def test_plan_requires_overview(self):
        (self.tmp / "docs" / "design" / "demo" / "00-overview.md").unlink()
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "design")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("overview", proc.stderr.lower())

    def test_plan_rejects_stale_index(self):
        with open(self.pack / "slices" / "01-alpha.md", "a", encoding="utf-8") as f:
            f.write("\n- REQ-ALP-002: added after build.\n")
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "design")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("req-index.sh build", proc.stderr)

    def test_dry_run_writes_nothing_and_existing_requires_force(self):
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "design", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertFalse((self.tmp / ".sdlc" / "parallel").exists())

        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design").returncode, 0)
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "design")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--force", proc.stderr)
        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design", "--force").returncode, 0)

    def test_show_prints_work_order(self):
        proc = self.sdlc("show", "--feature", "demo", "--stage", "design", "--slice", "alpha")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Slice work order: demo / alpha", proc.stdout)
        self.assertIn("REQ-ALP-001", proc.stdout)

    def test_deterministic_work_orders(self):
        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design").returncode, 0)
        first = self.manifest("design")
        first_order = (self.tmp / first["slices"][0]["work_order"]).read_text(encoding="utf-8")
        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design", "--force").returncode, 0)
        second = self.manifest("design")
        self.assertEqual(first["work_order_hash"], second["work_order_hash"])
        self.assertEqual(first_order, (self.tmp / second["slices"][0]["work_order"]).read_text(encoding="utf-8"))

    # ----------------------------------------------------------------- check
    def write_design_outputs(self, slugs=("alpha", "gamma")):
        design_dir = self.tmp / "docs" / "design" / "demo"
        design_dir.mkdir(parents=True, exist_ok=True)
        for slug in slugs:
            ids = self.slices[slug]["ids"]
            body = ["# Design: " + slug, "", "## 2. Requirement coverage", "| Requirement | Section |", "|---|---|"]
            body += [f"| {rid} | 4.1 |" for rid in ids]
            body += ["", "## 11. Risks and assumptions", "- none"]
            (design_dir / f"{slug}.md").write_text("\n".join(body) + "\n", encoding="utf-8")

    def test_check_design_coverage(self):
        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design").returncode, 0)
        self.write_design_outputs()
        proc = self.sdlc("check", "--feature", "demo", "--stage", "design")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((self.tmp / ".sdlc" / "parallel" / "demo" / "design" / "report.md").is_file())

        gamma = self.tmp / "docs" / "design" / "demo" / "gamma.md"
        gamma.write_text(gamma.read_text(encoding="utf-8").replace("REQ-GAM-001", "REQ-GAM-999"), encoding="utf-8")
        proc = self.sdlc("check", "--feature", "demo", "--stage", "design", "--json")
        self.assertEqual(proc.returncode, 1)
        report = json.loads(proc.stdout)
        self.assertEqual(report["summary"]["fail"], 1)

    def test_check_design_detects_stale_slice(self):
        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design").returncode, 0)
        self.write_design_outputs()
        with open(self.pack / "slices" / "01-alpha.md", "a", encoding="utf-8") as f:
            f.write("\nchanged\n")
        proc = self.sdlc("check", "--feature", "demo", "--stage", "design", "--json")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("changed since plan", proc.stdout)

    def test_check_backlog_coverage_and_epic(self):
        self.write_design_outputs()
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "backlog")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        manifest = self.manifest("backlog")
        self.assertEqual([s["slug"] for s in manifest["slices"]], ["alpha", "gamma"])
        self.assertTrue(any("gate not recorded" in w for s in manifest["slices"] if s["slug"] == "gamma"
                            for w in s["warnings"]))

        backlog_dir = self.tmp / "docs" / "backlog" / "demo"
        backlog_dir.mkdir(parents=True)
        for slug in ("alpha", "gamma"):
            prefix = self.slices[slug]["prefix"]
            data = {
                "schema_version": 1, "feature": "demo",
                "items": [{
                    "id": f"E-{prefix}", "type": "epic", "title": slug.title(),
                    "req_refs": self.slices[slug]["ids"],
                }],
            }
            (backlog_dir / f"{slug}-backlog.json").write_text(json.dumps(data), encoding="utf-8")
            (backlog_dir / f"{slug}-backlog.md").write_text(f"# {slug}\n", encoding="utf-8")

        proc = self.sdlc("check", "--feature", "demo", "--stage", "backlog")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        gamma = backlog_dir / "gamma-backlog.json"
        data = json.loads(gamma.read_text(encoding="utf-8"))
        data["items"][0]["req_refs"] = []
        gamma.write_text(json.dumps(data), encoding="utf-8")
        proc = self.sdlc("check", "--feature", "demo", "--stage", "backlog")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("REQ-GAM-001", proc.stdout)

    def test_check_threat_model_duplicate_ids(self):
        self.write_design_outputs()
        proc = self.sdlc("plan", "--feature", "demo", "--stage", "threat-model")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        sec = self.tmp / "docs" / "security" / "demo"
        sec.mkdir(parents=True)
        for slug in ("alpha", "gamma"):
            (sec / f"{slug}-threats.md").write_text(
                f"# Threats: {slug}\n\n## Summary\n\n### T-001 Credential theft\n- Control: rotate\n",
                encoding="utf-8")
        proc = self.sdlc("check", "--feature", "demo", "--stage", "threat-model")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("also used by slice", proc.stdout)

    def test_plan_does_not_touch_state_or_index(self):
        state_before = (self.tmp / ".sdlc" / "state.json").read_text(encoding="utf-8")
        index_before = (self.pack / "index.json").read_text(encoding="utf-8")
        self.assertEqual(self.sdlc("plan", "--feature", "demo", "--stage", "design").returncode, 0)
        self.write_design_outputs()
        self.sdlc("check", "--feature", "demo", "--stage", "design")
        self.assertEqual((self.tmp / ".sdlc" / "state.json").read_text(encoding="utf-8"), state_before)
        self.assertEqual((self.pack / "index.json").read_text(encoding="utf-8"), index_before)


if __name__ == "__main__":
    unittest.main()
