"""Tests for the differential test harness (Phase 0 migration scaffolding).

Run: python -m unittest discover -s scripts/tests -v
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _diff_harness as harness  # noqa: E402


def py(code: str):
    return [sys.executable, "-c", code]


class ModeTests(unittest.TestCase):
    def test_default_is_shell(self):
        env = {k: v for k, v in os.environ.items() if k != "SDLC_IMPL"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(harness.impl_mode(), "shell")

    def test_valid_modes(self):
        for mode in harness.VALID_MODES:
            with mock.patch.dict(os.environ, {"SDLC_IMPL": mode}):
                self.assertEqual(harness.impl_mode(), mode)

    def test_invalid_mode_raises(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "wat"}):
            with self.assertRaises(harness.HarnessError):
                harness.impl_mode()


class NormalizationTests(unittest.TestCase):
    def test_text_normalizes_crlf_slashes_and_roots(self):
        raw = "a\\b\r\nc   \r\n\r\n\r\nd"
        out = harness.normalize_text(raw, roots=[r"C:\repo"])
        self.assertEqual(out, "a/b\nc\n\nd")

    def test_text_replaces_temp_root(self):
        raw = "report at C:\\tmp\\x\\report.json"
        out = harness.normalize_text(raw, roots=[r"C:\tmp\x"])
        self.assertIn("<ROOT>/report.json", out)

    def test_json_drops_volatile_keys_and_sorts(self):
        raw = '{"b": 1, "startTime": "now", "a": [{"endTime": "later", "x": 2}]}'
        out = harness.normalize_json_text(raw)
        self.assertNotIn("startTime", out)
        self.assertNotIn("endTime", out)
        self.assertLess(out.index('"a"'), out.index('"b"'))


class CompareTests(unittest.TestCase):
    def test_shell_mode_runs_shell_only(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "shell"}):
            result = harness.compare(py("print('hi')"), None, label="shell-only")
        self.assertEqual(result.code, 0)
        self.assertEqual(result.stdout.strip(), "hi")

    def test_python_mode_requires_python_command(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "python"}):
            with self.assertRaises(harness.HarnessError):
                harness.compare(py("print('hi')"), None, label="no-python")

    def test_python_mode_runs_python_only(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "python"}):
            result = harness.compare(py("print('shell')"), py("print('python')"), label="py")
        self.assertEqual(result.stdout.strip(), "python")

    def test_shadow_equal_output_passes(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "shadow"}):
            result = harness.compare(
                py("print('same')"), py("print('same')"), label="equal"
            )
        self.assertEqual(result.code, 0)
        self.assertEqual(result.stdout.strip(), "same")

    def test_shadow_mismatch_raises(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "shadow"}):
            with self.assertRaises(harness.DiffMismatch) as ctx:
                harness.compare(py("print('shell')"), py("print('python')"), label="diff")
        self.assertIn("stdout differs", str(ctx.exception))

    def test_shadow_exit_code_mismatch_raises(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "shadow"}):
            with self.assertRaises(harness.DiffMismatch) as ctx:
                harness.compare(py("raise SystemExit(0)"), py("raise SystemExit(3)"), label="rc")
        self.assertIn("exit code differs", str(ctx.exception))

    def test_shadow_normalizer_can_hide_volatile_output(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "shadow"}):
            result = harness.compare(
                py("print('{\"x\": 1, \"startTime\": \"a\"}')"),
                py("print('{\"x\": 1, \"startTime\": \"b\"}')"),
                normalize=harness.normalize_json_text,
                label="json",
            )
        self.assertEqual(result.code, 0)

    def test_shadow_compare_stderr(self):
        with mock.patch.dict(os.environ, {"SDLC_IMPL": "shadow"}):
            with self.assertRaises(harness.DiffMismatch):
                harness.compare(
                    py("import sys; print('x', file=sys.stderr)"),
                    py("import sys; print('y', file=sys.stderr)"),
                    label="stderr",
                    compare_stderr=True,
                )


if __name__ == "__main__":
    unittest.main()
