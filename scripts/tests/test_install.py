"""Tests for the curl-bootstrap installer (install.py).

Run: python -m unittest discover -s scripts/tests -v
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import install  # noqa: E402


class TestRemoteDetection(unittest.TestCase):
    def _with_file(self, value):
        original = getattr(install, "__file__", None)
        try:
            install.__file__ = value
            return install._is_remote_execution()
        finally:
            install.__file__ = original

    def test_imported_module_is_local(self):
        self.assertFalse(install._is_remote_execution())

    def test_stdin_pipe_is_remote(self):
        self.assertTrue(self._with_file("<stdin>"))

    def test_python_dash_c_is_remote(self):
        self.assertTrue(self._with_file("-c"))

    def test_missing_file_is_remote(self):
        self.assertTrue(self._with_file(None))


class TestPackItems(unittest.TestCase):
    def test_documented_items_present(self):
        rels = {dst for _src, dst, _is_dir in install.PACK_ITEMS}
        for expected in [
            "AGENTS.md",
            "CLAUDE.md",
            ".github/copilot-instructions.md",
            ".github/workflows/security.yml",
            ".github/workflows/sync-check.yml",
            "skills",
            ".sdlc/schema",
            "scripts/sdlc.py",
            "scripts/sdlc_common.py",
            "scripts/sdlc_graph.py",
            "scripts/sdlc.cmd",
            "scripts/sdlc.ps1",
            "scripts/sdlc",
            "install.py",
        ]:
            self.assertIn(expected, rels)

    def test_all_sources_exist(self):
        missing = [src for src, _dst, _is_dir in install.PACK_ITEMS if not (ROOT / src).exists()]
        self.assertEqual(missing, [], f"PACK_ITEMS reference missing sources: {missing}")


class TestRunLocal(unittest.TestCase):
    def test_dry_run_makes_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            rc = install.run(target=str(target), dry_run=True, remote=False)
            self.assertEqual(rc, 0)
            self.assertFalse(target.exists())

    def test_dry_run_reports_no_files_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = install.run(target=str(target), dry_run=True, remote=False)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertFalse(target.exists())
            self.assertIn("no files were written", out)
            self.assertIn("would be copied", out)
            self.assertIn("Re-run without --dry-run", out)

    def test_real_install_copies_core_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            rc = install.run(target=str(target), dry_run=False, remote=False)
            self.assertEqual(rc, 0)
            self.assertTrue((target / "AGENTS.md").is_file())
            self.assertTrue((target / "scripts" / "sdlc.py").is_file())
            self.assertTrue((target / ".sdlc" / "config.yaml").is_file())
            self.assertIn("tracker: local", (target / ".sdlc" / "config.yaml").read_text(encoding="utf-8"))

    def test_second_run_reports_nothing_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            install.run(target=str(target), dry_run=False, remote=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = install.run(target=str(target), dry_run=False, remote=False)
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("Nothing copied", out)
            self.assertIn("--force", out)


if __name__ == "__main__":
    unittest.main()
