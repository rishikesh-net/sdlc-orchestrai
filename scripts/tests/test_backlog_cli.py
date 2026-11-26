"""Contract test for `python scripts/sdlc.py backlog ...` delegation.

Runs the task-scale CLI from the pack root while pointing the backlog root at a
temporary project, so no files are written to the pack. Cross-platform.
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

BACKLOG = {
    "schema_version": 1,
    "feature": "feat",
    "items": [
        {"id": "E1", "type": "epic", "title": "Epic", "body_markdown": "Body."},
        {"id": "E1-S1", "type": "story", "parent": "E1", "title": "Story", "estimate": 2},
    ],
}


@unittest.skipIf(shutil.which("git") is None, "git is required")
class BacklogCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sdlc-backlog-cli-"))
        (self.tmp / ".sdlc").mkdir()
        (self.tmp / "docs" / "backlog").mkdir(parents=True)
        (self.tmp / ".sdlc" / "config.yaml").write_text(
            "tracker: local\nlocal:\n  output_dir: docs/backlog/tickets\n", encoding="utf-8"
        )
        (self.tmp / "docs" / "backlog" / "feat-backlog.json").write_text(
            json.dumps(BACKLOG, indent=2), encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        subprocess.run(["git", "-C", str(self.tmp), "add", "-A"], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_push_dry_run_delegates_to_backlog_module(self):
        env = os.environ.copy()
        env["SDLC_BACKLOG_ROOT"] = str(self.tmp)
        env["PYTHONIOENCODING"] = "utf-8"
        for key in ("SDLC_TRACKER", "SDLC_REPO", "SDLC_LOCAL_DIR"):
            env.pop(key, None)

        proc = subprocess.run(
            [sys.executable, str(SDLC_PY), "backlog", "push",
             "--file", "docs/backlog/feat-backlog.json", "--dry-run"],
            cwd=str(ROOT), capture_output=True, text=True, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        self.assertIn("E1", proc.stdout)
        self.assertFalse((self.tmp / "docs" / "backlog" / "tickets").exists())


if __name__ == "__main__":
    unittest.main()
