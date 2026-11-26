#!/usr/bin/env python3
"""
sdlc - Universal cross-platform CLI runner and validator for SDLCOrchestrAI.

Provides:
  python scripts/sdlc.py check-env [--json] [--strict] (aliases: check, doctor, preflight, soundcheck)
  python scripts/sdlc.py verify [--gate GATE] [--feature FEATURE] [--json]
  python scripts/sdlc.py resume [--client CLIENT]
  python scripts/sdlc.py checkpoint --feature FEATURE [options]
  python scripts/sdlc.py init
  python scripts/sdlc.py render
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def find_repo_root() -> Path:
    """Find the root directory of the git repository or fallback to current directory."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(res.stdout.strip())
    except Exception:
        # Walk up from script location or cwd
        current = Path(__file__).resolve().parent
        while current != current.parent:
            if (current / ".sdlc").exists() or (current / ".git").exists():
                return current
            current = current.parent
        return Path.cwd()


ROOT = find_repo_root()
SDLC_DIR = ROOT / ".sdlc"
STATE_FILE = SDLC_DIR / "state.json"
HANDOFF_FILE = SDLC_DIR / "HANDOFF.md"
MEMORY_DIR = SDLC_DIR / "memory"
SCHEMA_DIR = SDLC_DIR / "schema"
CONFIG_FILE = SDLC_DIR / "config.yaml"
CODEBASE_MAP = MEMORY_DIR / "codebase-map.md"


def cli_prefix() -> str:
    """Return the runnable invocation prefix for this CLI.

    There is no global ``sdlc`` command; users run the script (or a wrapper).
    Hints must therefore show a command that can be copy-pasted.
    """
    script = "scripts\\sdlc.py" if sys.platform == "win32" else "scripts/sdlc.py"
    return f"python {script}"


PHASES = [
    "requirements",
    "design",
    "threat-model",
    "backlog",
    "issues",
    "build",
    "implementation",
    "security-review",
    "done",
]
GATE_STATUSES = ["pending", "in-review", "approved", "skipped"]


def run_cmd(args: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Run a command safely and return (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"Command not found: {args[0]}"
    except Exception as e:
        return 1, "", str(e)


def parse_simple_yaml(path: Path) -> Dict[str, Any]:
    """Lightweight YAML parser for key-value and nested maps without external PyYAML."""
    if not path.is_file():
        return {}
    data: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, data)]
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("- "):
                    continue
                if " #" in line:
                    line = line.split(" #", 1)[0].strip()
                if ":" not in line:
                    continue
                indent = len(raw_line) - len(raw_line.lstrip(" \t"))
                while len(stack) > 1 and indent <= stack[-1][0]:
                    stack.pop()
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                target = stack[-1][1]
                if v == "":
                    child: Dict[str, Any] = {}
                    target[k] = child
                    stack.append((indent, child))
                else:
                    target[k] = v
        return data
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Command: check-env (doctor / preflight / soundcheck)
# ---------------------------------------------------------------------------

def check_env(json_output: bool = False, strict: bool = False) -> int:
    """Run comprehensive environment and prerequisite diagnostics."""
    results: List[Dict[str, Any]] = []

    def record(name: str, status: str, message: str, details: Optional[Dict[str, Any]] = None):
        results.append({
            "name": name,
            "status": status,  # "ok", "warn", "fail"
            "message": message,
            "details": details or {},
        })

    # 1. Git Repository
    code, out, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
    if code == 0 and out == "true":
        _, branch, _ = run_cmd(["git", "branch", "--show-current"])
        _, sha, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"])
        _, dirty_out, _ = run_cmd(["git", "status", "--porcelain"])
        is_dirty = bool(dirty_out.strip())
        record("git", "ok", f"Git repository initialized (branch: '{branch or 'detached'}', HEAD: {sha}, dirty: {is_dirty})", {
            "branch": branch,
            "head_sha": sha,
            "dirty": is_dirty,
        })
    else:
        record("git", "fail", "Not inside a valid Git repository")

    # 2. Python Runtime
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 8):
        record("python", "ok", f"Python runtime {py_ver} ({sys.executable})", {"version": py_ver})
    else:
        record("python", "fail", f"Python version {py_ver} is too old (requires >= 3.8)")

    # 3. .sdlc configuration & Tracker
    config = parse_simple_yaml(CONFIG_FILE)
    if CONFIG_FILE.is_file():
        tracker = config.get("tracker", "github")
        record("config", "ok", f"Tracker configured: '{tracker}' ({CONFIG_FILE.relative_to(ROOT)})", config)
    else:
        record("config", "warn", f"Missing {CONFIG_FILE.relative_to(ROOT)}; tracker defaults to github")
        tracker = "github"

    # 4. Tracker client (per adapter)
    if tracker == "github":
        code, out, _ = run_cmd(["gh", "--version"])
        if code == 0:
            first_line = out.splitlines()[0] if out else "gh installed"
            code_auth, auth_out, auth_err = run_cmd(["gh", "auth", "status"])
            if code_auth == 0:
                record("gh_cli", "ok", f"{first_line} (authenticated)", {"version_line": first_line})
            else:
                record("gh_cli", "warn", f"{first_line} installed but not authenticated (`gh auth login` required)", {"auth_err": auth_err or auth_out})
        else:
            record("gh_cli", "warn", "GitHub CLI (`gh`) not found in PATH; required for push-backlog.sh")
    elif tracker == "local":
        local_cfg = config.get("local") if isinstance(config.get("local"), dict) else {}
        out_dir = (local_cfg or {}).get("output_dir") or "docs/backlog/tickets"
        code_jq, out_jq, _ = run_cmd(["jq", "--version"])
        if code_jq == 0:
            record("tracker_local", "ok", f"Local Markdown tracker -> {out_dir} ({out_jq})", {"output_dir": out_dir})
        else:
            record("tracker_local", "warn", f"Local tracker configured but jq is missing; ticket files cannot be written (output_dir: {out_dir})")
    else:
        record("tracker", "warn", f"Tracker '{tracker}' has no adapter yet; use github or local (or set SDLC_TRACKER)")

    # 5. SDLC Schemas
    expected_schemas = [
        "backlog.schema.json",
        "findings.schema.json",
        "requirements-index.schema.json",
        "split-plan.schema.json",
        "state.schema.json",
    ]
    missing_schemas = []
    invalid_schemas = []
    for s in expected_schemas:
        sp = SCHEMA_DIR / s
        if not sp.is_file():
            missing_schemas.append(s)
        else:
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:
                invalid_schemas.append(f"{s}: {e}")

    if not missing_schemas and not invalid_schemas:
        record("schemas", "ok", f"All {len(expected_schemas)} core schemas valid in .sdlc/schema/")
    elif missing_schemas:
        record("schemas", "fail", f"Missing schema files: {', '.join(missing_schemas)}")
    else:
        record("schemas", "fail", f"Invalid JSON in schemas: {'; '.join(invalid_schemas)}")

    # 6. SDLC Shared State & Memory
    if STATE_FILE.is_file():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            feat_count = len(state_data.get("features", {}))
            record("state", "ok", f"State file valid ({feat_count} feature(s) tracked)")
        except Exception as e:
            record("state", "fail", f"Invalid JSON in {STATE_FILE}: {e}")
    else:
        record("state", "warn", f"No .sdlc/state.json found (run `{cli_prefix()} init`)")

    if CODEBASE_MAP.is_file():
        record("codebase_map", "ok", "Codebase map present (.sdlc/memory/codebase-map.md)")
    else:
        record("codebase_map", "warn", f"Missing .sdlc/memory/codebase-map.md (run `{cli_prefix()} init`)")

    # 7. Stack SDKs (.NET & Node)
    code_dn, out_dn, _ = run_cmd(["dotnet", "--version"])
    if code_dn == 0:
        record("dotnet", "ok", f".NET SDK installed ({out_dn})")
    else:
        record("dotnet", "warn", ".NET SDK (`dotnet`) not found in PATH")

    code_node, out_node, _ = run_cmd(["node", "--version"])
    if code_node == 0:
        record("node", "ok", f"Node.js installed ({out_node})")
    else:
        record("node", "warn", "Node.js (`node`) not found in PATH")

    # 8. Security Scanners (respecting .sdlc/config.yaml security.scanners)
    sec_cfg = config.get("security") if isinstance(config.get("security"), dict) else {}
    sec_scanners = sec_cfg.get("scanners") if isinstance(sec_cfg.get("scanners"), dict) else {}
    is_win = sys.platform == "win32"
    is_mac = sys.platform == "darwin"
    install_cmd_map = {
        "semgrep": "pip install semgrep",
        "gitleaks": "winget install Gitleaks.Gitleaks" if is_win else ("brew install gitleaks" if is_mac else "https://github.com/gitleaks/gitleaks/releases"),
        "trivy": "winget install AquaSecurity.Trivy" if is_win else ("brew install trivy" if is_mac else "https://trivy.dev/latest/getting-started/installation/"),
        "osv-scanner": "winget install Google.OSVScanner" if is_win else ("brew install osv-scanner" if is_mac else "go install github.com/google/osv-scanner/v2/cmd/osv-scanner@latest"),
        "zizmor": "pip install zizmor",
    }
    sec_tools = []
    missing_sec_tools = []
    required_missing = []
    disabled_sec_tools = []
    missing_hints: Dict[str, str] = {}
    for tool_name, cfg_key, check_args in [
        ("semgrep", "semgrep", ["semgrep", "--version"]),
        ("gitleaks", "gitleaks", ["gitleaks", "version"]),
        ("trivy", "trivy", ["trivy", "--version"]),
        ("osv-scanner", "osv_scanner", ["osv-scanner", "--version"]),
        ("zizmor", "zizmor", ["zizmor", "--version"]),
    ]:
        mode = str(sec_scanners.get(cfg_key, "auto")).lower()
        if mode == "disabled":
            disabled_sec_tools.append(tool_name)
            continue
        code, out, _ = run_cmd(check_args)
        if code == 0:
            first_line = out.splitlines()[0] if out else tool_name
            sec_tools.append(f"{tool_name} ({first_line})")
        else:
            missing_hints[tool_name] = install_cmd_map[tool_name]
            if mode == "enabled":
                required_missing.append(tool_name)
                missing_sec_tools.append(f"{tool_name} [REQUIRED]")
            else:
                missing_sec_tools.append(tool_name)

    sec_details = {"install_hints": missing_hints} if missing_hints else {}
    if required_missing:
        record("security_tools", "fail", f"Required scanner(s) missing or failed: {', '.join(required_missing)}", sec_details)
    elif sec_tools:
        msg = f"Available: {', '.join(sec_tools)}"
        if missing_sec_tools:
            msg += f" (missing: {', '.join(missing_sec_tools)}; fallback/skip used)"
        if disabled_sec_tools:
            msg += f" (disabled: {', '.join(disabled_sec_tools)})"
        record("security_tools", "ok", msg, sec_details)
    elif missing_sec_tools:
        record("security_tools", "warn", f"None of the configured scanners found ({', '.join(missing_sec_tools)}); heuristic fallback will be used", sec_details)
    else:
        record("security_tools", "ok", f"All security scanners disabled in .sdlc/config.yaml ({', '.join(disabled_sec_tools)})")
    record("sarif", "ok", f"SARIF 2.1.0 reports -> .sdlc/reports/<feature>-findings.sarif (run `{cli_prefix()} scan --feature <slug>`)")

    # Output Rendering
    if json_output:
        has_fail = any(r["status"] == "fail" for r in results)
        has_warn = any(r["status"] == "warn" for r in results)
        status_str = "FAILED" if has_fail else ("WARNINGS" if has_warn else "OK")
        print(json.dumps({"overall_status": status_str, "checks": results}, indent=2))
        return 1 if (has_fail or (strict and has_warn)) else 0

    print("\n========================================================")
    print("         SDLCOrchestrAI Environment Diagnostic          ")
    print("========================================================\n")

    symbols = {"ok": "[✓]", "warn": "[!]", "fail": "[✗]"}
    has_fail = False
    has_warn = False

    for r in results:
        sym = symbols.get(r["status"], "[?]")
        print(f" {sym} {r['name'].upper():<16} : {r['message']}")
        if r["name"] == "security_tools" and r["details"].get("install_hints"):
            print("     Install missing scanners (or set to 'disabled' in .sdlc/config.yaml):")
            for tool_name, hint in r["details"]["install_hints"].items():
                print(f"       - {tool_name:<12}: {hint}")
        if r["status"] == "fail":
            has_fail = True
        elif r["status"] == "warn":
            has_warn = True

    print("\n--------------------------------------------------------")
    if has_fail:
        print(" Status: ACTION REQUIRED (One or more critical checks failed)")
        print("--------------------------------------------------------\n")
        return 1
    elif has_warn:
        print(" Status: READY WITH WARNINGS (Recommended tools missing)")
        print("--------------------------------------------------------\n")
        return 1 if strict else 0
    else:
        print(" Status: READY FOR SDLC WORKFLOW")
        print("--------------------------------------------------------\n")
        return 0


# ---------------------------------------------------------------------------
# Command: verify (pre-flight gate verification)
# ---------------------------------------------------------------------------

def verify_requirements(feature: Optional[str] = None) -> List[Dict[str, Any]]:
    """Validate requirements documents: ID formats, uniqueness, acceptance criteria."""
    findings = []
    req_dir = ROOT / "docs" / "requirements"
    if not req_dir.is_dir():
        findings.append({"level": "warn", "file": str(req_dir), "message": "docs/requirements/ directory not found"})
        return findings

    # Find candidate files
    if feature:
        # Check single file or pack
        targets = [req_dir / f"{feature}.md", req_dir / feature / "00-index.md"]
        target_files = [t for t in targets if t.is_file()]
        if not target_files:
            findings.append({"level": "fail", "file": str(req_dir / feature), "message": f"Requirements file or pack for '{feature}' not found"})
            return findings
    else:
        target_files = list(req_dir.glob("*.md")) + list(req_dir.glob("*/00-index.md"))

    id_regex = re.compile(r"\b(REQ-(?:[A-Z0-9]+-)?\d{3})\b")

    for fpath in target_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            findings.append({"level": "fail", "file": str(fpath), "message": f"Could not read file: {e}"})
            continue

        ids_found = id_regex.findall(content)
        if not ids_found:
            findings.append({"level": "warn", "file": str(fpath.relative_to(ROOT)), "message": "No requirement IDs (matching REQ-NNN or REQ-SLICE-NNN) found"})
            continue

        # Check duplicates
        seen = set()
        duplicates = set()
        for rid in ids_found:
            if rid in seen:
                duplicates.add(rid)
            seen.add(rid)

        if duplicates:
            findings.append({
                "level": "fail",
                "file": str(fpath.relative_to(ROOT)),
                "message": f"Duplicate requirement IDs detected: {', '.join(sorted(duplicates))}"
            })
        else:
            findings.append({
                "level": "ok",
                "file": str(fpath.relative_to(ROOT)),
                "message": f"{len(seen)} requirement IDs defined and unique"
            })

    return findings


def verify_backlog(feature: Optional[str] = None) -> List[Dict[str, Any]]:
    """Validate backlog JSON files against schema structure (schema/backlog.schema.json)."""
    findings = []
    backlog_dir = ROOT / "docs" / "backlog"
    if not backlog_dir.is_dir():
        return findings

    if feature:
        target_files = [backlog_dir / f"{feature}-backlog.json"]
    else:
        target_files = list(backlog_dir.glob("*-backlog.json"))

    for fpath in target_files:
        if not fpath.is_file():
            if feature:
                findings.append({"level": "fail", "file": str(fpath.relative_to(ROOT) if fpath.is_relative_to(ROOT) else fpath), "message": f"Backlog JSON for '{feature}' not found"})
            continue

        rel_path = str(fpath.relative_to(ROOT))
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            findings.append({"level": "fail", "file": rel_path, "message": f"Invalid JSON: {e}"})
            continue

        # Schema assertions
        if data.get("schema_version") != 1:
            findings.append({"level": "warn", "file": rel_path, "message": f"Expected schema_version: 1, found: {data.get('schema_version')}"})

        feat_name = data.get("feature")
        if not feat_name:
            findings.append({"level": "fail", "file": rel_path, "message": "Missing required field 'feature'"})

        items = data.get("items", [])
        if not isinstance(items, list) or not items:
            findings.append({"level": "warn", "file": rel_path, "message": "No 'items' array defined or empty"})
            continue

        item_ids = set()
        duplicate_ids = set()
        story_count = 0
        missing_ac = 0
        valid_types = {"epic", "story", "task", "spike"}

        for item in items:
            iid = item.get("id")
            itype = item.get("type")
            title = item.get("title")

            if not iid or not itype or not title:
                findings.append({"level": "fail", "file": rel_path, "message": f"Item missing required fields (id, type, title): {item}"})
                continue

            if iid in item_ids:
                duplicate_ids.add(iid)
            item_ids.add(iid)

            if itype not in valid_types:
                findings.append({"level": "warn", "file": rel_path, "message": f"Item '{iid}' has unknown type '{itype}' (expected: {', '.join(sorted(valid_types))})"})

            if itype == "story":
                story_count += 1
                ac = item.get("acceptance_criteria", [])
                if not ac or not isinstance(ac, list) or len(ac) == 0:
                    missing_ac += 1

        if duplicate_ids:
            findings.append({"level": "fail", "file": rel_path, "message": f"Duplicate item IDs in backlog: {', '.join(sorted(duplicate_ids))}"})

        if missing_ac > 0:
            findings.append({"level": "warn", "file": rel_path, "message": f"{missing_ac} of {story_count} stories missing acceptance criteria"})
        elif story_count > 0:
            findings.append({"level": "ok", "file": rel_path, "message": f"Backlog valid: {len(items)} items ({story_count} stories with acceptance criteria)"})
        else:
            findings.append({"level": "ok", "file": rel_path, "message": f"Backlog valid: {len(items)} items"})

        # Cross-document REQ-ID coverage check against requirements
        req_file = ROOT / "docs" / "requirements" / f"{feat_name}.md"
        if req_file.is_file():
            req_ids = set(re.findall(r"\b(REQ-(?:[A-Z0-9]+-)?\d{3})\b", req_file.read_text(encoding="utf-8", errors="replace")))
            covered_reqs = set()
            for item in items:
                for ref in item.get("req_refs", []) or []:
                    covered_reqs.add(ref)
            uncovered = sorted(req_ids - covered_reqs)
            if uncovered:
                findings.append({"level": "fail", "file": rel_path, "message": f"Uncovered requirement IDs missing from backlog req_refs: {', '.join(uncovered)}"})
            elif req_ids:
                findings.append({"level": "ok", "file": rel_path, "message": f"All {len(req_ids)} requirement ID(s) covered by backlog items"})

    return findings


def verify_design(feature: Optional[str] = None) -> List[Dict[str, Any]]:
    """Validate design documents: existence, REQ-ID coverage, and core sections."""
    findings = []
    design_dir = ROOT / "docs" / "design"
    req_dir = ROOT / "docs" / "requirements"
    if not design_dir.is_dir():
        return findings

    if feature:
        candidates = [feature]
    else:
        candidates = []
        if req_dir.is_dir():
            for rf in sorted(req_dir.glob("*.md")):
                if (design_dir / rf.name).is_file():
                    candidates.append(rf.stem)

    for feat in candidates:
        dfile = design_dir / f"{feat}.md"
        if not dfile.is_file():
            findings.append({"level": "fail", "file": f"docs/design/{feat}.md", "message": f"Design document for '{feat}' not found"})
            continue

        rel_path = str(dfile.relative_to(ROOT))
        content = dfile.read_text(encoding="utf-8", errors="replace")

        rfile = req_dir / f"{feat}.md"
        if rfile.is_file():
            req_ids = set(re.findall(r"\b(REQ-(?:[A-Z0-9]+-)?\d{3})\b", rfile.read_text(encoding="utf-8", errors="replace")))
            design_ids = set(re.findall(r"\b(REQ-(?:[A-Z0-9]+-)?\d{3})\b", content))
            missing = sorted(req_ids - design_ids)
            if missing:
                findings.append({"level": "fail", "file": rel_path, "message": f"Requirement IDs not referenced in design: {', '.join(missing)}"})
            elif req_ids:
                findings.append({"level": "ok", "file": rel_path, "message": f"All {len(req_ids)} requirement ID(s) referenced in design"})

        lower = content.lower()
        missing_sections = [
            label for label, keys in [
                ("Architecture/Components", ("architecture", "component")),
                ("Data Model/API", ("data model", "schema", "api")),
                ("Risks/Rollback", ("risk", "rollback")),
            ]
            if not any(k in lower for k in keys)
        ]
        if missing_sections:
            findings.append({"level": "warn", "file": rel_path, "message": f"Design missing recommended sections: {', '.join(missing_sections)}"})
        else:
            findings.append({"level": "ok", "file": rel_path, "message": "Design sections complete"})

    return findings


def verify_implementation() -> List[Dict[str, Any]]:
    """Validate active implementation branch, working tree, and test files."""
    findings = []
    # Check current branch
    code, branch, _ = run_cmd(["git", "branch", "--show-current"])
    if code == 0:
        if branch.startswith("feat/") or branch.startswith("feature/"):
            findings.append({"level": "ok", "file": f"git:branch({branch})", "message": f"Active feature branch: {branch}"})
        elif branch in ["main", "master"]:
            findings.append({"level": "warn", "file": f"git:branch({branch})", "message": "Currently on default branch; story implementation should occur on feat/* branch"})
        else:
            findings.append({"level": "ok", "file": f"git:branch({branch})", "message": f"Working branch: {branch}"})

    # Check git dirty status
    code, dirty_out, _ = run_cmd(["git", "status", "--porcelain"])
    dirty_lines = [l for l in dirty_out.splitlines() if not (".sdlc/" in l or ".sdlc\\" in l)]
    if dirty_lines:
        findings.append({"level": "warn", "file": "git:working-tree", "message": f"{len(dirty_lines)} uncommitted file(s) in working tree"})
    else:
        findings.append({"level": "ok", "file": "git:working-tree", "message": "Working tree clean"})

    # Check for test files in repo
    test_files = list(ROOT.rglob("*Tests.cs")) + list(ROOT.rglob("*Test.cs")) + \
                 list(ROOT.rglob("*.test.ts")) + list(ROOT.rglob("*.test.tsx")) + \
                 list(ROOT.rglob("*.spec.ts")) + list(ROOT.rglob("*.spec.tsx")) + \
                 list(ROOT.rglob("test_*.py")) + list(ROOT.rglob("*_test.py"))
    test_files = [f for f in test_files if not any(part.startswith(".") for part in f.parts)]
    if test_files:
        findings.append({"level": "ok", "file": "tests", "message": f"Found {len(test_files)} test file(s) in repository"})
    else:
        findings.append({"level": "warn", "file": "tests", "message": "No test files detected (*Tests.cs, *.test.ts(x), *.spec.ts(x), test_*.py)"})

    return findings


def find_story(story_id: str, feature: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Path]]:
    """Find a story by ID across backlog files or templates."""
    backlog_dir = ROOT / "docs" / "backlog"
    candidates = []
    if feature:
        bf = backlog_dir / f"{feature}-backlog.json"
        if bf.is_file():
            candidates.append(bf)
    else:
        if backlog_dir.is_dir():
            candidates.extend(sorted(backlog_dir.glob("*-backlog.json")))

    example_bf = ROOT / "skills" / "sdlc-backlog-breakdown" / "templates" / "backlog.example.json"
    if example_bf.is_file() and example_bf not in candidates:
        candidates.append(example_bf)

    for cf in candidates:
        try:
            with open(cf, "r", encoding="utf-8") as f:
                data = json.load(f)
            feat_name = data.get("feature", cf.stem.replace("-backlog", ""))
            for item in data.get("items", []):
                if item.get("id", "").lower() == story_id.lower():
                    return item, feat_name, cf
        except Exception:
            continue

    return None, None, None


def cmd_story_show(story_id: str, feature: Optional[str] = None, json_output: bool = False) -> int:
    """Display story details, acceptance criteria, requirement refs, and design links."""
    story, feat_name, path = find_story(story_id, feature)
    if not story:
        print(f"ERROR: Story '{story_id}' not found in backlog files.", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps({"feature": feat_name, "story": story}, indent=2))
        return 0

    print("\n========================================================")
    print(f" Story: {story.get('id')} - {story.get('title')}")
    print(f" Feature: {feat_name} | Type: {story.get('type')} | Estimate: {story.get('estimate', 'N/A')} pts | Priority: {story.get('priority', 'N/A')}")
    print("========================================================\n")

    if story.get("user_story"):
        print(f" User Story:\n   {story.get('user_story')}\n")

    acs = story.get("acceptance_criteria", [])
    if acs:
        print(" Acceptance Criteria:")
        for idx, ac in enumerate(acs, 1):
            print(f"   {idx}. {ac}")
        print()

    reqs = story.get("req_refs", [])
    if reqs:
        print(f" Requirement Refs : {', '.join(reqs)}")

    dref = story.get("design_ref")
    if dref:
        print(f" Design Reference : {dref}")

    ext = story.get("external", {})
    if ext and ext.get("key"):
        print(f" Tracker Issue    : {ext.get('key')} ({ext.get('url', '')})")

    deps = story.get("depends_on", [])
    if deps:
        print(f" Depends On       : {', '.join(deps)}")

    print("\n--------------------------------------------------------")
    return 0


def cmd_story_start(story_id: str, feature: Optional[str] = None) -> int:
    """Start implementation of a story: create feature branch and record checkpoint."""
    story, feat_name, path = find_story(story_id, feature)
    if not story:
        print(f"ERROR: Story '{story_id}' not found in backlog files.", file=sys.stderr)
        return 1

    title = story.get("title", "")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30]

    ext = story.get("external", {})
    issue_num = ext.get("key", "").lstrip("#")
    prefix = issue_num if issue_num else story.get("id", "").lower()
    branch_name = f"feat/{prefix}-{slug}"

    print(f"Starting implementation for Story {story.get('id')} ({title})")
    print(f"Target branch: {branch_name}")

    # Check git status
    code, dirty_out, _ = run_cmd(["git", "status", "--porcelain"])
    dirty_lines = [l for l in dirty_out.splitlines() if not (".sdlc/" in l or ".sdlc\\" in l)]
    if dirty_lines:
        print(f"NOTE: Working tree has {len(dirty_lines)} uncommitted change(s).")

    # Checkout branch
    code_co, out_co, err_co = run_cmd(["git", "checkout", "-b", branch_name])
    if code_co != 0:
        code_sw, _, _ = run_cmd(["git", "checkout", branch_name])
        if code_sw == 0:
            print(f"Switched to existing branch: {branch_name}")
        else:
            print(f"NOTE: Git branch create notice: {err_co or out_co}")
    else:
        print(f"Created and checked out: {branch_name}")

    # Record checkpoint in state.json
    cmd_checkpoint(
        feature=feat_name or "feature",
        phase="build",
        branch=branch_name,
        note=f"Started story {story.get('id')}: {title}",
        next_action=f"Scaffold tests for {story.get('id')} acceptance criteria, then implement code."
    )
    return 0


def cmd_story_pr_body(story_id: str, feature: Optional[str] = None, output_file: Optional[str] = None) -> int:
    """Generate markdown PR description populated from story metadata."""
    story, feat_name, path = find_story(story_id, feature)
    if not story:
        print(f"ERROR: Story '{story_id}' not found in backlog files.", file=sys.stderr)
        return 1

    ext = story.get("external", {})
    issue_num = ext.get("key", "")
    closes_str = f"Closes {issue_num}" if issue_num else f"Refs Story `{story.get('id')}`"

    acs = story.get("acceptance_criteria", [])
    ac_checklist = "\n".join(f"- [x] {ac}" for ac in acs) if acs else "- [ ] Acceptance criteria satisfied"

    reqs = story.get("req_refs", [])
    dref = story.get("design_ref", "docs/design/")
    if reqs:
        rows = "\n".join(f"| {r} | `{dref}` | Unit & integration tests |" for r in reqs)
    else:
        rows = f"| N/A | `{dref}` | Unit tests |"

    tmpl_path = ROOT / "skills" / "sdlc-feature-implementer" / "templates" / "pr-description.md.tmpl"
    if tmpl_path.is_file():
        body = tmpl_path.read_text(encoding="utf-8")
        body = body.replace("${CLOSES_ISSUE}", closes_str)
        body = body.replace("${STORY_ID}", story.get("id", "E1-S1"))
        body = body.replace("${STORY_TITLE}", story.get("title", ""))
        body = body.replace("${FEATURE}", feat_name or "feature")
        body = body.replace("${TRACEABILITY_ROWS}", rows)
        body = body.replace("${AC_CHECKLIST}", ac_checklist)
    else:
        body = f"## Summary\n{closes_str}\nImplements Story: `{story.get('id')}` - {story.get('title')}\n\n## Acceptance Criteria\n{ac_checklist}\n"

    if output_file:
        out_p = Path(output_file)
        if not out_p.is_absolute():
            out_p = ROOT / out_p
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(body, encoding="utf-8")
        print(f"Generated PR description -> {out_p.relative_to(ROOT) if out_p.is_relative_to(ROOT) else out_p}")
    else:
        print(body)

    return 0


def verify_gate(gate: Optional[str] = None, feature: Optional[str] = None, json_output: bool = False) -> int:
    """Run gate verification checks."""
    all_findings = []

    if not gate or gate in ["requirements", "all"]:
        all_findings.extend(verify_requirements(feature))

    if not gate or gate in ["design", "all"]:
        all_findings.extend(verify_design(feature))

    if not gate or gate in ["backlog", "all"]:
        all_findings.extend(verify_backlog(feature))

    if not gate or gate in ["implementation", "all"]:
        all_findings.extend(verify_implementation())

    if json_output:
        has_fail = any(f["level"] == "fail" for f in all_findings)
        print(json.dumps({"findings": all_findings, "status": "FAIL" if has_fail else "PASS"}, indent=2))
        return 1 if has_fail else 0

    print("\n========================================================")
    print(f"         SDLC Pre-Flight Gate Verification              ")
    print(f"         Target Gate: {gate or 'all'} | Feature: {feature or 'all'}")
    print("========================================================\n")

    symbols = {"ok": "[✓]", "warn": "[!]", "fail": "[✗]"}
    has_fail = False
    for f in all_findings:
        sym = symbols.get(f["level"], "[?]")
        print(f" {sym} {f['file']:<35} : {f['message']}")
        if f["level"] == "fail":
            has_fail = True

    if not all_findings:
        print(" (No matching artifacts found to verify)")

    print("\n--------------------------------------------------------")
    print(" Result: " + ("FAILED" if has_fail else "PASSED"))
    print("--------------------------------------------------------\n")
    return 1 if has_fail else 0


# ---------------------------------------------------------------------------
# Command: resume & checkpoint (state management)
# ---------------------------------------------------------------------------

def cmd_resume(client: Optional[str] = None) -> int:
    """Print handoff state, repo divergence, and next actions."""
    if not STATE_FILE.is_file():
        print(f"No .sdlc/state.json found. Run `{cli_prefix()} init` to initialize.")
        return 1

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    _, head_sha, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"])
    _, dirty_out, _ = run_cmd(["git", "status", "--porcelain"])
    # filter out .sdlc
    dirty_lines = [l for l in dirty_out.splitlines() if not (".sdlc/" in l or ".sdlc\\" in l)]
    is_dirty = bool(dirty_lines)

    recorded_sha = state.get("repo_sha", "none")
    sha_status = "matches HEAD" if recorded_sha == head_sha else f"diverged from HEAD (recorded: {recorded_sha}, current: {head_sha})"

    print(f"\n[SDLC Session Resume]")
    print(f"Client: {client or state.get('updated_by', 'unknown')}")
    print(f"Last updated: {state.get('updated_at', 'never')} by {state.get('updated_by', 'unknown')}")
    print(f"Repository SHA: {sha_status} (uncommitted changes: {is_dirty})\n")

    features = state.get("features", {})
    if not features:
        print("(No active features recorded in state.json)")
    else:
        for fname, fmeta in features.items():
            print(f"## Feature: {fname} (Phase: {fmeta.get('phase', 'requirements')})")
            print(f"   Next Action : {fmeta.get('next_action', 'none recorded')}")
            gates = fmeta.get("gates", {})
            if gates:
                gate_str = ", ".join(f"{k}={v}" for k, v in gates.items())
                print(f"   Gates       : {gate_str}")
            qs = fmeta.get("open_questions", [])
            if qs:
                print(f"   Questions   : {len(qs)} open question(s)")
                for q in qs:
                    print(f"     - {q}")
            arts = fmeta.get("artifacts", [])
            if arts:
                print(f"   Artifacts   : {', '.join(arts)}")
            print()

    return 0


def cmd_install(target: str, tracker: str = "local", dry_run: bool = False, force: bool = False) -> int:
    """Delegate to the standalone install.py bootstrap installer (single source of truth)."""
    import importlib.util

    installer_path = ROOT / "install.py"
    if not installer_path.is_file():
        print(f"ERROR: installer not found at {installer_path}", file=sys.stderr)
        return 1

    spec = importlib.util.spec_from_file_location("sdlc_installer", installer_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run(target=target, tracker=tracker, dry_run=dry_run, force=force, remote=False)


def cmd_init() -> int:
    """Initialize .sdlc/ structure if missing."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    (SDLC_DIR / "reports").mkdir(parents=True, exist_ok=True)

    if not STATE_FILE.is_file():
        init_state = {"schema_version": 1, "features": {}}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(init_state, f, indent=2)
        print(f"Created {STATE_FILE.relative_to(ROOT)}")

    graph_file = MEMORY_DIR / "graph.jsonl"
    if not graph_file.is_file():
        graph_file.touch()

    if not CODEBASE_MAP.is_file():
        tmpl = ROOT / "skills" / "sdlc-session-handoff" / "templates" / "codebase-map.md.tmpl"
        if tmpl.is_file():
            CODEBASE_MAP.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            CODEBASE_MAP.write_text("<!-- map-sha: UNSET -->\n# Codebase map\n", encoding="utf-8")
        print(f"Created {CODEBASE_MAP.relative_to(ROOT)}")

    cmd_render()
    print("Initialized shared memory in .sdlc/ (state.json, HANDOFF.md, memory/).")
    return 0


def cmd_render() -> int:
    """Regenerate HANDOFF.md from state.json."""
    if not STATE_FILE.is_file():
        print(f"ERROR: {STATE_FILE} does not exist. Run `{cli_prefix()} init` first.", file=sys.stderr)
        return 1

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    lines = [
        "# Handoff",
        "",
        "_Generated from `.sdlc/state.json`. Do not edit by hand._",
        "",
        f"Last updated: {state.get('updated_at', 'never')} by {state.get('updated_by', 'unknown')} at commit {state.get('repo_sha', 'n/a')}"
        + (" (code had uncommitted changes)" if state.get("repo_dirty") else ""),
        "",
    ]

    features = state.get("features", {})
    if not features:
        lines.append("(No features recorded yet.)\n")
    else:
        for fname, fmeta in features.items():
            lines.append(f"## {fname} - phase: {fmeta.get('phase', 'n/a')}\n")
            lines.append(f"**Next action:** {fmeta.get('next_action', 'none recorded')}\n")

            gates = fmeta.get("gates", {})
            if gates:
                lines.append("| Gate | Status |")
                lines.append("|---|---|")
                for gk, gv in gates.items():
                    lines.append(f"| {gk} | {gv} |")
                lines.append("")

            qs = fmeta.get("open_questions", [])
            if qs:
                lines.append("**Open questions**")
                for q in qs:
                    lines.append(f"- {q}")
                lines.append("")

            arts = fmeta.get("artifacts", [])
            if arts:
                lines.append("**Artifacts**")
                for a in arts:
                    lines.append(f"- `{a}`")
                lines.append("")

            if fmeta.get("branch"):
                lines.append(f"**Branch:** `{fmeta.get('branch')}`\n")

            notes = fmeta.get("notes", [])
            if notes:
                lines.append("**Recent notes**")
                for n in notes:
                    lines.append(f"- {n.get('at')} ({n.get('by')}): {n.get('text')}")
                lines.append("")

    with open(HANDOFF_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return 0


def cmd_checkpoint(
    feature: str,
    client: str = "unknown",
    phase: Optional[str] = None,
    gates: Optional[List[str]] = None,
    artifacts: Optional[List[str]] = None,
    next_action: Optional[str] = None,
    questions: Optional[List[str]] = None,
    close_questions: Optional[List[str]] = None,
    slice_slug: Optional[str] = None,
    branch: Optional[str] = None,
    note: Optional[str] = None,
) -> int:
    """Record progress checkpoint and update shared memory."""
    if not STATE_FILE.is_file():
        cmd_init()

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        state = json.load(f)

    if phase and phase not in PHASES:
        print(f"ERROR: Phase must be one of: {', '.join(PHASES)}", file=sys.stderr)
        return 2

    # Parse gates
    gate_dict: Dict[str, str] = {}
    if gates:
        for g in gates:
            if "=" not in g:
                print(f"ERROR: --gate expects NAME=STATUS (e.g. design=approved)", file=sys.stderr)
                return 2
            gk, gv = g.split("=", 1)
            gk = gk.strip()
            gv = gv.strip()
            if gv not in GATE_STATUSES:
                print(f"ERROR: Gate status must be one of: {', '.join(GATE_STATUSES)}", file=sys.stderr)
                return 2
            if slice_slug:
                gk = f"{gk}:{slice_slug}"
            gate_dict[gk] = gv

    # Slice hashing
    slice_hash = ""
    if slice_slug:
        req_base = ROOT / os.environ.get("SDLC_REQ_DIR", "docs/requirements")
        slice_candidates = list((req_base / feature / "slices").glob(f"*-{slice_slug}.md")) + \
                           list((req_base / feature / "slices").glob(f"{slice_slug}.md"))
        if slice_candidates and slice_candidates[0].is_file():
            content = slice_candidates[0].read_bytes()
            slice_hash = hashlib.sha256(content).hexdigest()[:16]

    _, head_sha, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"])
    _, dirty_out, _ = run_cmd(["git", "status", "--porcelain"])
    dirty_lines = [l for l in dirty_out.splitlines() if not (".sdlc/" in l or ".sdlc\\" in l)]
    is_dirty = bool(dirty_lines)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    state["updated_by"] = client
    state["updated_at"] = now
    state["repo_sha"] = head_sha or "none"
    state["repo_dirty"] = is_dirty

    if "features" not in state or not isinstance(state["features"], dict):
        state["features"] = {}

    feat = state["features"].get(feature, {
        "phase": "requirements",
        "gates": {},
        "artifacts": [],
        "open_questions": [],
        "notes": [],
    })
    feat["updated_by"] = client
    feat["updated_at"] = now

    if phase:
        feat["phase"] = phase
    if next_action:
        feat["next_action"] = next_action
    if branch:
        feat["branch"] = branch
    if slice_slug and slice_hash:
        feat.setdefault("slice_hashes", {})[slice_slug] = slice_hash

    if gate_dict:
        feat.setdefault("gates", {}).update(gate_dict)

    if artifacts:
        curr_arts = set(feat.get("artifacts", []))
        curr_arts.update(artifacts)
        feat["artifacts"] = sorted(curr_arts)

    curr_qs = list(feat.get("open_questions", []))
    if questions:
        for q in questions:
            if q not in curr_qs:
                curr_qs.append(q)
    if close_questions:
        curr_qs = [q for q in curr_qs if q not in close_questions]
    feat["open_questions"] = curr_qs

    if note:
        notes = feat.get("notes", [])
        notes.append({"at": now, "by": client, "text": note})
        feat["notes"] = notes[-5:]

    state["features"][feature] = feat

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    cmd_render()
    print(f"Recorded checkpoint for '{feature}' (phase: {feat.get('phase')}, updated by: {client}).")
    return 0


def cmd_sync_skills(check: bool = False) -> int:
    """Publish canonical skills/ to client directories or check for drift."""
    import shutil
    src = ROOT / "skills"
    targets = [
        ROOT / ".claude" / "skills",
        ROOT / ".github" / "skills",
        ROOT / ".opencode" / "skills",
        ROOT / ".agent" / "skills",
    ]
    extra = os.environ.get("SDLC_SYNC_EXTRA", "").strip()
    if extra:
        for p in extra.split():
            targets.append(ROOT / p)

    drift = False

    def dir_diff(d1: Path, d2: Path) -> bool:
        if not d2.is_dir():
            return True
        files1 = {f.relative_to(d1): f for f in d1.rglob("*") if f.is_file()}
        files2 = {f.relative_to(d2): f for f in d2.rglob("*") if f.is_file()}
        if set(files1.keys()) != set(files2.keys()):
            return True
        for rel, f1 in files1.items():
            f2 = files2[rel]
            try:
                t1 = f1.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                t2 = f2.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
                if t1 != t2:
                    return True
            except Exception:
                if f1.read_bytes() != f2.read_bytes():
                    return True
        return False

    for tgt in targets:
        if check:
            if dir_diff(src, tgt):
                print(f"DRIFT: {tgt.relative_to(ROOT)} differs from skills/")
                drift = True
        else:
            if tgt.exists():
                shutil.rmtree(tgt)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, tgt)
            print(f"synced -> {tgt.relative_to(ROOT)}")

    # Cursor rules
    cursor_rules_dir = ROOT / ".cursor" / "rules"
    cursor_rules_dir.mkdir(parents=True, exist_ok=True)
    for sdir in sorted(src.iterdir()):
        if not sdir.is_dir():
            continue
        skill_name = sdir.name
        skill_file = sdir / "SKILL.md"
        desc = ""
        if skill_file.is_file():
            for line in skill_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("description:"):
                    desc = line.split("description:", 1)[1].strip().strip("\"'")
                    break
        mdc_content = f"""---
description: "{desc}"
alwaysApply: false
---
Follow the skill defined in `skills/{skill_name}/SKILL.md` (read it fully, plus any files it references
in `references/`, `templates/`, and `scripts/`). Shared rules and approval gates: @AGENTS.md
"""
        target_mdc = cursor_rules_dir / f"{skill_name}.mdc"
        if check:
            if not target_mdc.is_file() or target_mdc.read_text(encoding="utf-8").replace("\r\n", "\n") != mdc_content.replace("\r\n", "\n"):
                print(f"DRIFT: {target_mdc.relative_to(ROOT)} differs from generated stub")
                drift = True
        else:
            target_mdc.write_text(mdc_content, encoding="utf-8")

    if not check:
        print("generated -> .cursor/rules/*.mdc")

    if check:
        if drift:
            print(f"Run `{cli_prefix()} sync-skills` to synchronize.")
            return 1
        else:
            print("All client copies are in sync.")
            return 0
    return 0


def cmd_validate() -> int:
    """Validate state.json against schema and enum constraints."""
    if not STATE_FILE.is_file():
        print(f"ERROR: {STATE_FILE} does not exist", file=sys.stderr)
        return 1
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"ERROR: Invalid JSON in {STATE_FILE}: {e}", file=sys.stderr)
        return 1

    if data.get("schema_version") != 1:
        print("state.json: INVALID (schema_version must be 1)", file=sys.stderr)
        return 1

    features = data.get("features", {})
    if not isinstance(features, dict):
        print("state.json: INVALID (features must be an object)", file=sys.stderr)
        return 1

    for fname, fmeta in features.items():
        phase = fmeta.get("phase", "requirements")
        if phase not in PHASES:
            print(f"state.json: INVALID (feature '{fname}' has invalid phase '{phase}')", file=sys.stderr)
            return 1
        gates = fmeta.get("gates", {})
        if isinstance(gates, dict):
            for gk, gv in gates.items():
                if gv not in GATE_STATUSES:
                    print(f"state.json: INVALID (gate '{gk}' in '{fname}' has invalid status '{gv}')", file=sys.stderr)
                    return 1

    print("state.json: OK")
    return 0


def cmd_scan(feature: str, strict: bool = False) -> int:
    """Run the security scanners via the deterministic shell scripts, writing SARIF + JSON."""
    script = ROOT / "skills" / "sdlc-security-review" / "scripts" / "scan-all.sh"
    if not script.is_file():
        print(f"ERROR: scanner script not found: {script}", file=sys.stderr)
        return 1
    rel_script = script.relative_to(ROOT).as_posix()
    cmd = ["bash", rel_script, "--feature", feature]
    if strict:
        cmd.append("--strict")
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT))
    except FileNotFoundError:
        print("ERROR: bash not found; install Git Bash or WSL (or run the scripts directly)", file=sys.stderr)
        return 127
    return proc.returncode



def main():
    parser = argparse.ArgumentParser(
        prog="sdlc",
        description="SDLCOrchestrAI universal runner, environment diagnostic, and gate verifier",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Command to run")

    # check-env (with aliases check, doctor, preflight, soundcheck)
    for alias in ["check-env", "check", "doctor", "preflight", "soundcheck"]:
        p_check = subparsers.add_parser(alias, help="Run environment and prerequisites check")
        p_check.add_argument("--json", action="store_true", help="Output results in JSON format")
        p_check.add_argument("--strict", action="store_true", help="Return error code on warnings")

    # verify
    p_verify = subparsers.add_parser("verify", help="Run pre-flight gate verification on artifacts")
    p_verify.add_argument("--gate", choices=["requirements", "design", "backlog", "implementation", "all"], default="all", help="Target gate")
    p_verify.add_argument("--feature", help="Target feature name")
    p_verify.add_argument("--json", action="store_true", help="Output findings in JSON format")

    # scan
    p_scan = subparsers.add_parser("scan", help="Run security scanners and write SARIF + findings JSON")
    p_scan.add_argument("--feature", default=os.environ.get("SDLC_FEATURE", "repo"), help="Feature/report slug (default: repo)")
    p_scan.add_argument("--strict", action="store_true", help="Return error code when findings exist")

    # story
    p_story = subparsers.add_parser("story", help="Manage story implementation lifecycle")
    story_subs = p_story.add_subparsers(dest="story_action", help="Story action")

    # story show
    p_s_show = story_subs.add_parser("show", help="Show story details and acceptance criteria")
    p_s_show.add_argument("story_id", help="Story ID (e.g. E1-S1)")
    p_s_show.add_argument("--feature", help="Feature name (optional)")
    p_s_show.add_argument("--json", action="store_true", help="Output in JSON format")

    # story start
    p_s_start = story_subs.add_parser("start", help="Checkout branch and begin implementation")
    p_s_start.add_argument("story_id", help="Story ID (e.g. E1-S1)")
    p_s_start.add_argument("--feature", help="Feature name (optional)")

    # story pr-body
    p_s_pr = story_subs.add_parser("pr-body", help="Generate markdown PR description for story")
    p_s_pr.add_argument("story_id", help="Story ID (e.g. E1-S1)")
    p_s_pr.add_argument("--feature", help="Feature name (optional)")
    p_s_pr.add_argument("--output", help="Output file path (optional)")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume session and print handoff state")
    p_resume.add_argument("--client", default=os.environ.get("SDLC_CLIENT", "antigravity"), help="Client name")

    # checkpoint
    p_cp = subparsers.add_parser("checkpoint", help="Record progress checkpoint into .sdlc/state.json")
    p_cp.add_argument("--feature", required=True, help="Feature slug name")
    p_cp.add_argument("--client", default=os.environ.get("SDLC_CLIENT", "antigravity"), help="Client name")
    p_cp.add_argument("--phase", choices=PHASES, help="Current SDLC phase")
    p_cp.add_argument("--gate", action="append", help="Gate status in format NAME=STATUS (repeatable)")
    p_cp.add_argument("--artifact", action="append", help="Artifact path (repeatable)")
    p_cp.add_argument("--next", dest="next_action", help="Next action description")
    p_cp.add_argument("--question", action="append", help="Open question (repeatable)")
    p_cp.add_argument("--close-question", action="append", help="Close existing question (repeatable)")
    p_cp.add_argument("--slice", dest="slice_slug", help="Slice slug for scoped gate")
    p_cp.add_argument("--branch", help="Current git branch")
    p_cp.add_argument("--note", help="Note text to record")

    # sync-skills
    p_sync = subparsers.add_parser("sync-skills", help="Sync skills to all client directories")
    p_sync.add_argument("--check", action="store_true", help="Check for drift without copying")

    # install
    p_install = subparsers.add_parser("install", help="Copy SDLCOrchestrAI pack files into a target repository")
    p_install.add_argument("--target", "-t", default=os.getcwd(), help="Target repository directory (default: current directory)")
    p_install.add_argument("--tracker", choices=["local", "github"], default="local", help="Tracker mode for .sdlc/config.yaml (default: local)")
    p_install.add_argument("--dry-run", "-n", action="store_true", help="Preview only; writes nothing (re-run without --dry-run to install)")
    p_install.add_argument("--force", "-f", action="store_true", help="Overwrite existing files")

    # init
    subparsers.add_parser("init", help="Initialize .sdlc/ state and memory directories")

    # render
    subparsers.add_parser("render", help="Regenerate .sdlc/HANDOFF.md from state.json")

    # validate
    subparsers.add_parser("validate", help="Validate state.json against schema constraints")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    if args.subcommand in ["check-env", "check", "doctor", "preflight", "soundcheck"]:
        sys.exit(check_env(json_output=args.json, strict=args.strict))
    elif args.subcommand == "verify":
        sys.exit(verify_gate(gate=args.gate, feature=args.feature, json_output=args.json))
    elif args.subcommand == "scan":
        sys.exit(cmd_scan(feature=args.feature, strict=args.strict))
    elif args.subcommand == "story":
        if args.story_action == "show":
            sys.exit(cmd_story_show(story_id=args.story_id, feature=args.feature, json_output=args.json))
        elif args.story_action == "start":
            sys.exit(cmd_story_start(story_id=args.story_id, feature=args.feature))
        elif args.story_action == "pr-body":
            sys.exit(cmd_story_pr_body(story_id=args.story_id, feature=args.feature, output_file=args.output))
        else:
            p_story.print_help()
            sys.exit(1)
    elif args.subcommand == "resume":
        sys.exit(cmd_resume(client=args.client))
    elif args.subcommand == "checkpoint":
        sys.exit(cmd_checkpoint(
            feature=args.feature,
            client=args.client,
            phase=args.phase,
            gates=args.gate,
            artifacts=args.artifact,
            next_action=args.next_action,
            questions=args.question,
            close_questions=args.close_question,
            slice_slug=args.slice_slug,
            branch=args.branch,
            note=args.note,
        ))
    elif args.subcommand == "sync-skills":
        sys.exit(cmd_sync_skills(check=args.check))
    elif args.subcommand == "install":
        sys.exit(cmd_install(target=args.target, tracker=args.tracker, dry_run=args.dry_run, force=args.force))
    elif args.subcommand == "init":
        sys.exit(cmd_init())
    elif args.subcommand == "render":
        sys.exit(cmd_render())
    elif args.subcommand == "validate":
        sys.exit(cmd_validate())
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
