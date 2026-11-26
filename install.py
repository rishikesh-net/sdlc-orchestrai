#!/usr/bin/env python3
"""
SDLCOrchestrAI bootstrap installer.

Usage - remote (curl, piped into Python):
    # macOS / Linux
    curl -fsSL https://raw.githubusercontent.com/rishikesh-net/sdlc-orchestrai/main/install.py | python3 -

    # Windows (PowerShell or cmd)
    curl.exe -fsSL https://raw.githubusercontent.com/rishikesh-net/sdlc-orchestrai/main/install.py | python -
    # PowerShell-native alternative:
    Invoke-RestMethod https://raw.githubusercontent.com/rishikesh-net/sdlc-orchestrai/main/install.py | python -

Usage - local (after cloning):
    python install.py [--target <dir>] [--tracker local|github] [--dry-run] [--force]

What it does:
    1. Detects whether it is running from a local clone or piped via stdin.
    2. Remote: downloads the main-branch tarball and extracts the pack files.
    3. Local:  copies pack files from the repo into --target (default: current working directory).
    4. Prints a post-install checklist.
"""

import argparse
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_REPO = "rishikesh-net/sdlc-orchestrai"
GITHUB_BRANCH_TARBALL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.tar.gz"

# Pack files/dirs to copy from source root -> target root.
# (source_rel, target_rel, is_dir)
PACK_ITEMS = [
    ("AGENTS.md",                             "AGENTS.md",                               False),
    ("CLAUDE.md",                             "CLAUDE.md",                               False),
    (".github/copilot-instructions.md",       ".github/copilot-instructions.md",         False),
    (".github/workflows/security.yml",        ".github/workflows/security.yml",          False),
    (".github/workflows/sync-check.yml",      ".github/workflows/sync-check.yml",        False),
    ("skills",                                "skills",                                  True),
    (".sdlc/schema",                          ".sdlc/schema",                            True),
    ("scripts/sdlc.py",                       "scripts/sdlc.py",                         False),
    ("scripts/sdlc.cmd",                      "scripts/sdlc.cmd",                        False),
    ("scripts/sdlc.ps1",                      "scripts/sdlc.ps1",                        False),
    ("scripts/sdlc",                          "scripts/sdlc",                            False),
    ("install.py",                            "install.py",                              False),
]

CONFIG_YAML_LOCAL = """\
tracker: local
local:
  output_dir: docs/backlog/tickets

security:
  strict: false
  scanners:
    gitleaks: auto
    trufflehog: auto
    semgrep: auto
    trivy: auto
    osv_scanner: auto
    zizmor: auto
    dotnet: auto
    npm_audit: auto
"""

CONFIG_YAML_GITHUB = """\
tracker: github
github:
  repo: ""          # your-org/your-repo
  project_number: ""
  project_owner: ""

security:
  strict: false
  scanners:
    gitleaks: auto
    trufflehog: auto
    semgrep: auto
    trivy: auto
    osv_scanner: auto
    zizmor: auto
    dotnet: auto
    npm_audit: auto
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print(msg: str, dry_run: bool = False) -> None:
    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}{msg}")


def _copy_item(src: Path, dst: Path, is_dir: bool, force: bool, dry_run: bool) -> bool:
    """Copy src -> dst. Returns True if copied / would copy."""
    if dst.exists() and not force:
        print(f"  skipped  {dst}  (already exists; use --force to overwrite)")
        return False
    if dry_run:
        action = "copy dir " if is_dir else "copy file"
        _print(f"  {action}  {src}  ->  {dst}", dry_run=True)
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    if is_dir:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    print(f"  OK  {dst}")
    return True


def _write_config(target: Path, tracker: str, force: bool, dry_run: bool) -> bool:
    """Write .sdlc/config.yaml. Returns True if written / would write, False if skipped."""
    cfg = target / ".sdlc" / "config.yaml"
    content = CONFIG_YAML_LOCAL if tracker == "local" else CONFIG_YAML_GITHUB
    if cfg.exists() and not force:
        print("  skipped  .sdlc/config.yaml  (already exists; use --force to overwrite)")
        return False
    if dry_run:
        _print(f"  write    .sdlc/config.yaml  (tracker: {tracker})", dry_run=True)
        return True
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(content, encoding="utf-8")
    print(f"  OK  .sdlc/config.yaml  (tracker: {tracker})")
    return True


def _post_install_checklist(target: Path) -> None:
    scripts_prefix = "python scripts/sdlc.py"
    if sys.platform == "win32":
        scripts_prefix = "python scripts\\sdlc.py"
    print()
    print("=" * 60)
    print("  SDLCOrchestrAI installed successfully!")
    print("=" * 60)
    print()
    print("Next steps:")
    print(f"  cd {target}")
    print(f"  {scripts_prefix} check-env        # verify prerequisites")
    print(f"  {scripts_prefix} sync-skills      # sync skills to your AI client")
    print()
    print("Then open your AI client in this repository and ask:")
    print('  "Which sdlc- skills do you have available?"')
    print()
    print("Full walkthrough: https://github.com/rishikesh-net/sdlc-orchestrai/blob/main/GETTING_STARTED.md")


# ---------------------------------------------------------------------------
# Install from local source (clone scenario)
# ---------------------------------------------------------------------------


def _install_local(source: Path, target: Path, tracker: str, force: bool, dry_run: bool) -> int:
    print(f"\nInstalling from local source: {source}")
    print(f"Target directory:             {target}")
    if dry_run:
        print("DRY RUN - no files will be written (re-run without --dry-run to install).")
    print()
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    missing = 0
    for src_rel, dst_rel, is_dir in PACK_ITEMS:
        src = source / src_rel
        dst = target / dst_rel
        if not src.exists():
            print(f"  missing  {src_rel}  (skipped)")
            missing += 1
            continue
        if _copy_item(src, dst, is_dir, force, dry_run):
            copied += 1
        else:
            skipped += 1

    if _write_config(target, tracker, force, dry_run):
        copied += 1
    else:
        skipped += 1

    if dry_run:
        print()
        print(
            f"Dry run complete - no files were written. "
            f"{copied} item(s) would be copied, {skipped} skipped, {missing} missing."
        )
        print("Re-run without --dry-run to install.")
    elif copied == 0:
        print()
        print(
            "Nothing copied - all pack files already exist. "
            "Use --force to overwrite or -t <dir> to target another folder."
        )
    else:
        _post_install_checklist(target)
    return 0


# ---------------------------------------------------------------------------
# Install from remote (curl / Invoke-RestMethod scenario)
# ---------------------------------------------------------------------------


def _download_tarball(url: str, dest: Path) -> None:
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:  # noqa: S310
        shutil.copyfileobj(resp, f)


def _find_source_prefix(tf: tarfile.TarFile) -> str:
    """Return the top-level directory prefix inside the tarball."""
    names = tf.getnames()
    if names:
        return names[0].split("/")[0]
    return ""


def _install_remote(target: Path, tracker: str, force: bool, dry_run: bool) -> int:
    print("\nSDLCOrchestrAI bootstrap installer")
    print(f"Installing into: {target}\n")

    with tempfile.TemporaryDirectory() as tmp:
        tarball = Path(tmp) / "sdlc-orchestrai.tar.gz"
        _download_tarball(GITHUB_BRANCH_TARBALL, tarball)

        extract_dir = Path(tmp) / "extracted"
        with tarfile.open(tarball, "r:gz") as tf:
            prefix = _find_source_prefix(tf)
            tf.extractall(extract_dir)  # noqa: S202

        source = extract_dir / prefix
        return _install_local(source, target, tracker, force, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _is_remote_execution() -> bool:
    """True when run via stdin pipe (`curl ... | python -`) or `python -c`.

    When executed as a real file, `__file__` points at this script, so we install
    from the local clone. When piped or eval'd, `__file__` is absent or a marker
    such as ``<stdin>`` / ``-c``, so we must download the pack instead.
    """
    file_ref = globals().get("__file__")
    if not file_ref:
        return True
    return file_ref in ("<stdin>", "-c", "<string>")


def run(
    target: str,
    tracker: str = "local",
    dry_run: bool = False,
    force: bool = False,
    remote: Optional[bool] = None,
) -> int:
    """Install the pack into *target*.

    Public entry point so both `install.py` and `sdlc.py install` share one
    implementation. ``remote=None`` auto-detects the execution mode.
    """
    target_path = Path(target).resolve()
    if remote is None:
        remote = _is_remote_execution()
    if remote:
        return _install_remote(target_path, tracker, force, dry_run)
    source = Path(__file__).resolve().parent
    return _install_local(source=source, target=target_path, tracker=tracker, force=force, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SDLCOrchestrAI bootstrap installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--target", "-t",
        default=os.getcwd(),
        help="Target repository directory (default: current directory)",
    )
    parser.add_argument(
        "--tracker",
        choices=["local", "github"],
        default="local",
        help="Tracker mode written to .sdlc/config.yaml (default: local - no auth required)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview only; writes nothing (re-run without --dry-run to install)",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing files (default: skip existing)",
    )
    args = parser.parse_args()

    return run(
        target=args.target,
        tracker=args.tracker,
        dry_run=args.dry_run,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
