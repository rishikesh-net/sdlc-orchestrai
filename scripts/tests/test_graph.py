"""Tests for the Python knowledge-graph CLI (sdlc_graph.py).

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
GRAPH_PY = ROOT / "scripts" / "sdlc_graph.py"
SDLC_PY = ROOT / "scripts" / "sdlc.py"


@unittest.skipIf(shutil.which("git") is None, "git is required")
class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-graph-"))
        (self.tmp / ".sdlc" / "memory").mkdir(parents=True)
        (self.tmp / "docs" / "backlog").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)
        self.graph = self.tmp / ".sdlc" / "memory" / "graph.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_graph(self, *args, expect=0):
        env = os.environ.copy()
        env["SDLC_GRAPH_ROOT"] = str(self.tmp)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(GRAPH_PY), *args],
            cwd=str(self.tmp), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc

    def lines(self):
        if not self.graph.is_file():
            return []
        return [json.loads(line) for line in self.graph.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def test_add_validate_normalize(self):
        self.run_graph("add-entity", "--id", "E1", "--kind", "epic", "--title", "Epic")
        self.run_graph("add-entity", "--id", "REQ-001", "--kind", "requirement")
        self.run_graph("add-relation", "--from", "E1", "--rel", "covers", "--to", "REQ-001")
        self.run_graph("add-entity", "--id", "T-001", "--kind", "threat",
                       "--attr", "severity=high")
        self.run_graph("add-relation", "--from", "T-001", "--rel", "mitigated_by",
                       "--to", "TASK-1")

        proc = self.run_graph("validate")
        self.assertIn("OK (3 entities, 2 relations)", proc.stdout)

        self.run_graph("normalize")
        first = self.lines()
        self.run_graph("normalize")
        self.assertEqual(self.lines(), first)
        self.assertEqual(len(first), 5)

    def test_backlog_to_graph_and_gaps(self):
        backlog = {
            "schema_version": 1,
            "feature": "feat",
            "items": [
                {"id": "E1", "type": "epic", "title": "Epic", "req_refs": ["REQ-001"]},
                {"id": "E1-S1", "type": "story", "parent": "E1", "title": "Story",
                 "req_refs": ["REQ-001"]},
            ],
        }
        path = self.tmp / "docs" / "backlog" / "feat-backlog.json"
        path.write_text(json.dumps(backlog), encoding="utf-8")

        self.run_graph("backlog-to-graph", "--file", "docs/backlog/feat-backlog.json", "--apply")
        entities = {item["id"] for item in self.lines() if item["type"] == "entity"}
        self.assertIn("E1", entities)
        self.assertIn("E1-S1", entities)

        self.run_graph("add-entity", "--id", "REQ-002", "--kind", "requirement")
        self.run_graph("add-entity", "--id", "T-001", "--kind", "threat",
                       "--attr", "severity=high")
        self.run_graph("add-entity", "--id", "F-001", "--kind", "finding",
                       "--attr", "severity=high", "--attr", "status=open")

        gaps = self.run_graph("gaps").stdout
        self.assertIn("UNCOVERED REQ-002", gaps)
        self.assertIn("UNMITIGATED T-001 (high)", gaps)
        self.assertIn("UNTRACKED F-001 (high)", gaps)
        self.assertNotIn("UNCOVERED REQ-001", gaps)

        self.run_graph("add-relation", "--from", "E1", "--rel", "covers", "--to", "REQ-002")
        self.run_graph("add-relation", "--from", "T-001", "--rel", "mitigated_by",
                       "--to", "TASK-1")
        self.run_graph("add-relation", "--from", "F-001", "--rel", "tracked_by",
                       "--to", "TASK-2")
        self.assertIn("No gaps", self.run_graph("gaps").stdout)

    def test_validate_rejects_bad_line(self):
        self.graph.write_text('{"type": "relation", "from": "A"}\n', encoding="utf-8")
        proc = self.run_graph("validate", expect=1)
        self.assertIn("FAIL", proc.stdout + proc.stderr)

    def test_import_dry_run_then_apply(self):
        source = self.tmp / "import.jsonl"
        source.write_text(json.dumps({"type": "entity", "id": "X", "kind": "task"}) + "\n",
                          encoding="utf-8")
        dry = self.run_graph("import", "--file", "import.jsonl", "--dry-run")
        self.assertIn('"id":"X"', dry.stdout)
        self.assertFalse(self.graph.is_file())

        self.run_graph("import", "--file", "import.jsonl")
        self.assertTrue(self.graph.is_file())
        self.run_graph("validate")

    def test_sdlc_graph_cli_delegates(self):
        self.run_graph("add-entity", "--id", "E1", "--kind", "epic")
        env = os.environ.copy()
        env["SDLC_GRAPH_ROOT"] = str(self.tmp)
        proc = subprocess.run(
            [sys.executable, str(SDLC_PY), "graph", "validate"],
            cwd=str(ROOT), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
