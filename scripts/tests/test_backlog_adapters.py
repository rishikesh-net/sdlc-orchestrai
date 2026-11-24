"""Integration tests for backlog tracker adapters (local + GitHub parity via a gh stub).

POSIX/CI only: the scripts use bash paths and a git working tree.
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
PUSH = ROOT / "skills" / "sdlc-backlog-breakdown" / "scripts" / "push-backlog.sh"
PULL = ROOT / "skills" / "sdlc-backlog-breakdown" / "scripts" / "pull-backlog.sh"
GRAPH = ROOT / "skills" / "sdlc-session-handoff" / "scripts" / "backlog-to-graph.sh"

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

GH_SHIM = """#!/usr/bin/env bash
set -u
[[ -n "${GH_SHIM_LOG:-}" ]] && echo "$*" >> "$GH_SHIM_LOG"
case "${1:-}:${2:-}" in
  auth:status|label:create|issue:edit|project:item-add) exit 0 ;;
esac
if [[ "${1:-}" == "--version" ]]; then echo "gh version 9.9.9 (shim)"; exit 0; fi
if [[ "${1:-}:${2:-}" == "issue:list" ]]; then echo "[]"; exit 0; fi
if [[ "${1:-}:${2:-}" == "issue:create" ]]; then
  n=$(grep -c 'issue create' "$GH_SHIM_LOG" 2>/dev/null || echo 1)
  echo "https://github.com/org/repo/issues/$n"
  exit 0
fi
if [[ "${1:-}" == "api" ]]; then
  if [[ "${2:-}" == "-X" ]]; then exit 0; fi
  echo "1000"
  exit 0
fi
exit 0
"""


def _bash_available() -> bool:
    return shutil.which("bash") is not None and shutil.which("jq") is not None


@unittest.skipIf(os.name == "nt", "adapter integration tests require POSIX bash paths")
@unittest.skipIf(not _bash_available(), "bash and jq are required")
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

    def run_script(self, script: Path, *args, env_extra=None):
        env = os.environ.copy()
        for key in ("SDLC_TRACKER", "SDLC_REPO", "SDLC_LOCAL_DIR", "GH_SHIM_LOG"):
            env.pop(key, None)
        env["PYTHONIOENCODING"] = "utf-8"
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            ["bash", str(script), *args],
            cwd=str(self.tmp), capture_output=True, text=True, env=env,
        )

    def read_backlog(self):
        return json.loads(self.backlog_path.read_text(encoding="utf-8"))

    def test_local_dry_run_writes_nothing(self):
        before = self.backlog_path.read_text(encoding="utf-8")
        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertIn("E1-S1", proc.stdout)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())
        self.assertEqual(self.backlog_path.read_text(encoding="utf-8"), before)

    def test_local_apply_creates_tickets_and_external(self):
        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json")
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
        self.assertEqual(self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json").returncode, 0)
        tickets = self.tmp / "docs" / "backlog" / "tickets"
        first = sorted(p.name for p in tickets.glob("*.md"))
        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("created=0 updated=3 failed=0", proc.stdout)
        self.assertEqual(sorted(p.name for p in tickets.glob("*.md")), first)

    def test_local_pull_and_label_filter(self):
        self.assertEqual(self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json").returncode, 0)
        proc = self.run_script(PULL, "--state", "all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = json.loads(proc.stdout)
        self.assertEqual({r["number"] for r in rows}, {"E1", "E1-S1", "E1-T1"})
        self.assertTrue(all(r["state"] == "open" for r in rows))

        filtered = self.run_script(PULL, "--state", "all", "--label", "component:db")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        rows = json.loads(filtered.stdout)
        self.assertEqual([r["number"] for r in rows], ["E1-T1"])

    def test_tracker_precedence_and_unknown_tracker(self):
        self.write_config("tracker: github\ngithub:\n  repo: org/repo\n")
        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json",
                               "--tracker", "local", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Tickets:", proc.stdout)

        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json",
                               "--dry-run", env_extra={"SDLC_TRACKER": "local"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json",
                               "--tracker", "nope", "--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Unknown or unsupported tracker", proc.stderr)
        self.assertIn("github", proc.stderr)
        self.assertIn("local", proc.stderr)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())

    def test_github_adapter_parity_with_gh_shim(self):
        shim_dir = self.tmp / "shim"
        shim_dir.mkdir()
        gh = shim_dir / "gh"
        gh.write_text(GH_SHIM, encoding="utf-8")
        gh.chmod(0o755)
        log = self.tmp / "gh-calls.log"
        self.write_config("tracker: github\ngithub:\n  repo: org/repo\n")

        env = {
            "PATH": f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GH_SHIM_LOG": str(log),
        }
        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json", env_extra=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("created=3 updated=0 failed=0", proc.stdout)

        data = self.read_backlog()
        keys = {item["id"]: item["external"]["key"] for item in data["items"]}
        self.assertEqual(set(keys.values()), {"1", "2", "3"})
        self.assertTrue(all(item["external"]["tracker"] == "github" for item in data["items"]))
        calls = log.read_text(encoding="utf-8")
        self.assertIn("issue create", calls)
        self.assertIn("label create", calls)

        proc = self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json", env_extra=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("created=0 updated=3 failed=0", proc.stdout)
        self.assertIn("issue edit", log.read_text(encoding="utf-8"))

    def test_backlog_to_graph_uses_external_key_for_local(self):
        self.assertEqual(self.run_script(PUSH, "--file", "docs/backlog/feat-backlog.json").returncode, 0)
        proc = self.run_script(GRAPH, "--file", "docs/backlog/feat-backlog.json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        entities = [r for r in rows if r.get("type") == "entity"]
        self.assertEqual(len(entities), 3)
        for entity in entities:
            self.assertNotIn("issue", entity)
            self.assertEqual(entity["external_key"], entity["id"])
            self.assertEqual(entity["tracker"], "local")

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
