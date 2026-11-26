"""Guard tests: keep SDLCOrchestrAI a Python-only runtime.

Fails if a tracked shell script reappears or if executable docs/scripts drift
back to the removed bash tooling. Historical design notes and untracked
requirements drafts are excluded.

Run: python -m unittest discover -s scripts/tests -v
"""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THIS_TEST = "scripts/tests/test_single_runtime.py"

REMOVED_TOKENS = (
    "req-index.sh",
    "scan-all.sh",
    "scan-secrets.sh",
    "scan-sast.sh",
    "scan-deps.sh",
    "scan-iac.sh",
    "push-backlog.sh",
    "pull-backlog.sh",
    "sdlc-state.sh",
    "sync-skills.sh",
    "sdlc-graph.sh",
    "backlog-to-graph.sh",
)
BASH_TOKENS = ("bash skills/", "bash scripts/", "bash skills\\", "bash scripts\\")
EXCLUDED_PREFIXES = ("docs/design/", "docs/requirements/", ".sdlc/")
SCAN_SUFFIXES = (".md", ".py", ".yml", ".yaml")
SCAN_EXTRA = (".gitattributes", "install.py")


def tracked_files():
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return [item for item in proc.stdout.split("\0") if item]


class SingleRuntimeGuardTests(unittest.TestCase):
    def test_no_tracked_shell_scripts(self):
        shell = [path for path in tracked_files() if path.endswith(".sh")]
        self.assertEqual(shell, [], "tracked shell scripts are not allowed: " + ", ".join(shell))

    def _scanned_texts(self):
        for path in tracked_files():
            if path == THIS_TEST or path.startswith(EXCLUDED_PREFIXES):
                continue
            if not (path.endswith(SCAN_SUFFIXES) or path in SCAN_EXTRA):
                continue
            yield path, (ROOT / path).read_text(encoding="utf-8", errors="replace")

    def test_no_removed_tooling_references(self):
        offenders = []
        for path, text in self._scanned_texts():
            for token in REMOVED_TOKENS:
                if token in text:
                    offenders.append(f"{path}: {token}")
        self.assertEqual(offenders, [], "removed tooling is still referenced:\n" + "\n".join(offenders))

    def test_no_bash_commands_in_docs_or_scripts(self):
        offenders = []
        for path, text in self._scanned_texts():
            for token in BASH_TOKENS:
                if token in text:
                    offenders.append(f"{path}: {token}")
        self.assertEqual(offenders, [], "bash invocations are not allowed:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
