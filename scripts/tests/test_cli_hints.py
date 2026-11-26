"""Tests that user-facing CLI hints use a runnable command.

There is no global `sdlc` command; hints must show `python scripts/sdlc.py ...`.

Run: python -m unittest discover -s scripts/tests -v
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sdlc  # noqa: E402


class TestCliHints(unittest.TestCase):
    def test_cli_prefix_is_runnable(self):
        prefix = sdlc.cli_prefix()
        self.assertTrue(prefix.startswith("python "), prefix)
        self.assertIn("scripts", prefix)
        self.assertIn("sdlc.py", prefix)

    def test_check_env_hints_use_runnable_prefix(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            sdlc.check_env(json_output=True)
        data = json.loads(buf.getvalue())
        messages = "\n".join(check["message"] for check in data["checks"])
        self.assertIn(sdlc.cli_prefix(), messages)
        self.assertNotIn("`sdlc scan", messages)
        self.assertNotIn("`sdlc init", messages)

    def test_resume_missing_state_hint_is_runnable(self):
        original = sdlc.STATE_FILE
        sdlc.STATE_FILE = Path(tempfile.gettempdir()) / "sdlc-missing-state-for-test.json"
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = sdlc.cmd_resume()
        finally:
            sdlc.STATE_FILE = original
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn(sdlc.cli_prefix(), out)
        self.assertNotIn("`sdlc init", out)


if __name__ == "__main__":
    unittest.main()
