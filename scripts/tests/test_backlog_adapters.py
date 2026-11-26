"""Integration tests for backlog adapters (local + GitHub via a Python gh shim).

Runs on Windows, macOS, and Linux (git + Python only; no bash or jq).
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
BACKLOG_PY = ROOT / "skills" / "sdlc-backlog-breakdown" / "scripts" / "backlog.py"

BACKLOG = {
    "schema_version": 1,
    "feature": "feat",
    "items": [
        {
            "id": "E1",
            "type": "epic",
            "title": "Feature epic",
            "body_markdown": "Epic body.",
            "priority": "P1",
            "labels": ["feature:feat"],
            "req_refs": ["REQ-001"],
        },
        {
            "id": "E1-S1",
            "type": "story",
            "parent": "E1",
            "title": "User can do the thing",
            "user_story": "As a user, I want the thing, so that value.",
            "acceptance_criteria": [
                "Given a user, When they act, Then it works",
                "Given bad input, When saved, Then a 400 ProblemDetails is returned",
            ],
            "estimate": 3,
            "priority": "P1",
            "labels": ["component:api"],
            "depends_on": ["E1-T1"],
            "req_refs": ["REQ-001"],
            "design_ref": "docs/design/feat.md#api",
        },
        {
            "id": "E1-T1",
            "type": "task",
            "parent": "E1",
            "title": "Add table migration",
            "body_markdown": "Migration with rollback notes.",
            "estimate": 2,
            "priority": "P1",
            "labels": ["component:db"],
            "req_refs": ["REQ-001"],
        },
    ],
}

GH_SHIM_PY = r"""
import os
import sys

args = sys.argv[1:]
log = os.environ.get("GH_SHIM_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")

if args[:1] == ["--version"]:
    print("gh version 9.9.9 (shim)")
    sys.exit(0)
if args[:2] == ["auth", "status"] or args[:1] == ["label"]:
    sys.exit(0)
if args[:2] == ["issue", "list"]:
    print("[]")
    sys.exit(0)
if args[:2] == ["issue", "create"]:
    n = 1
    if log and os.path.exists(log):
        with open(log, encoding="utf-8") as handle:
            n = sum(1 for line in handle if "issue create" in line)
    print(f"https://github.com/org/repo/issues/{n}")
    sys.exit(0)
if args[:2] == ["issue", "edit"] or args[:2] == ["project", "item-add"]:
    sys.exit(0)
if args[:1] == ["api"]:
    if "-X" in args:
        sys.exit(0)
    print("1000")
    sys.exit(0)
sys.exit(0)
"""


@unittest.skipIf(shutil.which("git") is None, "git is required")
class BacklogAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-backlog-"))
        (self.tmp / ".sdlc").mkdir()
        (self.tmp / "docs" / "backlog").mkdir(parents=True)
        self.backlog_path = self.tmp / "docs" / "backlog" / "feat-backlog.json"
        self.backlog_path.write_text(json.dumps(BACKLOG, indent=2), encoding="utf-8")
        self.write_config("tracker: local\nlocal:\n  output_dir: docs/backlog/tickets\n")
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_config(self, text: str):
        (self.tmp / ".sdlc" / "config.yaml").write_text(text, encoding="utf-8")

    def run_script(self, *args, env_extra=None):
        env = os.environ.copy()
        for key in ("SDLC_TRACKER", "SDLC_REPO", "SDLC_LOCAL_DIR", "GH_SHIM_LOG", "SDLC_BACKLOG_ROOT"):
            env.pop(key, None)
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(BACKLOG_PY), *args],
            cwd=str(self.tmp), capture_output=True, text=True, env=env,
        )

    def install_gh_shim(self):
        shim_dir = self.tmp / "shim"
        shim_dir.mkdir()
        shim_py = shim_dir / "gh_shim.py"
        shim_py.write_text(GH_SHIM_PY, encoding="utf-8")
        if os.name == "nt":
            (shim_dir / "gh.cmd").write_text(
                f'@echo off\r\n"{sys.executable}" "{shim_py}" %*\r\n', encoding="utf-8"
            )
        else:
            gh = shim_dir / "gh"
            gh.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "{shim_py}" "$@"\n', encoding="utf-8"
            )
            gh.chmod(0o755)
        log = self.tmp / "gh-calls.log"
        return {
            "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GH_SHIM_LOG": str(log),
        }, log

    def read_backlog(self):
        return json.loads(self.backlog_path.read_text(encoding="utf-8"))

    def test_local_dry_run_writes_nothing(self):
        before = self.backlog_path.read_text(encoding="utf-8")
        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertIn("E1-S1", proc.stdout)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())
        self.assertEqual(self.backlog_path.read_text(encoding="utf-8"), before)

    def test_dry_run_plan_contract(self):
        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        out = proc.stdout
        for heading in ("ID", "TYPE", "ACTION", "ISSUE", "TITLE"):
            self.assertIn(heading, out)
        self.assertIn("E1", out)
        self.assertIn("E1-S1", out)
        self.assertIn("E1-T1", out)
        self.assertIn("create", out)
        self.assertIn("Dry run complete. No changes were made.", out)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())
        self.assertEqual(self.read_backlog(), BACKLOG)

    def test_duplicate_ids_rejected_before_touching_tracker(self):
        duplicate = json.loads(json.dumps(BACKLOG))
        duplicate["items"].append(dict(duplicate["items"][0]))
        self.backlog_path.write_text(json.dumps(duplicate, indent=2), encoding="utf-8")
        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json", "--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate ids", proc.stderr)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())

    def test_local_apply_creates_tickets_and_external(self):
        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        tickets = self.tmp / "docs" / "backlog" / "tickets"
        names = sorted(p.name for p in tickets.glob("*.md"))
        self.assertEqual(names, ["E1-S1.md", "E1-T1.md", "E1.md"])

        data = self.read_backlog()
        by_id = {item["id"]: item for item in data["items"]}
        self.assertEqual(by_id["E1-S1"]["external"], {
            "tracker": "local",
            "key": "E1-S1",
            "url": "docs/backlog/tickets/E1-S1.md",
        })

        story = (tickets / "E1-S1.md").read_text(encoding="utf-8")
        self.assertIn('title: "User can do the thing"', story)
        self.assertIn("type: story", story)
        self.assertIn("parent: E1", story)
        self.assertIn("state: open", story)
        self.assertIn('depends_on: ["E1-T1"]', story)
        self.assertIn('labels: ["component:api"]', story)
        self.assertIn("### Acceptance criteria", story)
        self.assertIn("**Part of:** E1", story)
        self.assertIn("**Blocked by:** E1-T1", story)

    def test_local_rerun_updates_without_duplicates(self):
        self.assertEqual(self.run_script("push", "--file", "docs/backlog/feat-backlog.json").returncode, 0)
        tickets = self.tmp / "docs" / "backlog" / "tickets"
        first = sorted(p.name for p in tickets.glob("*.md"))
        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("created=0 updated=3 failed=0", proc.stdout)
        self.assertEqual(sorted(p.name for p in tickets.glob("*.md")), first)

    def test_local_pull_and_label_filter(self):
        self.assertEqual(self.run_script("push", "--file", "docs/backlog/feat-backlog.json").returncode, 0)
        proc = self.run_script("pull", "--state", "all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = json.loads(proc.stdout)
        self.assertEqual({r["number"] for r in rows}, {"E1", "E1-S1", "E1-T1"})
        self.assertTrue(all(r["state"] == "open" for r in rows))

        filtered = self.run_script("pull", "--state", "all", "--label", "component:db")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        rows = json.loads(filtered.stdout)
        self.assertEqual([r["number"] for r in rows], ["E1-T1"])

    def test_tracker_precedence_and_unknown_tracker(self):
        self.write_config("tracker: github\ngithub:\n  repo: org/repo\n")
        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json",
                               "--tracker", "local", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Tickets:", proc.stdout)

        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json",
                               "--dry-run", env_extra={"SDLC_TRACKER": "local"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json",
                               "--tracker", "nope", "--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Unknown or unsupported tracker", proc.stderr)
        self.assertIn("github", proc.stderr)
        self.assertIn("local", proc.stderr)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())

    def test_github_adapter_parity_with_gh_shim(self):
        env, log = self.install_gh_shim()
        self.write_config("tracker: github\ngithub:\n  repo: org/repo\n")

        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json", env_extra=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("created=3 updated=0 failed=0", proc.stdout)

        data = self.read_backlog()
        keys = {item["id"]: item["external"]["key"] for item in data["items"]}
        self.assertEqual(set(keys.values()), {"1", "2", "3"})
        self.assertTrue(all(item["external"]["tracker"] == "github" for item in data["items"]))
        calls = log.read_text(encoding="utf-8")
        self.assertIn("issue create", calls)
        self.assertIn("label create", calls)

        proc = self.run_script("push", "--file", "docs/backlog/feat-backlog.json", env_extra=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("created=0 updated=3 failed=0", proc.stdout)
        self.assertIn("issue edit", log.read_text(encoding="utf-8"))

    def test_check_env_reports_local_tracker(self):
        env = os.environ.copy()
        env.pop("SDLC_TRACKER", None)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "sdlc.py"), "check-env", "--json"],
            cwd=str(self.tmp), capture_output=True, text=True, env=env,
        )
        data = json.loads(proc.stdout)
        checks = {c["name"]: c for c in data["checks"]}
        self.assertIn("tracker_local", checks)
        self.assertEqual(checks["tracker_local"]["status"], "ok")
        self.assertIn("docs/backlog/tickets", checks["tracker_local"]["message"])


if __name__ == "__main__":
    unittest.main()
