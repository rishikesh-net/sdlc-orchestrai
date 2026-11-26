#!/usr/bin/env python3
"""sarif.py - convert scanner output to SARIF 2.1.0 and normalized findings JSON.

Zero dependencies (standard library only) so it runs anywhere Python 3 does.

Scanners write two files per feature into .sdlc/reports/:
  <feature>-<scanner>.sarif   single-scanner SARIF (debugging/IDE use)
  <feature>-<scanner>.json    normalized findings (schema: .sdlc/schema/findings.schema.json)

`merge` combines every per-scanner JSON for a feature into:
  <feature>-findings.sarif    merged SARIF for GitHub Code Scanning / IDEs
  <feature>-findings.json     merged normalized findings

Secret values are never copied into reports: converters only read rule ids,
descriptions, paths and line numbers.

Usage:
  sarif.py convert --type semgrep --input raw.json --scanner semgrep \
      --feature repo --out-dir .sdlc/reports [--status ran] [--root .]
  sarif.py convert --type lines --input hits.tsv --scanner heuristic-sast ...
  sarif.py convert --type none --scanner semgrep --status skipped \
      --message "semgrep not installed" ...
  sarif.py merge --feature repo --out-dir .sdlc/reports
  sarif.py count --feature repo --out-dir .sdlc/reports
  sarif.py validate .sdlc/reports/repo-findings.sarif
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"
TOOL_NAME = "SDLCOrchestrAI"
SCHEMA_VERSION = 1

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEVERITY_TO_LEVEL = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}
LEVEL_TO_SEVERITY = {
    "error": "high",
    "warning": "medium",
    "note": "low",
    "none": "info",
}


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_severity(value: Any) -> str:
    if value is None:
        return "info"
    s = str(value).strip().lower()
    aliases = {
        "error": "high",
        "warning": "medium",
        "warn": "medium",
        "moderate": "medium",
        "note": "low",
        "informational": "info",
        "none": "info",
        "unknown": "info",
    }
    s = aliases.get(s, s)
    return s if s in SEVERITY_RANK else "info"


def normalize_confidence(value: Any) -> str:
    valid = {"confirmed", "likely", "needs-verification"}
    s = str(value or "likely").strip().lower()
    return s if s in valid else "likely"


def to_posix(path: Any) -> str:
    return str(path or "").replace("\\", "/")


def rel_path(path: Any, root: Optional[Path]) -> str:
    p = to_posix(path)
    if not p:
        return p
    if root is not None:
        root_s = to_posix(root).rstrip("/")
        if root_s and p.startswith(root_s + "/"):
            p = p[len(root_s) + 1:]
    while p.startswith("./"):
        p = p[2:]
    return p


def as_int(value: Any, default: int = 1) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n >= 1 else default


def finding(scanner: str, rule: str, severity: Any, file: Any, line: Any,
            message: str, confidence: str = "likely",
            remediation: Optional[str] = None, url: Optional[str] = None) -> Dict[str, Any]:
    return {
        "scanner": scanner,
        "rule": rule or scanner,
        "severity": normalize_severity(severity),
        "confidence": normalize_confidence(confidence),
        "file": to_posix(file),
        "line": as_int(line, 1),
        "message": (message or rule or scanner).strip(),
        "remediation": remediation or None,
        "url": url or None,
    }


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Converters (raw tool output -> normalized findings)
# ---------------------------------------------------------------------------

def from_semgrep(data: Any, scanner: str, root: Optional[Path]) -> List[Dict[str, Any]]:
    results = data.get("results", []) if isinstance(data, dict) else []
    findings = []
    for r in results:
        extra = r.get("extra") or {}
        metadata = extra.get("metadata") or {}
        check = r.get("check_id") or r.get("checkId") or "semgrep.rule"
        line = (r.get("start") or {}).get("line") or (r.get("start") or {}).get("line", 1)
        remediation = extra.get("fix") or metadata.get("fix") or None
        findings.append(finding(
            scanner=scanner,
            rule="semgrep." + str(check),
            severity=extra.get("severity") or metadata.get("impact") or "info",
            file=rel_path(r.get("path"), root),
            line=line,
            message=extra.get("message") or check,
            confidence="likely",
            remediation=str(remediation) if remediation else None,
            url=(metadata.get("references") or [None])[0] if isinstance(metadata.get("references"), list) else None,
        ))
    return findings


def from_gitleaks(data: Any, scanner: str, root: Optional[Path]) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        data = data.get("findings", [])
    findings = []
    for r in data or []:
        rule = r.get("RuleID") or r.get("RuleId") or "secret"
        description = r.get("Description") or "Potential secret detected"
        findings.append(finding(
            scanner=scanner,
            rule="gitleaks." + str(rule),
            severity=r.get("Severity") or "high",
            file=rel_path(r.get("File"), root),
            line=r.get("StartLine"),
            message=str(description) + " (value redacted; rotate if live)",
            confidence="confirmed",
            remediation="Rotate the credential, remove it from git history, and load it from a secret manager.",
        ))
    return findings


def from_trufflehog(text: str, scanner: str, root: Optional[Path]) -> List[Dict[str, Any]]:
    findings = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:  # noqa: BLE001 - tolerate non-JSON log lines
            continue
        detector = obj.get("DetectorName") or obj.get("DetectorType") or "secret"
        meta = ((obj.get("SourceMetadata") or {}).get("Data") or {})
        filesystem = meta.get("Filesystem") if isinstance(meta, dict) else {}
        filesystem = filesystem or {}
        findings.append(finding(
            scanner=scanner,
            rule="trufflehog." + str(detector),
            severity="high",
            file=rel_path(filesystem.get("file") or meta.get("file") or "", root),
            line=filesystem.get("line") or filesystem.get("lineNumber") or 1,
            message=f"{detector} secret detected (value redacted; rotate if live)",
            confidence="confirmed",
            remediation="Rotate the credential, remove it from git history, and load it from a secret manager.",
        ))
    return findings


def from_npm_audit(data: Any, scanner: str, root: Optional[Path],
                    package_path: str = "package.json") -> List[Dict[str, Any]]:
    vulns = data.get("vulnerabilities", {}) if isinstance(data, dict) else {}
    findings = []
    for name, info in vulns.items():
        if not isinstance(info, dict):
            continue
        via = info.get("via") or []
        titles, urls = [], []
        for v in via:
            if isinstance(v, str):
                titles.append(v)
            elif isinstance(v, dict):
                if v.get("title"):
                    titles.append(str(v["title"]))
                if v.get("url"):
                    urls.append(str(v["url"]))
        fix = info.get("fixAvailable")
        if isinstance(fix, dict):
            remediation = f"Upgrade {name} to {fix.get('version') or 'a fixed version'}."
        else:
            remediation = "No fixed version reported; replace or isolate the dependency."
        findings.append(finding(
            scanner=scanner,
            rule="npm." + str(name),
            severity=info.get("severity"),
            file=rel_path(package_path, root),
            line=1,
            message=f"{name} ({info.get('range') or 'unknown range'}): " + ("; ".join(titles) or "known vulnerability"),
            confidence="confirmed",
            remediation=remediation,
            url=urls[0] if urls else None,
        ))
    return findings


def from_dotnet(data: Any, scanner: str, root: Optional[Path]) -> List[Dict[str, Any]]:
    findings = []
    projects = data.get("projects", []) if isinstance(data, dict) else []
    for project in projects:
        project_path = project.get("path") or "project"
        for framework in project.get("frameworks", []) or []:
            for group in ("topLevelPackages", "transitivePackages"):
                for pkg in framework.get(group, []) or []:
                    for vuln in pkg.get("vulnerabilities", []) or []:
                        findings.append(finding(
                            scanner=scanner,
                            rule="nuget." + str(pkg.get("id") or "package"),
                            severity=vuln.get("severity"),
                            file=rel_path(project_path, root),
                            line=1,
                            message=f"{pkg.get('id')} {pkg.get('resolvedVersion') or ''} ".strip()
                                    + f"({framework.get('framework') or 'framework'}): "
                                    + str(vuln.get("severity") or "vulnerability"),
                            confidence="confirmed",
                            remediation="Upgrade the NuGet package to a non-vulnerable version.",
                            url=vuln.get("advisoryurl") or vuln.get("advisoryUrl"),
                        ))
    return findings


def from_lines(text: str, scanner: str, root: Optional[Path]) -> List[Dict[str, Any]]:
    """Read tab-separated hits: rule \\t file \\t line \\t severity \\t message \\t [remediation]."""
    findings = []
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t", 5)
        if len(parts) < 5:
            continue
        rule, file, lineno, severity, message = parts[:5]
        remediation = parts[5] if len(parts) > 5 else None
        findings.append(finding(
            scanner=scanner,
            rule=rule.strip(),
            severity=severity,
            file=rel_path(file.strip(), root),
            line=lineno,
            message=message.strip(),
            confidence="needs-verification",
            remediation=remediation.strip() if remediation else None,
        ))
    return findings


def from_sarif(data: Any, scanner: str, root: Optional[Path]) -> List[Dict[str, Any]]:
    """Ingest external SARIF 2.1.0 output (Trivy, OSV-Scanner, zizmor, Roslyn, etc.)."""
    out = []
    if not isinstance(data, dict):
        return out
    for run in data.get("runs") or []:
        if not isinstance(run, dict):
            continue
        rules_by_id: Dict[str, Dict[str, Any]] = {}
        driver = (run.get("tool") or {}).get("driver") or {}
        for r in driver.get("rules") or []:
            if isinstance(r, dict) and r.get("id"):
                rules_by_id[str(r["id"])] = r
        for res in run.get("results") or []:
            if not isinstance(res, dict):
                continue
            rule_id = str(res.get("ruleId") or "finding")
            rule_meta = rules_by_id.get(rule_id) or {}
            props = {**(rule_meta.get("properties") or {}), **(res.get("properties") or {})}
            sev_raw = props.get("severity")
            if not sev_raw and props.get("security-severity") is not None:
                try:
                    score = float(props["security-severity"])
                    sev_raw = "critical" if score >= 9.0 else "high" if score >= 7.0 else "medium" if score >= 4.0 else "low"
                except (TypeError, ValueError):
                    sev_raw = None
            if not sev_raw:
                level = str(res.get("level") or (rule_meta.get("defaultConfiguration") or {}).get("level") or "warning").lower()
                sev_raw = LEVEL_TO_SEVERITY.get(level, "medium")

            locs = res.get("locations") or []
            phys = (locs[0].get("physicalLocation") or {}) if locs and isinstance(locs[0], dict) else {}
            uri = str((phys.get("artifactLocation") or {}).get("uri") or ".")
            if uri.startswith("file:///"):
                uri = uri[8:] if len(uri) > 10 and uri[9] == ":" else uri[7:]
            elif uri.startswith("file://"):
                uri = uri[7:]
            region = phys.get("region") or {}
            line_no = as_int(region.get("startLine"), 1)
            msg = str((res.get("message") or {}).get("text") or (rule_meta.get("shortDescription") or {}).get("text") or rule_id)
            out.append(finding(
                scanner=scanner,
                rule=f"{scanner}.{rule_id}" if not rule_id.startswith(f"{scanner}.") else rule_id,
                severity=sev_raw,
                file=rel_path(uri, root),
                line=line_no,
                message=msg,
                confidence="likely",
            ))
    return out


DEFAULT_SECURITY_SCANNERS = {
    "gitleaks": "auto",
    "trufflehog": "auto",
    "semgrep": "auto",
    "trivy": "auto",
    "osv_scanner": "auto",
    "zizmor": "auto",
    "dotnet": "auto",
    "npm_audit": "auto",
    "roslyn": "auto",
    "eslint_sdl": "auto",
    "squawk": "auto",
}


def load_security_config(config_path: Path) -> Dict[str, Any]:
    """Read the `security:` block from .sdlc/config.yaml using stdlib only."""
    cfg: Dict[str, Any] = {
        "strict": False,
        "scanners": dict(DEFAULT_SECURITY_SCANNERS),
    }
    if not config_path.is_file():
        return cfg
    in_security = False
    sec_indent = -1
    sub_section: Optional[str] = None
    sub_indent = -1
    try:
        lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return cfg

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if " #" in stripped:
            stripped = stripped.split(" #", 1)[0].strip()
        indent = len(raw) - len(raw.lstrip(" \t"))
        if not in_security:
            if indent == 0 and stripped.startswith("security:"):
                in_security = True
                sec_indent = indent
            continue
        if indent <= sec_indent:
            break
        if ":" not in stripped:
            continue
        k, v = [p.strip() for p in stripped.split(":", 1)]
        v = v.strip("\"'")
        if v == "":
            sub_section = k
            sub_indent = indent
            continue
        if sub_section and indent > sub_indent:
            if sub_section == "scanners" and k in cfg["scanners"]:
                mode = v.lower()
                if mode in ("auto", "enabled", "disabled"):
                    cfg["scanners"][k] = mode
        else:
            sub_section = None
            if k == "strict":
                cfg["strict"] = v.lower() in ("true", "1", "yes")
    return cfg


def cmd_config(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    cfg = load_security_config(root / ".sdlc" / "config.yaml")
    if args.shell:
        print(f"SDLC_CONFIG_STRICT={'1' if cfg['strict'] else '0'}")
        for name, mode in cfg["scanners"].items():
            env_name = f"SDLC_SEC_{name.upper()}"
            print(f"{env_name}={mode}")
    else:
        print(json.dumps(cfg, indent=2))
    return 0


# ---------------------------------------------------------------------------
# SARIF / JSON writers
# ---------------------------------------------------------------------------

def build_sarif(findings: List[Dict[str, Any]], tool_name: str = TOOL_NAME,
                tool_version: Optional[str] = None) -> Dict[str, Any]:
    rules: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    for f in findings:
        rule_id = f["rule"]
        level = SEVERITY_TO_LEVEL.get(f["severity"], "note")
        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": rule_id,
                "shortDescription": {"text": f["message"][:160] or rule_id},
                "defaultConfiguration": {"level": level},
            }
        fingerprint = hashlib.sha256(
            f"{f['scanner']}|{rule_id}|{f['file']}|{f['line']}".encode("utf-8")
        ).hexdigest()[:16]
        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {"text": f["message"]},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f["file"] or "."},
                    "region": {"startLine": as_int(f["line"], 1)},
                }
            }],
            "partialFingerprints": {"sdlcFindingHash/v1": fingerprint},
            "properties": {
                "scanner": f["scanner"],
                "severity": f["severity"],
                "confidence": f["confidence"],
                "remediation": f.get("remediation"),
            },
        })
    run: Dict[str, Any] = {
        "tool": {
            "driver": {
                "name": tool_name,
                "version": tool_version or "0.0.0",
                "rules": sorted(rules.values(), key=lambda r: r["id"]),
            }
        },
        "results": results,
    }
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [run],
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def scanner_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", name or "scanner")


def feature_slug(feature: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", feature or "")
    return slug or "repo"


def write_scanner_outputs(out_dir: Path, feature: str, scanner: str,
                          findings: List[Dict[str, Any]], status: str,
                          tool_version: Optional[str] = None,
                          message: Optional[str] = None) -> None:
    feature = feature_slug(feature)
    slug = scanner_slug(scanner)
    unique: Dict[tuple, Dict[str, Any]] = {}
    for f in findings:
        unique[(f["scanner"], f["rule"], f["file"], f["line"])] = f
    ordered = sorted(unique.values(), key=lambda f: (
        SEVERITY_RANK.get(f["severity"], 9), f["file"], f["line"], f["rule"]))

    per_scanner = {
        "schema_version": SCHEMA_VERSION,
        "feature": feature,
        "scanner": scanner,
        "status": status,
        "tool_version": tool_version,
        "generated_at": now_utc(),
        "message": message,
        "findings": ordered,
    }
    write_json(out_dir / f"{feature}-{slug}.json", per_scanner)
    write_json(out_dir / f"{feature}-{slug}.sarif",
               build_sarif(ordered, tool_name=f"SDLCOrchestrAI/{scanner}", tool_version=tool_version))


def merge_feature(out_dir: Path, feature: str) -> Dict[str, Any]:
    feature = feature_slug(feature)
    pattern = str(out_dir / f"{feature}-*.json")
    findings: Dict[tuple, Dict[str, Any]] = {}
    scanners: Dict[str, Dict[str, Any]] = {}
    for path_str in sorted(glob.glob(pattern)):
        path = Path(path_str)
        if path.name.endswith("-findings.json"):
            continue
        try:
            data = load_json(path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"[sarif] warn: skipping unreadable {path.name}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict) or not data.get("scanner"):
            continue  # raw tool output (e.g. *.raw.json), not a normalized findings file
        name = data.get("scanner") or path.stem
        scanners.setdefault(name, {
            "name": name,
            "status": data.get("status") or "ran",
            "tool_version": data.get("tool_version"),
            "message": data.get("message"),
        })
        for f in data.get("findings", []) or []:
            key = (f.get("scanner"), f.get("rule"), f.get("file"), f.get("line"))
            findings[key] = f

    ordered = sorted(findings.values(), key=lambda f: (
        SEVERITY_RANK.get(f.get("severity", "info"), 9),
        f.get("file", ""), f.get("line", 0), f.get("rule", "")))
    combined = {
        "schema_version": SCHEMA_VERSION,
        "feature": feature,
        "generated_at": now_utc(),
        "scanners": [scanners[k] for k in sorted(scanners)],
        "findings": ordered,
    }
    write_json(out_dir / f"{feature}-findings.json", combined)
    write_json(out_dir / f"{feature}-findings.sarif",
               build_sarif(ordered, tool_name=TOOL_NAME))
    return combined


def validate_sarif(path: Path) -> int:
    try:
        data = load_json(path)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {path}: {exc}", file=sys.stderr)
        return 1
    errors = []
    if data.get("version") != SARIF_VERSION:
        errors.append(f"version must be {SARIF_VERSION}, found {data.get('version')!r}")
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        errors.append("runs[] is missing or empty")
        runs = []
    total = 0
    rule_count = 0
    for idx, run in enumerate(runs):
        driver = (run.get("tool") or {}).get("driver") or {}
        if not driver.get("name"):
            errors.append(f"runs[{idx}].tool.driver.name is missing")
        rules = driver.get("rules") or []
        rule_count += len(rules)
        rule_ids = {r.get("id") for r in rules if isinstance(r, dict)}
        for ridx, result in enumerate(run.get("results") or []):
            total += 1
            rid = result.get("ruleId")
            if not rid:
                errors.append(f"runs[{idx}].results[{ridx}].ruleId is missing")
            elif rule_ids and rid not in rule_ids:
                errors.append(f"runs[{idx}].results[{ridx}].ruleId {rid!r} has no matching rule")
            locs = (result.get("locations") or [])
            if not locs:
                errors.append(f"runs[{idx}].results[{ridx}] has no locations")
                continue
            physical = (locs[0] or {}).get("physicalLocation") or {}
            uri = (physical.get("artifactLocation") or {}).get("uri")
            line = (physical.get("region") or {}).get("startLine")
            if not uri:
                errors.append(f"runs[{idx}].results[{ridx}] has no artifactLocation.uri")
            if not isinstance(line, int) or line < 1:
                errors.append(f"runs[{idx}].results[{ridx}] has invalid startLine {line!r}")
    if errors:
        print(f"FAIL: {path}")
        for e in errors[:20]:
            print(f"  - {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
        return 1
    print(f"OK: {path} ({total} result(s), {rule_count} rule(s), {len(runs)} run(s))")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def read_input(path: Optional[str]) -> str:
    if not path:
        return ""
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def cmd_convert(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    scanner = args.scanner
    root = Path(args.root).resolve() if args.root else None
    findings: List[Dict[str, Any]] = []

    if args.type != "none":
        if not args.input:
            print("ERROR: --input is required for this --type", file=sys.stderr)
            return 2
        try:
            if args.type == "lines":
                findings = from_lines(read_input(args.input), scanner, root)
            elif args.type == "trufflehog":
                findings = from_trufflehog(read_input(args.input), scanner, root)
            else:
                data = load_json(Path(args.input))
                if args.type == "semgrep":
                    findings = from_semgrep(data, scanner, root)
                elif args.type == "gitleaks":
                    findings = from_gitleaks(data, scanner, root)
                elif args.type == "npm-audit":
                    findings = from_npm_audit(data, scanner, root, args.package_path)
                elif args.type == "dotnet":
                    findings = from_dotnet(data, scanner, root)
                elif args.type == "sarif":
                    findings = from_sarif(data, scanner, root)
                else:
                    print(f"ERROR: unknown --type {args.type}", file=sys.stderr)
                    return 2
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: could not parse {args.input}: {exc}", file=sys.stderr)
            return 1

    if args.append:
        existing = out_dir / f"{feature_slug(args.feature)}-{scanner_slug(scanner)}.json"
        if existing.is_file():
            try:
                findings = (load_json(existing).get("findings") or []) + findings
            except Exception:  # noqa: BLE001 - start fresh if unreadable
                pass

    write_scanner_outputs(out_dir, feature_slug(args.feature), scanner, findings,
                          args.status, args.tool_version, args.message)
    print(f"[sarif] {scanner}: {len(findings)} finding(s) -> {out_dir}/{feature_slug(args.feature)}-{scanner_slug(scanner)}.sarif")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    combined = merge_feature(Path(args.out_dir), args.feature)
    print(f"[sarif] merged {len(combined['findings'])} finding(s) -> "
          f"{args.out_dir}/{feature_slug(args.feature)}-findings.sarif")
    return 0


def cmd_count(args: argparse.Namespace) -> int:
    path = Path(args.out_dir) / f"{feature_slug(args.feature)}-findings.json"
    try:
        data = load_json(path)
    except Exception:  # noqa: BLE001
        print("0")
        return 0
    print(len(data.get("findings", []) or []))
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert scanner output to SARIF 2.1.0 and normalized JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("convert", help="Convert one tool's output into per-scanner SARIF + JSON")
    p.add_argument("--type", required=True, choices=["semgrep", "gitleaks", "trufflehog", "npm-audit", "dotnet", "lines", "sarif", "none"])
    p.add_argument("--input", help="Raw tool output file ('-' for stdin)")
    p.add_argument("--append", action="store_true", help="Append to an existing per-scanner findings file")
    p.add_argument("--scanner", required=True, help="Scanner name, e.g. semgrep, gitleaks, heuristic-sast")
    p.add_argument("--feature", default="repo", help="Feature slug (default: repo)")
    p.add_argument("--out-dir", required=True, help="Output directory, e.g. .sdlc/reports")
    p.add_argument("--status", default="ran", choices=["ran", "fallback", "skipped"])
    p.add_argument("--tool-version", default=None)
    p.add_argument("--message", default=None, help="Status note (e.g. why a scan was skipped)")
    p.add_argument("--root", default=None, help="Strip this root prefix from file paths")
    p.add_argument("--package-path", default="package.json", help="Path used for npm audit findings")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("merge", help="Merge per-scanner outputs into <feature>-findings.sarif/.json")
    p.add_argument("--feature", default="repo")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("count", help="Print the number of merged findings")
    p.add_argument("--feature", default="repo")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(func=cmd_count)

    p = sub.add_parser("validate", help="Structurally validate a SARIF file")
    p.add_argument("path")
    p.set_defaults(func=lambda a: validate_sarif(Path(a.path)))

    p = sub.add_parser("config", help="Read security scanner settings from .sdlc/config.yaml")
    p.add_argument("--root", default=".")
    p.add_argument("--shell", action="store_true", help="Emit safe KEY=VALUE lines for shell eval")
    p.set_defaults(func=cmd_config)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
