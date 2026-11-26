#!/usr/bin/env python3
"""scan.py - deterministic security scanners for the sdlc-security-review skill.

Python port of the former ``scan-*.sh`` scripts. Requires only Python 3.8+ and
``git``. External tools are optional and detected in PATH:

* secrets: gitleaks -> trufflehog -> labeled regex fallback
* sast:    semgrep  -> conservative heuristics; plus zizmor for GitHub Actions
* deps:    dotnet list --vulnerable, npm audit, osv-scanner
* iac:     trivy config

Scanner modes (``auto`` | ``enabled`` | ``disabled``) are read from
``.sdlc/config.yaml`` under ``security.scanners`` and can be overridden with
``SDLC_SEC_<NAME>`` (for example ``SDLC_SEC_SEMGREP=disabled``).

Usage:
    python scan.py [secrets|sast|deps|iac|all] [--feature SLUG] [--strict]

Outputs (never secret values):
    .sdlc/reports/<feature>-<scanner>.{json,sarif}
    .sdlc/reports/<feature>-findings.{json,sarif}

Exit codes: 0 normally; 1 when ``--strict`` / ``SDLC_STRICT=1`` and the invoked
scanner(s) produced findings; 2 on usage errors.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sarif  # noqa: E402  (same directory)

SCAN_TIMEOUT = int(os.environ.get("SDLC_SCAN_TIMEOUT", "1800"))
APP_SOURCE_EXTS = {
    ".cs", ".cshtml", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".java", ".kt", ".rb", ".php", ".sql",
}
EXCLUDE_DIRS = {"node_modules", "bin", "obj", "dist", "build", ".sdlc"}
SKILL_PREFIX = "skills/sdlc-security-review/"

# (rule, severity, message, compiled pattern)
SECRET_PATTERNS: List[Tuple[str, str, str, re.Pattern]] = [
    ("heuristic-secrets.aws-access-key", "high",
     "AWS access key id pattern (value redacted)", re.compile(r"AKIA[0-9A-Z]{16}", re.I)),
    ("heuristic-secrets.private-key", "critical",
     "Private key block (value redacted)",
     re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I)),
    ("heuristic-secrets.database-uri", "high",
     "Database URI with embedded credentials (value redacted)",
     re.compile(r"postgres(ql)?://[^\s:/@]+:[^\s@]+@", re.I)),
    ("heuristic-secrets.credential-assignment", "high",
     "Credential-like assignment (value redacted)",
     re.compile(r"(password|pwd|secret|api[_-]?key|token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]", re.I)),
    ("heuristic-secrets.password-argument", "medium",
     "Password passed on a command line/config",
     re.compile(r"(password|pwd)=[^;\"\s]{4,}", re.I)),
    ("heuristic-secrets.jwt", "high",
     "JSON Web Token pattern (value redacted)",
     re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", re.I)),
    ("heuristic-secrets.github-token", "high",
     "GitHub token pattern (value redacted)",
     re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}", re.I)),
    ("heuristic-secrets.stripe-key", "critical",
     "Stripe live key pattern (value redacted)",
     re.compile(r"sk_live_[0-9A-Za-z]{20,}", re.I)),
    ("heuristic-secrets.slack-token", "high",
     "Slack token pattern (value redacted)",
     re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}", re.I)),
]

SAST_PATTERNS: List[Tuple[str, str, str, re.Pattern]] = [
    ("heuristic-sast.dangerous-html", "medium",
     "React dangerouslySetInnerHTML - ensure HTML is sanitized",
     re.compile(r"dangerouslySetInnerHTML", re.I)),
    ("heuristic-sast.dynamic-eval", "high",
     "Dynamic code evaluation (eval/new Function) - review input source",
     re.compile(r"eval\s*\(|new\s+Function\s*\(", re.I)),
    ("heuristic-sast.cors-any", "medium",
     "Permissive CORS policy (AllowAnyOrigin)", re.compile(r"AllowAnyOrigin", re.I)),
    ("heuristic-sast.tls-disabled", "high",
     "TLS certificate validation disabled",
     re.compile(r"TrustServerCertificate\s*=\s*true|VerifyServerCertificate\s*=\s*false", re.I)),
    ("heuristic-sast.allow-anonymous", "low",
     "Anonymous access attribute - verify this is intentional",
     re.compile(r"\[AllowAnonymous\]", re.I)),
    ("heuristic-sast.weak-hash", "low",
     "Weak hash algorithm (MD5/SHA1) - prefer SHA-256+", re.compile(r"MD5|SHA1", re.I)),
    ("heuristic-sast.sql-concat", "medium",
     "Possible SQL string concatenation - use parameters",
     re.compile(r"\bSELECT\b[^;]*\+")),
    ("heuristic-sast.html-raw", "medium",
     "Unencoded HTML output - ensure input is trusted/sanitized",
     re.compile(r"Html\.Raw\(|innerHTML\s*=", re.I)),
]

SECRET_EXCLUDE_GLOBS = ("*.md", "*.lock", "package-lock.json", "*.min.js")
SAST_EXCLUDE_GLOBS = ("*.min.js",)

# Set by main().
ROOT: Path = Path.cwd()
OUT: Path = ROOT / ".sdlc" / "reports"
FEATURE: str = "repo"
STRICT: bool = False
CFG: Dict[str, Any] = {"strict": False, "scanners": {}}


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def find_root() -> Path:
    env_root = os.environ.get("SDLC_SCAN_ROOT")
    if env_root:
        return Path(env_root).resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return Path.cwd().resolve()


def run_cmd(cmd: Sequence[str], cwd: Optional[Path] = None) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SCAN_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        warn(f"[scan] command failed: {cmd[0]}: {exc}")
        return None


def tool_cmd(name: str) -> Optional[List[str]]:
    path = shutil.which(name)
    if not path:
        return None
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path]
    return [path]


def run_tool(name: str, args: Sequence[str], cwd: Optional[Path] = None) -> Optional[subprocess.CompletedProcess]:
    base = tool_cmd(name)
    if not base:
        return None
    return run_cmd(base + list(args), cwd=cwd)


def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def scan_mode(key: str) -> str:
    env_value = os.environ.get(f"SDLC_SEC_{key.upper()}", "").strip().lower()
    if env_value in ("auto", "enabled", "disabled"):
        return env_value
    return str((CFG.get("scanners") or {}).get(key, "auto")).lower()


def git_files(*patterns: str) -> List[str]:
    proc = run_cmd(["git", "-C", str(ROOT), "ls-files", "-z", *patterns])
    if not proc or proc.returncode != 0:
        return []
    return [item for item in proc.stdout.split("\0") if item]


def read_lines(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if "\x00" in text[:4096]:
        return []
    return text.splitlines()


def path_excluded(rel: str, globs: Iterable[str]) -> bool:
    parts = Path(rel).parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    if rel.startswith(SKILL_PREFIX):
        return True
    name = Path(rel).name
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g) for g in globs)


def emit(scanner: str, findings: List[Dict[str, Any]], status: str,
         message: Optional[str] = None, tool_version: Optional[str] = None) -> None:
    sarif.write_scanner_outputs(OUT, FEATURE, scanner, findings, status, tool_version, message)
    log(f"[sarif] {scanner}: {len(findings)} finding(s) -> {OUT}/{FEATURE}-{sarif.scanner_slug(scanner)}.sarif")


def scanner_count(name: str) -> int:
    path = OUT / f"{FEATURE}-{sarif.scanner_slug(name)}.json"
    try:
        return len(json.loads(path.read_text(encoding="utf-8")).get("findings", []) or [])
    except (OSError, ValueError):
        return 0


def clean(*patterns: str) -> None:
    for pattern in patterns:
        for path in OUT.glob(f"{FEATURE}-{pattern}"):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass


def finish(label: str, names: Optional[Sequence[str]]) -> int:
    combined = sarif.merge_feature(OUT, FEATURE)
    total = len(combined.get("findings", []))
    self_count = total if not names else sum(scanner_count(name) for name in names)
    log(f"[{label}] findings: {self_count} (merged: {total}; report: .sdlc/reports/{FEATURE}-findings.sarif)")
    return 1 if STRICT and self_count > 0 else 0


def heuristic_secrets() -> List[Dict[str, Any]]:
    rows = set()
    for rel in git_files():
        if path_excluded(rel, SECRET_EXCLUDE_GLOBS):
            continue
        for lineno, line in enumerate(read_lines(ROOT / rel), 1):
            for rule, severity, message, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    rows.add((rule, rel, lineno, severity, message))
    tsv = "\n".join("\t".join(str(part) for part in row)
                    for row in sorted(rows, key=lambda r: (r[1], r[2], r[0])))
    return sarif.from_lines(tsv, "heuristic-secrets", ROOT)


def run_secrets() -> int:
    clean("gitleaks.*", "trufflehog.*", "heuristic-secrets.*",
          "secrets-*.raw.json", "secrets-*.raw.jsonl")

    if has_tool("gitleaks") and scan_mode("gitleaks") != "disabled":
        raw = OUT / f"{FEATURE}-secrets-gitleaks.raw.json"
        log("[secrets] gitleaks (redacted)")
        run_tool("gitleaks", [
            "detect", "--source", str(ROOT), "--redact", "--no-banner",
            "--report-format", "json", "--report-path", str(raw),
        ])
        if raw.is_file() and raw.stat().st_size > 0:
            try:
                findings = sarif.from_gitleaks(sarif.load_json(raw), "gitleaks", ROOT)
                emit("gitleaks", findings, "ran")
                log(f"[secrets] gitleaks findings: {len(findings)}")
                return finish("secrets", ["gitleaks", "trufflehog", "heuristic-secrets"])
            except Exception as exc:  # noqa: BLE001
                warn(f"[secrets] gitleaks report could not be parsed: {exc}")
        else:
            log("[secrets] gitleaks produced no report; using regex fallback")
    elif has_tool("trufflehog") and scan_mode("trufflehog") != "disabled":
        log("[secrets] trufflehog (verified only, redacted)")
        proc = run_tool("trufflehog", ["filesystem", str(ROOT), "--only-verified", "--json"])
        if proc and proc.stdout.strip():
            raw = OUT / f"{FEATURE}-secrets-trufflehog.raw.jsonl"
            raw.write_text(proc.stdout, encoding="utf-8")
            findings = sarif.from_trufflehog(proc.stdout, "trufflehog", ROOT)
            emit("trufflehog", findings, "ran")
            log(f"[secrets] trufflehog findings: {len(findings)}")
            return finish("secrets", ["gitleaks", "trufflehog", "heuristic-secrets"])

    log("[secrets] gitleaks/trufflehog not installed or disabled - using regex fallback "
        "(low coverage; install gitleaks for real scanning)")
    emit("heuristic-secrets", heuristic_secrets(), "fallback")
    return finish("secrets", ["gitleaks", "trufflehog", "heuristic-secrets"])


def heuristic_sast() -> List[Dict[str, Any]]:
    rows = set()
    for rel in git_files():
        if Path(rel).suffix.lower() not in APP_SOURCE_EXTS:
            continue
        if path_excluded(rel, SAST_EXCLUDE_GLOBS):
            continue
        for lineno, line in enumerate(read_lines(ROOT / rel), 1):
            for rule, severity, message, pattern in SAST_PATTERNS:
                if pattern.search(line):
                    rows.add((rule, rel, lineno, severity, message))
    tsv = "\n".join("\t".join(str(part) for part in row)
                    for row in sorted(rows, key=lambda r: (r[1], r[2], r[0])))
    return sarif.from_lines(tsv, "heuristic-sast", ROOT)


def run_sast() -> None:
    clean("semgrep.*", "heuristic-sast.*", "sast-*.raw.json", "zizmor.*", "sast-*.raw.sarif")

    if scan_mode("semgrep") == "disabled":
        log("[sast] semgrep disabled in .sdlc/config.yaml")
        emit("semgrep", [], "skipped", "disabled in .sdlc/config.yaml")
    elif has_tool("semgrep"):
        raw = OUT / f"{FEATURE}-sast-semgrep.raw.json"
        log("[sast] semgrep scan")
        run_tool("semgrep", [
            "scan", "--metrics=off", "--quiet",
            "--config", "p/owasp-top-ten", "--config", "p/csharp",
            "--config", "p/react", "--config", "p/typescript", "--config", "p/secrets",
            "--exclude", "node_modules", "--exclude", "bin", "--exclude", "obj",
            "--exclude", "dist", "--exclude", "build",
            "--json", "--output", str(raw), str(ROOT),
        ])
        used_heuristic = False
        if raw.is_file() and raw.stat().st_size > 0:
            try:
                findings = sarif.from_semgrep(sarif.load_json(raw), "semgrep", ROOT)
                emit("semgrep", findings, "ran")
                log(f"[sast] semgrep findings: {len(findings)}")
            except Exception as exc:  # noqa: BLE001
                warn(f"[sast] semgrep output could not be parsed ({exc}); using heuristic fallback")
                used_heuristic = True
        else:
            log("[sast] semgrep produced no output; check network/rule access or use the fallback")
            used_heuristic = True
        if used_heuristic:
            emit("heuristic-sast", heuristic_sast(), "fallback")
            log(f"[sast] heuristic findings: {scanner_count('heuristic-sast')}")
    else:
        log("[sast] semgrep not installed - using conservative heuristics on application source "
            "files (low coverage; install semgrep for real SAST)")
        emit("heuristic-sast", heuristic_sast(), "fallback")

    workflows = ROOT / ".github" / "workflows"
    if workflows.is_dir():
        if scan_mode("zizmor") == "disabled":
            log("[sast] zizmor disabled in .sdlc/config.yaml")
            emit("zizmor", [], "skipped", "disabled in .sdlc/config.yaml")
        elif has_tool("zizmor"):
            log("[sast] zizmor GitHub Actions scan")
            proc = run_tool("zizmor", ["--format", "sarif", str(workflows)])
            raw = OUT / f"{FEATURE}-sast-zizmor.raw.sarif"
            if proc and proc.stdout.strip():
                raw.write_text(proc.stdout, encoding="utf-8")
                try:
                    emit("zizmor", sarif.from_sarif(sarif.load_json(raw), "zizmor", ROOT), "ran")
                except Exception as exc:  # noqa: BLE001
                    warn(f"[sast] zizmor SARIF output could not be parsed: {exc}")
                    emit("zizmor", [], "skipped", "zizmor SARIF output could not be parsed")
            else:
                emit("zizmor", [], "ran", "no workflow findings reported")
        else:
            log("[sast] zizmor not installed - skipped GitHub Actions workflow check")
            emit("zizmor", [], "skipped", "zizmor not installed")

    return finish("sast", ["semgrep", "heuristic-sast", "zizmor"])


def run_deps() -> int:
    clean("dotnet.*", "npm-audit.*", "osv-scanner.*",
          "deps-*.raw.json", "deps-*.raw.sarif", "deps-dotnet-*.txt")

    if scan_mode("dotnet") == "disabled":
        log("[deps] dotnet disabled in .sdlc/config.yaml")
        emit("dotnet", [], "skipped", "disabled in .sdlc/config.yaml")
    elif has_tool("dotnet"):
        targets = git_files("*.sln", "*.slnx") or git_files("*.csproj")
        if not targets:
            log("[deps] no .NET solution/projects found")
            emit("dotnet", [], "skipped", "No .NET solution or project files found")
        else:
            findings: List[Dict[str, Any]] = []
            json_found = False
            for idx, rel in enumerate(targets, 1):
                raw = OUT / f"{FEATURE}-deps-dotnet-{idx}.raw.json"
                txt = OUT / f"{FEATURE}-deps-dotnet-{idx}.txt"
                log(f"[deps] dotnet list package --vulnerable: {rel}")
                proc = run_tool("dotnet", [
                    "list", str(ROOT / rel), "package", "--vulnerable",
                    "--include-transitive", "--format", "json",
                ])
                if proc and proc.stdout.lstrip().startswith("{"):
                    try:
                        findings.extend(sarif.from_dotnet(json.loads(proc.stdout), "dotnet", ROOT))
                        raw.write_text(proc.stdout, encoding="utf-8")
                        json_found = True
                        continue
                    except (ValueError, TypeError) as exc:
                        warn(f"[deps] {rel}: could not parse dotnet JSON: {exc}")
                proc_text = run_tool("dotnet", [
                    "list", str(ROOT / rel), "package", "--vulnerable", "--include-transitive",
                ])
                if proc_text:
                    txt.write_text((proc_text.stdout or "") + (proc_text.stderr or ""), encoding="utf-8")
                log(f"[deps] {rel}: SDK does not support --format json; wrote text report to .sdlc/reports/{txt.name}")
            if json_found:
                emit("dotnet", findings, "ran")
            else:
                emit("dotnet", [], "fallback",
                     f"dotnet SDK lacks JSON output; findings are in .sdlc/reports/{FEATURE}-deps-dotnet-*.txt")
    else:
        log("[deps] dotnet not installed - skipped .NET check")
        emit("dotnet", [], "skipped", "dotnet SDK not installed")

    if scan_mode("npm_audit") == "disabled":
        log("[deps] npm-audit disabled in .sdlc/config.yaml")
        emit("npm-audit", [], "skipped", "disabled in .sdlc/config.yaml")
    elif has_tool("npm"):
        packages = [p for p in git_files("*package.json") if "node_modules" not in Path(p).parts]
        if not packages:
            log("[deps] no package.json found")
            emit("npm-audit", [], "skipped", "No package.json found")
        else:
            findings = []
            any_json = False
            had_lockfile = False
            for rel in packages:
                pkg_dir = (ROOT / rel).parent
                if not any((pkg_dir / name).is_file()
                           for name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml")):
                    log(f"[deps] {rel}: no lockfile - skipped (commit a lockfile)")
                    continue
                had_lockfile = True
                log(f"[deps] npm audit (high+): {rel}")
                proc = run_tool("npm", ["audit", "--audit-level=high", "--json"], cwd=pkg_dir)
                if proc and proc.stdout.strip():
                    try:
                        findings.extend(sarif.from_npm_audit(
                            json.loads(proc.stdout), "npm-audit", ROOT, rel))
                        any_json = True
                        continue
                    except (ValueError, TypeError) as exc:
                        warn(f"[deps] {rel}: could not parse npm audit JSON: {exc}")
                log(f"[deps] {rel}: npm audit produced no JSON report")
            if any_json:
                emit("npm-audit", findings, "ran")
            elif had_lockfile:
                emit("npm-audit", [], "fallback", "npm audit produced no JSON report")
            else:
                emit("npm-audit", [], "skipped", "No lockfile found for package.json")
    else:
        log("[deps] npm not installed - skipped Node check")
        emit("npm-audit", [], "skipped", "npm not installed")

    if scan_mode("osv_scanner") == "disabled":
        log("[deps] osv-scanner disabled in .sdlc/config.yaml")
        emit("osv-scanner", [], "skipped", "disabled in .sdlc/config.yaml")
    elif has_tool("osv-scanner"):
        raw = OUT / f"{FEATURE}-deps-osv.raw.sarif"
        log("[deps] osv-scanner lockfile scan")
        run_tool("osv-scanner", [
            "scan", "--recursive", "--format", "sarif", "--output", str(raw), str(ROOT),
        ])
        if raw.is_file() and raw.stat().st_size > 0:
            try:
                emit("osv-scanner", sarif.from_sarif(sarif.load_json(raw), "osv-scanner", ROOT), "ran")
            except Exception as exc:  # noqa: BLE001
                warn(f"[deps] osv-scanner SARIF output could not be parsed: {exc}")
                emit("osv-scanner", [], "skipped", "osv-scanner SARIF output could not be parsed")
        else:
            emit("osv-scanner", [], "ran", "no lockfile vulnerabilities reported")
    else:
        log("[deps] osv-scanner not installed - skipped lockfile SCA")
        emit("osv-scanner", [], "skipped", "osv-scanner not installed")

    return finish("deps", ["dotnet", "npm-audit", "osv-scanner"])


def run_iac() -> int:
    clean("trivy.*", "iac-*.raw.sarif")

    if scan_mode("trivy") == "disabled":
        log("[iac] trivy disabled in .sdlc/config.yaml")
        emit("trivy", [], "skipped", "disabled in .sdlc/config.yaml")
    elif has_tool("trivy"):
        raw = OUT / f"{FEATURE}-iac-trivy.raw.sarif"
        log("[iac] trivy config scan")
        run_tool("trivy", [
            "config", "--format", "sarif", "--quiet",
            "--skip-dirs", "node_modules,.git,.sdlc,bin,obj,dist,build",
            "--output", str(raw), str(ROOT),
        ])
        if raw.is_file() and raw.stat().st_size > 0:
            try:
                emit("trivy", sarif.from_sarif(sarif.load_json(raw), "trivy", ROOT), "ran")
            except Exception as exc:  # noqa: BLE001
                warn(f"[iac] trivy SARIF output could not be parsed: {exc}")
                emit("trivy", [], "skipped", "trivy SARIF output could not be parsed")
        else:
            emit("trivy", [], "ran", "no IaC findings reported")
    else:
        log("[iac] trivy not installed - skipped IaC/container config check")
        emit("trivy", [], "skipped", "trivy not installed")

    return finish("iac", ["trivy"])


def clean_all() -> None:
    if not OUT.is_dir():
        return
    for path in OUT.glob(f"{FEATURE}-*"):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def run_all() -> int:
    clean_all()
    run_secrets()
    run_sast()
    run_deps()
    run_iac()
    return finish("all", None)


COMMANDS = {
    "secrets": run_secrets,
    "sast": run_sast,
    "deps": run_deps,
    "iac": run_iac,
    "all": run_all,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    global ROOT, OUT, FEATURE, STRICT, CFG

    parser = argparse.ArgumentParser(
        description="Run SDLCOrchestrAI security scanners and write SARIF + findings JSON.",
    )
    parser.add_argument(
        "command", nargs="?", default="all",
        choices=["all", "secrets", "sast", "deps", "iac"],
        help="Scanner to run (default: all)",
    )
    parser.add_argument("--feature", default=os.environ.get("SDLC_FEATURE", "repo"),
                        help="Feature/report slug (default: repo)")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 when the invoked scanner(s) have findings")
    args = parser.parse_args(argv)

    ROOT = find_root()
    OUT = ROOT / ".sdlc" / "reports"
    OUT.mkdir(parents=True, exist_ok=True)
    FEATURE = sarif.feature_slug(args.feature)
    CFG = sarif.load_security_config(ROOT / ".sdlc" / "config.yaml")

    env_strict = os.environ.get("SDLC_STRICT")
    STRICT = bool(args.strict or env_strict == "1")
    if env_strict is None and CFG.get("strict"):
        STRICT = True

    return COMMANDS[args.command]()


if __name__ == "__main__":
    sys.exit(main())
