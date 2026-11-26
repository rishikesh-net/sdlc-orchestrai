#!/usr/bin/env python3
"""req_index.py - requirements packs: split, build, and validate the index.

Python requirements pack CLI (Python 3.8+, no jq/awk).

Commands:
    analyze  --file F [--id-regex RE] [--json]
    skeleton --file F --feature SLUG [--title T] [--level N] [--id-policy keep|renumber] [--out PLAN.json]
    split    --plan PLAN.json [--dry-run] [--allow-unassigned] [--force]
    init-pack --feature SLUG [--title T]
    new-slice --feature SLUG --slug S --title T --prefix P [--priority Must] [--depends a,b] [--summary TEXT]
    build    --feature SLUG
    validate --feature SLUG
    show     --feature SLUG (--index | --slice S | --id REQ-ID)
    stale    --feature SLUG
    to-graph --feature SLUG [--apply]

Environment: SDLC_REQ_DIR (default docs/requirements), SDLC_REQ_ROOT (root override).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
TPL = HERE.parent / "templates"

DEFAULT_PACK_RE = r"(REQ|NFR)-([A-Z][A-Z0-9]*-)?[0-9]+"
ANALYZE_RE = r"(REQ|FR|NFR|BR|UC|US|SR)-?[0-9]+([.][0-9]+)*|(REQ|NFR)-[A-Z][A-Z0-9]*-[0-9]+"
SLICE_LINES_WARN = 300
SLICE_TOKENS_WARN = 4500


def _common_dir() -> Path:
    for base in (HERE, *HERE.parents):
        candidate = base / "scripts" / "sdlc_common.py"
        if candidate.is_file():
            return candidate.parent
    raise RuntimeError("scripts/sdlc_common.py not found; reinstall the pack")


if str(_common_dir()) not in sys.path:
    sys.path.insert(0, str(_common_dir()))

import sdlc_common  # noqa: E402

ROOT: Path = Path.cwd()
REQ_BASE: Path = ROOT / "docs" / "requirements"


class ReqError(RuntimeError):
    """User-facing requirements error (exit code 2)."""


def rel(path: Path, base: Optional[Path] = None) -> str:
    try:
        return os.path.relpath(str(path), str(base or ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def source_lines(text: str) -> List[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def json_text(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def body_of(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return text
    out = []
    closed = False
    for line in lines[1:]:
        if not closed and line == "---":
            closed = True
            continue
        if closed:
            out.append(line)
    return "\n".join(out)


def frontmatter(text: str) -> Dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}
    data: Dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip().rstrip("\r")
    return data


def fm_get(text: str, key: str) -> str:
    return frontmatter(text).get(key, "")


def strip_numbering(text: str) -> str:
    return re.sub(r"^[0-9]+(?:\.[0-9]+)*[.)]?[ \t]*", "", text)


def slugify(text: str) -> str:
    value = strip_numbering(text.lower())
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:40]


def parse_list(raw: str) -> List[str]:
    value = (raw or "").strip().strip("[]")
    if not value.strip():
        return []
    return [part.strip().strip("\"'") for part in value.split(",") if part.strip()]


def ids_stream(text: str, regex: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    fence = False
    pattern = re.compile(regex)
    anchored = re.compile(r"^(" + regex + ")")
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        stripped = line.lstrip(" \t|*>#-")
        match = anchored.match(stripped)
        if match:
            out.append(("D", match.group(1)))
        for found in pattern.finditer(line):
            out.append(("R", found.group(0)))
    return out


def def_titles(text: str, regex: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    fence = False
    anchored = re.compile(r"^(" + regex + ")")
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        stripped = line.lstrip(" \t|*>#-")
        match = anchored.match(stripped)
        if not match:
            continue
        title = stripped[match.end():]
        title = re.sub(r"^[ \t*:.|)\-]+", "", title)
        title = re.sub(r"[ \t]*\|.*$", "", title)
        title = title.replace("**", "").rstrip("\r")
        out.append((match.group(1), title[:100]))
    return out


def template(name: str) -> str:
    return read_text(TPL / name)


def fill_template(text: str, **values: str) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def after_first_h1(text: str) -> str:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[idx:]) + "\n"
    return ""


def validate_feature(feature: str) -> None:
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", feature or ""):
        raise ReqError(f"invalid feature slug: {feature}")


def need_feature(feature: Optional[str]) -> str:
    if not feature:
        raise ReqError("--feature is required")
    validate_feature(feature)
    return feature


def pack_dir(feature: str) -> Path:
    return REQ_BASE / feature


def slice_file(pack: Path, slug: str) -> Optional[Path]:
    for pattern in (f"slices/*-{slug}.md", f"slices/{slug}.md"):
        for path in sorted(pack.glob(pattern)):
            if path.is_file():
                return path
    return None


def resolve_input(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def approx_tokens(path: Path) -> int:
    return (len(path.read_bytes()) + 3) // 4


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def analysis_json(path: Path, regex: str) -> Dict[str, Any]:
    text = read_text(path)
    lines = len(text.splitlines())
    words = len(text.split())
    chars = len(text.encode("utf-8"))
    tokens = (chars + 3) // 4

    headings: List[Dict[str, Any]] = []
    fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith("```"):
            fence = not fence
            continue
        if fence or not re.match(r"^#+[ \t]", line):
            continue
        level = len(line) - len(line.lstrip("#"))
        headings.append({"level": level, "start": lineno,
                         "title": line[level:].lstrip(" \t").rstrip("\r")})
    for idx, heading in enumerate(headings):
        end = lines
        for later in headings[idx + 1:]:
            if later["level"] <= heading["level"]:
                end = later["start"] - 1
                break
        heading["end"] = end

    outline = []
    for heading in headings:
        if heading["level"] > 3:
            continue
        title = heading["title"]
        if re.search(r"non-?functional|nfr|performance|security|privacy|compliance", title, re.I):
            hint = "nfr?"
        elif re.search(r"glossary|definitions|terminology|abbreviations", title, re.I):
            hint = "glossary?"
        elif re.search(r"revision|history|table of contents|contents|change log|document control", title, re.I):
            hint = "skip?"
        elif re.search(r"introduction|overview|scope|purpose|background|assumptions|constraints", title, re.I):
            hint = "overview?"
        else:
            hint = ""
        outline.append({"level": heading["level"], "start": heading["start"],
                        "end": heading["end"],
                        "lines": heading["end"] - heading["start"] + 1,
                        "title": title, "hint": hint})

    ids = ids_stream(text, regex)
    definitions = [item for kind, item in ids if kind == "D"]
    distinct = sorted({item for _, item in ids})
    duplicates = sorted({item for item in definitions if definitions.count(item) > 1})
    prefixes: Dict[str, int] = {}
    for item in distinct:
        prefix = re.sub(r"[0-9][0-9.]*$", "", item)
        prefixes[prefix] = prefixes.get(prefix, 0) + 1
    shall = sum(1 for line in text.splitlines() if re.search(r"\b(shall|must)\b", line, re.I))
    estimated = len(distinct) if distinct else shall

    reasons = []
    if lines > 400:
        reasons.append(f"{lines} lines (over 400)")
    if estimated > 40:
        reasons.append(f"about {estimated} requirements (over 40)")
    if tokens > 6000:
        reasons.append(f"about {tokens} tokens (over 6000)")

    return {
        "file": rel(path), "lines": lines, "words": words,
        "approx_tokens": tokens, "shall_must_lines": shall,
        "estimated_requirements": estimated,
        "ids": {"distinct": len(distinct), "duplicate_definitions": duplicates,
                "prefixes": [{"prefix": key, "count": prefixes[key]} for key in sorted(prefixes)]},
        "outline": outline,
        "recommendation": "pack" if reasons else "single-file",
        "reasons": reasons,
    }


def cmd_analyze(args: argparse.Namespace) -> int:
    path = resolve_input(args.file)
    if not path.is_file():
        raise ReqError(f"not found: {path}")
    data = analysis_json(path, args.id_regex or ANALYZE_RE)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"File: {data['file']}")
    print(f"Size: {data['lines']} lines, {data['words']} words, "
          f"about {data['approx_tokens']} tokens")
    print(f"Requirements (estimate): {data['estimated_requirements']}  "
          f"[distinct IDs: {data['ids']['distinct']}, "
          f"shall/must lines: {data['shall_must_lines']}]")
    prefixes = data["ids"]["prefixes"]
    if prefixes:
        print("ID prefixes: " + " ".join(
            f"{item['prefix']}({item['count']})" for item in prefixes))
    else:
        print("ID prefixes: none detected (pass --id-regex if the document uses another style)")
    if data["ids"]["duplicate_definitions"]:
        print("WARNING: IDs defined more than once: "
              + ", ".join(data["ids"]["duplicate_definitions"]))
    print()
    rec = f"RECOMMENDATION: {data['recommendation']}"
    if data["reasons"]:
        rec += " (" + "; ".join(data["reasons"]) + ")"
    print(rec)
    print()
    print("Outline (level, lines start-end, size, hint):")
    for item in data["outline"]:
        hint = f"  [{item['hint']}]" if item["hint"] else ""
        print(f"{'  ' * item['level']}L{item['level']} {item['start']}-{item['end']} "
              f"({item['lines']} lines) {item['title']}{hint}")
    return 0

def cmd_skeleton(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    if args.id_policy not in ("keep", "renumber"):
        raise ReqError("--id-policy must be keep or renumber")
    path = resolve_input(args.file)
    if not path.is_file():
        raise ReqError(f"not found: {path}")

    analysis = analysis_json(path, args.id_regex or ANALYZE_RE)
    level = args.level
    if level is None:
        level_one = [item for item in analysis["outline"] if item["level"] == 1]
        level = 2 if len(level_one) == 1 and level_one[0]["start"] <= 3 else 1

    sections = [item for item in analysis["outline"] if item["level"] == level]
    pre = sections[0]["start"] - 1 if sections else 0
    with_slug = [dict(item, slug=slugify(item["title"])) for item in sections]
    indexed = [dict(item, idx=idx) for idx, item in enumerate(with_slug)]
    slice_sections = [item for item in indexed if item["hint"] == ""]

    slices = []
    for idx, section in enumerate(slice_sections):
        slug = section["slug"] or f"slice-{idx + 1}"
        prefix = re.sub(r"[^a-z0-9]", "", section["slug"]).upper()[:4]
        if len(prefix) < 2:
            prefix = f"S{idx + 1}"
        slices.append({
            "slug": slug,
            "title": strip_numbering(section["title"]),
            "prefix": prefix,
            "summary": "TODO",
            "priority": "Must",
            "depends_on": [],
            "ranges": [[section["start"], section["end"]]],
        })
    seen: List[Dict[str, Any]] = []
    for item in slices:
        if any(existing["slug"] == item["slug"] for existing in seen):
            item["slug"] = f"{item['slug']}-{len(seen) + 1}"
        seen.append(item)
    seen_prefix: List[Dict[str, Any]] = []
    for item in slices:
        if any(existing["prefix"] == item["prefix"] for existing in seen_prefix):
            item["prefix"] = f"{item['prefix'][:3]}{len(seen_prefix) + 1}"
        seen_prefix.append(item)

    plan: Dict[str, Any] = {
        "feature": feature, "title": args.title or feature,
        "source": rel(path), "id_policy": args.id_policy,
    }
    if args.id_regex:
        plan["id_regex"] = args.id_regex
    plan["slices"] = slices
    plan["cross_cutting"] = {
        "overview": {"ranges": ([[1, pre]] if pre >= 1 else [])
                     + [[item["start"], item["end"]] for item in indexed if item["hint"] == "overview?"]},
        "nfr": {"prefix": "GEN",
                "ranges": [[item["start"], item["end"]] for item in indexed if item["hint"] == "nfr?"]},
        "glossary": {"ranges": [[item["start"], item["end"]] for item in indexed if item["hint"] == "glossary?"]},
    }
    plan["skip"] = [[item["start"], item["end"]] for item in indexed if item["hint"] == "skip?"]
    plan["skip_reason"] = ("TODO: confirm these sections (table of contents / revision history) "
                           "can be skipped")

    if args.out:
        out = resolve_input(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        json_dump(out, plan)
        print(f"Plan skeleton written to {args.out}. Review slices, ranges, prefixes, "
              f"cross-cutting and skip, then run: req_index.py split --plan {args.out} --dry-run",
              file=sys.stderr)
    else:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


def _extract(target: str, assignments: List[Tuple[str, int, int]],
             lines: List[str], base: str) -> str:
    ranges = sorted((start, end) for name, start, end in assignments if name == target)
    out = []
    for start, end in ranges:
        out.append(f"<!-- source: {base} L{start}-L{end} -->\n")
        out.append("\n".join(lines[start - 1:end]))
        out.append("\n\n")
    return "".join(out)


def cmd_split(args: argparse.Namespace) -> int:
    plan_path = resolve_input(args.plan)
    if not plan_path.is_file():
        raise ReqError("--plan PLAN.json is required")
    plan = json.loads(read_text(plan_path))
    if (not isinstance(plan, dict) or not isinstance(plan.get("feature"), str)
            or not isinstance(plan.get("source"), str)
            or not isinstance(plan.get("slices"), list) or not plan["slices"]):
        raise ReqError("plan needs feature (string), source (string) and slices (non-empty array)")

    feature = need_feature(plan["feature"])
    source = resolve_input(plan["source"])
    if not source.is_file():
        raise ReqError(f"source not found: {source}")
    policy = plan.get("id_policy") or "keep"
    if policy not in ("keep", "renumber"):
        raise ReqError("id_policy must be keep or renumber")
    regex = plan.get("id_regex") or ""
    title = plan.get("title") or plan["feature"]

    bad_slugs = []
    for slice_plan in plan["slices"]:
        slug = slice_plan.get("slug") or ""
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", slug) or not slice_plan.get("ranges"):
            bad_slugs.append(slug or "(missing slug)")
    if bad_slugs:
        raise ReqError("slices need a lowercase slug (a-z0-9-) and at least one range: "
                       + ", ".join(bad_slugs))
    slugs = [str(slice_plan.get("slug")) for slice_plan in plan["slices"]]
    duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicates:
        raise ReqError("duplicate slice slugs: " + ", ".join(duplicates))

    nfr_prefix = ((plan.get("cross_cutting") or {}).get("nfr") or {}).get("prefix") or "GEN"
    if policy == "renumber":
        bad_prefix = [str(s.get("slug")) for s in plan["slices"]
                      if not re.match(r"^[A-Z][A-Z0-9]{1,7}$", str(s.get("prefix") or ""))]
        if bad_prefix:
            raise ReqError("renumber needs an uppercase prefix (2-8 chars, A-Z0-9) on every "
                           "slice: " + ", ".join(bad_prefix))
        prefixes = [str(s.get("prefix")) for s in plan["slices"]] + [nfr_prefix]
        dup_prefix = sorted({p for p in prefixes if prefixes.count(p) > 1})
        if dup_prefix:
            raise ReqError("prefixes must be unique (including nfr prefix, default GEN): "
                           + ", ".join(dup_prefix))

    source_text = read_text(source)
    lines = source_lines(source_text)
    total_lines = len(source_text.splitlines())

    assignments: List[Tuple[str, int, int]] = []
    for slice_plan in plan["slices"]:
        for start, end in slice_plan.get("ranges") or []:
            assignments.append((f"slice:{slice_plan['slug']}", start, end))
    for key, value in (plan.get("cross_cutting") or {}).items():
        if key not in ("overview", "nfr", "glossary"):
            raise ReqError(f"unknown cross_cutting targets (allowed: nfr, glossary, overview): {key}")
        for start, end in (value or {}).get("ranges") or []:
            assignments.append((key, start, end))
    for start, end in plan.get("skip") or []:
        assignments.append(("skip", start, end))

    errors: List[str] = []
    owner: Dict[int, str] = {}
    overlap: Dict[str, int] = {}
    for target, start, end in assignments:
        if not isinstance(start, int) or not isinstance(end, int):
            errors.append(f"ERR bad range for {target}: {start},{end}")
            continue
        if start < 1 or end < start or end > total_lines:
            errors.append(f"ERR out of bounds for {target}: {start}-{end} "
                          f"(source has {total_lines} lines)")
            continue
        for lineno in range(start, end + 1):
            if lineno in owner:
                key = f"{target} / {owner[lineno]}"
                overlap[key] = overlap.get(key, 0) + 1
            else:
                owner[lineno] = target

    counts: Dict[str, int] = {}
    unassigned: List[int] = []
    for lineno, line in enumerate(lines, 1):
        if line.strip() == "":
            continue
        if lineno in owner:
            counts[owner[lineno]] = counts.get(owner[lineno], 0) + 1
        else:
            unassigned.append(lineno)
    unassigned_ranges: List[Tuple[int, int]] = []
    for lineno in unassigned:
        if not unassigned_ranges or lineno != unassigned_ranges[-1][1] + 1:
            unassigned_ranges.append((lineno, lineno))
        else:
            unassigned_ranges[-1] = (unassigned_ranges[-1][0], lineno)

    print(f"Source: {rel(source)} ({total_lines} lines)   Feature: {feature}   ID policy: {policy}")
    print("Coverage (non-blank lines per target):")
    for target in sorted(counts):
        print(f"  {target:<28} {counts[target]}")
    for key in sorted(overlap):
        errors.append(f"ERR overlap ({key}): {overlap[key]} line(s)")
    if errors:
        for message in errors:
            print(message, file=sys.stderr)
        raise ReqError("plan has errors (fix ranges so no range overlaps or runs past the end)")
    if unassigned:
        print(f"Unassigned non-blank lines: {len(unassigned)} "
              "(not in any slice, cross-cutting target, or skip)")
        for start, end in unassigned_ranges[:20]:
            print(f"  lines {start}-{end}")
        if not args.allow_unassigned:
            raise ReqError("every non-blank line must be assigned or skipped. Fix the plan, "
                           "or pass --allow-unassigned to park them in _unassigned.md")
    else:
        print("Unassigned non-blank lines: 0 (full coverage)")
    if args.dry_run:
        print()
        print("Dry run complete. Nothing written.")
        return 0

    pack = pack_dir(feature)
    if pack.is_dir() and any(pack.iterdir()) and not args.force:
        raise ReqError(f"{rel(pack)} already exists and is not empty (use --force to overwrite)")
    if pack.exists():
        for child in sorted(pack.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        pack.rmdir()
    (pack / "slices").mkdir(parents=True)
    (pack / "_source").mkdir(parents=True)
    base = source.name
    (pack / "_source" / base).write_bytes(source.read_bytes())

    for idx, slice_plan in enumerate(plan["slices"], 1):
        slug = slice_plan["slug"]
        stitle = slice_plan.get("title") or slug
        sprefix = slice_plan.get("prefix") or ""
        sprio = slice_plan.get("priority") or ""
        sdeps = ", ".join(slice_plan.get("depends_on") or [])
        ssum = slice_plan.get("summary") or ""
        target = pack / "slices" / f"{idx:02d}-{slug}.md"
        header = ("---\n" f"slice: {slug}\n" f"title: {stitle}\n" f"prefix: {sprefix}\n"
                  "status: draft\n" f"priority: {sprio}\n" "owner:\n"
                  f"depends_on: {sdeps}\n" f"summary: {ssum}\n" f"source: {base}\n"
                  "---\n\n" f"# {stitle}\n\n")
        write_text_lf(target, header + _extract(f"slice:{slug}", assignments, lines, base))

    nfr_header = ("---\n" "slice: nfr\n" "title: Cross-cutting requirements\n"
                  f"prefix: {nfr_prefix}\n" "status: draft\n"
                  "summary: Non-functional and cross-cutting requirements shared by all slices\n"
                  "---\n\n" "# Cross-cutting requirements\n\n")
    if any(name == "nfr" for name, _, _ in assignments):
        nfr_body = _extract("nfr", assignments, lines, base)
    else:
        nfr_body = after_first_h1(template("requirements-nfr.template.md"))
    write_text_lf(pack / "nfr.md", nfr_header + nfr_body)

    glossary_header = ("---\n" "slice: glossary\n" "title: Glossary\n" "status: draft\n"
                       "---\n\n" "# Glossary\n\n")
    if any(name == "glossary" for name, _, _ in assignments):
        glossary_body = _extract("glossary", assignments, lines, base)
    else:
        glossary_body = "| Term | Meaning |\n|---|---|\n|  |  |\n"
    write_text_lf(pack / "glossary.md", glossary_header + glossary_body)

    if unassigned:
        parked = ["# Unassigned lines (parked by --allow-unassigned)\n\n"
                  "Move each block into a slice, then delete this file.\n\n"]
        for start, end in unassigned_ranges:
            parked.append(f"<!-- source: {base} L{start}-L{end} -->\n")
            parked.append("\n".join(lines[start - 1:end]))
            parked.append("\n\n")
        write_text_lf(pack / "_unassigned.md", "".join(parked))

    if any(name == "overview" for name, _, _ in assignments):
        overview = _extract("overview", assignments, lines, base)
    else:
        overview = "TODO: problem statement, goals, non-goals, actors.\n"
    index_tpl = fill_template(template("requirements-index.template.md"),
                              FEATURE=feature, TITLE=title, SOURCE=f"_source/{base}")
    write_text_lf(pack / "00-index.md",
                  index_tpl.replace("{{OVERVIEW}}", overview.rstrip("\n")))

    pack_re = regex or ANALYZE_RE
    if policy == "renumber":
        pack_re = DEFAULT_PACK_RE
    json_dump(pack / "pack.json", {
        "schema_version": 1, "feature": feature, "id_policy": policy,
        "id_regex": pack_re, "source": f"_source/{base}",
        "split_from": rel(source), "created_by": "req_index.py split",
    })

    if policy == "renumber":
        renumber_pack(pack, regex or ANALYZE_RE, nfr_prefix)

    build_index(feature, quiet=True)
    write_split_report(pack, plan, assignments, counts, base, total_lines, policy)
    print()
    print(f"Split complete: {rel(pack)}/")
    print(f"  slices:  {len(list((pack / 'slices').glob('*.md')))}    "
          f"original kept at: {rel(pack)}/_source/{base}")
    print(f"  report:  {rel(pack)}/_split-report.md")
    print(f"Next: review each slice (status is draft), then: "
          f"req_index.py validate --feature {feature}")
    return 0

def renumber_pack(pack: Path, old_regex: str, nfr_prefix: str) -> None:
    mapping: Dict[str, str] = {}
    defined_in: Dict[str, str] = {}
    conflicts: List[Tuple[str, str]] = []
    targets = sorted((pack / "slices").glob("*.md")) + [pack / "nfr.md"]
    for path in targets:
        if not path.is_file():
            continue
        text = read_text(path)
        prefix = nfr_prefix if path.name == "nfr.md" else fm_get(text, "prefix")
        seen: List[str] = []
        for kind, ticket_id in ids_stream(body_of(text), old_regex):
            if kind != "D" or ticket_id in seen:
                continue
            seen.append(ticket_id)
            if re.match(r"^(REQ|NFR)-[A-Z][A-Z0-9]*-[0-9]+$", ticket_id):
                continue
            if ticket_id in mapping:
                conflicts.append((ticket_id, path.name))
                continue
            if ticket_id.startswith("NFR"):
                n = sum(1 for value in mapping.values() if value.startswith("NFR-")) + 1
                new_id = f"NFR-{prefix}-{n:03d}"
            else:
                n = sum(1 for value in mapping.values() if value.startswith("REQ-")) + 1
                new_id = f"REQ-{prefix}-{n:03d}"
            mapping[ticket_id] = new_id
            defined_in[ticket_id] = rel(path, pack)

    rewrite = sorted(
        [pack / "00-index.md", pack / "glossary.md", pack / "nfr.md"]
        + sorted((pack / "slices").glob("*.md"))
        + [pack / "_unassigned.md"]
    )
    for path in rewrite:
        if not path.is_file():
            continue
        out_lines = []
        fence = False
        for line in read_text(path).splitlines():
            if line.startswith("```"):
                fence = not fence
                out_lines.append(line)
                continue
            if fence or not mapping:
                out_lines.append(line)
                continue
            out = ""
            pos = 0
            for match in re.finditer(old_regex, line):
                pre = line[pos:match.start()]
                token = match.group(0)
                after = line[match.end():match.end() + 1]
                previous = (out + pre)[-1:] if (out + pre) else ""
                if (token in mapping
                        and not re.match(r"[A-Za-z0-9_-]", previous or "")
                        and (not after or not re.match(r"[A-Za-z0-9_-]", after))):
                    token = mapping[token]
                out += pre + token
                pos = match.end()
            out_lines.append(out + line[pos:])
        write_text_lf(path, "\n".join(out_lines) + "\n")

    json_dump(pack / "id-map.json", {
        "schema_version": 1,
        "map": [{"old": old, "new": new, "defined_in": defined_in[old]}
                for old, new in mapping.items()],
        "conflicts": [f"{ticket_id} (also defined in {name})" for ticket_id, name in conflicts],
    })
    if conflicts:
        print("WARNING: some legacy IDs are defined in more than one target; the first "
              "definition got the new ID (see id-map.json conflicts).", file=sys.stderr)


def write_split_report(pack: Path, plan: Dict[str, Any],
                       assignments: List[Tuple[str, int, int]],
                       counts: Dict[str, int], base: str, total_lines: int,
                       policy: str) -> None:
    out: List[str] = ["# Split report", ""]
    out.append(f"- Source: `{base}` ({total_lines} lines), kept unmodified in `_source/`")
    out.append(f"- ID policy: {policy}")
    out.extend(["", "## Targets", "",
                "| Target | Non-blank lines | Source ranges |", "|---|---|---|"])
    for target in sorted(counts):
        ranges = " ".join(f"L{start}-L{end}" for name, start, end in assignments
                          if name == target)
        out.append(f"| {target} | {counts[target]} | {ranges} |")
    out.extend(["", "## Skipped", ""])
    skipped = " ".join(f"L{start}-L{end}" for name, start, end in assignments if name == "skip")
    if skipped:
        out.extend([f"Ranges: {skipped}", "",
                    f"Reason: {plan.get('skip_reason') or 'not stated'}"])
    else:
        out.append("None.")
    out.extend(["", "## Unassigned", ""])
    if (pack / "_unassigned.md").is_file():
        out.append("Parked in `_unassigned.md`. Move into slices and delete it.")
    else:
        out.append("None. Every non-blank source line was assigned or skipped.")
    out.append("")
    id_map_path = pack / "id-map.json"
    if id_map_path.is_file():
        id_map = json.loads(read_text(id_map_path))
        out.extend(["## ID mapping", "",
                    f"Old to new IDs are in `id-map.json` ({len(id_map.get('map', []))} mapped)."])
        conflicts = id_map.get("conflicts") or []
        if conflicts:
            out.extend(["", "Conflicts to resolve by hand:"])
            out.extend(f"- {conflict}" for conflict in conflicts)
        out.append("")
    out.extend([
        "## Review checklist", "",
        "- [ ] Each slice reads on its own (add missing context from `glossary.md` or the index overview)",
        "- [ ] Slice `summary`, `priority`, `depends_on`, and `owner` filled in",
        "- [ ] Requirements that apply to every slice live in `nfr.md`, not copied into slices",
        "- [ ] Cross-references below are updated to point at slice files or requirement IDs",
        "",
        "### Possible dangling references (text like 'section 3.2', 'see above')", "",
    ])
    refs: List[str] = []
    candidates = sorted((pack / "slices").glob("*.md")) + [pack / "nfr.md", pack / "glossary.md"]
    pattern = re.compile(r"((section|sect\.|chapter|appendix|§) *[0-9]|see (above|below))", re.I)
    for path in candidates:
        if not path.is_file():
            continue
        for lineno, line in enumerate(read_text(path).splitlines(), 1):
            if pattern.search(line):
                refs.append(f"{rel(path, pack)}:{lineno}:{line}")
                if len(refs) >= 40:
                    break
        if len(refs) >= 40:
            break
    if refs:
        out.append("```")
        out.extend(refs)
        out.append("```")
    else:
        out.append("None found.")
    write_text_lf(pack / "_split-report.md", "\n".join(out) + "\n")


def cmd_init_pack(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    pack = pack_dir(feature)
    if pack.exists():
        raise ReqError(f"{rel(pack)} already exists")
    (pack / "slices").mkdir(parents=True)
    index_tpl = fill_template(template("requirements-index.template.md"),
                              FEATURE=feature, TITLE=args.title or feature,
                              SOURCE="n/a (new pack)")
    write_text_lf(
        pack / "00-index.md",
        index_tpl.replace("{{OVERVIEW}}",
                          "TODO: problem statement, goals, non-goals, actors."),
    )
    write_text_lf(pack / "nfr.md", template("requirements-nfr.template.md"))
    write_text_lf(pack / "glossary.md", template("requirements-glossary.template.md"))
    json_dump(pack / "pack.json", {
        "schema_version": 1, "feature": feature, "id_policy": "pack",
        "id_regex": DEFAULT_PACK_RE, "created_by": "req_index.py init-pack",
    })
    build_index(feature, quiet=True)
    print(f"Pack scaffolded at {rel(pack)}/. Add capability slices with: "
          f"req_index.py new-slice --feature {feature} --slug <slug> "
          f"--title <title> --prefix <PFX>")
    return 0


def cmd_new_slice(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", args.slug or ""):
        raise ReqError("--slug must be lowercase letters, digits, hyphens")
    if not re.match(r"^[A-Z][A-Z0-9]{1,7}$", args.prefix or ""):
        raise ReqError("--prefix must be 2-8 uppercase letters/digits (e.g. PREF)")
    if not args.title:
        raise ReqError("--title is required")
    pack = pack_dir(feature)
    if not pack.is_dir():
        raise ReqError("no pack (run init-pack first)")
    if slice_file(pack, args.slug):
        raise ReqError(f"slice {args.slug} already exists")
    for path in sorted((pack / "slices").glob("*.md")):
        if fm_get(read_text(path), "prefix") == args.prefix:
            raise ReqError(f"prefix {args.prefix} already used by {path.name}")
    number = len(list((pack / "slices").glob("*.md"))) + 1
    content = fill_template(
        template("requirements-slice.template.md"),
        SLUG=args.slug, TITLE=args.title, PREFIX=args.prefix,
        PRIORITY=args.priority or "Must", DEPENDS=args.depends or "",
        SUMMARY=args.summary or "",
    )
    target = pack / "slices" / f"{number:02d}-{args.slug}.md"
    write_text_lf(target, content)
    build_index(feature, quiet=True)
    print(f"Created {rel(target)} (IDs will look like REQ-{args.prefix}-001)")
    return 0

def _strip_slice_prefix(stem: str) -> str:
    return re.sub(r"^\d\d-", "", stem)


def compute_index(feature: str) -> Dict[str, Any]:
    pack = pack_dir(feature)
    if not pack.is_dir():
        raise ReqError(f"no pack at {rel(pack)} (run init-pack or split)")
    pack_meta: Dict[str, Any] = {}
    pack_json = pack / "pack.json"
    if pack_json.is_file():
        try:
            pack_meta = json.loads(read_text(pack_json))
        except ValueError:
            pack_meta = {}
    regex = pack_meta.get("id_regex") or DEFAULT_PACK_RE

    files: List[Path] = sorted((pack / "slices").glob("*.md"))
    for name in ("nfr.md", "glossary.md"):
        path = pack / name
        if path.is_file():
            files.append(path)

    items: List[Dict[str, Any]] = []
    defs: List[Tuple[str, str, str]] = []
    refs: List[Tuple[str, str]] = []
    for path in files:
        text = read_text(path)
        file_rel = rel(path, pack)
        body = body_of(text)
        ids: List[str] = []
        for kind, ticket_id in ids_stream(body, regex):
            if kind == "D" and ticket_id not in ids:
                ids.append(ticket_id)
        for kind, ticket_id in ids_stream(body, regex):
            if kind == "R":
                refs.append((ticket_id, file_rel))
        for ticket_id, title in def_titles(body, regex):
            defs.append((ticket_id, file_rel, title))
        items.append({
            "kind": "slice" if file_rel.startswith("slices/") else "cross",
            "slug": fm_get(text, "slice") or _strip_slice_prefix(path.stem),
            "file": file_rel,
            "title": fm_get(text, "title"),
            "status": fm_get(text, "status"),
            "priority": fm_get(text, "priority"),
            "prefix": fm_get(text, "prefix"),
            "summary": fm_get(text, "summary"),
            "depends_on": parse_list(fm_get(text, "depends_on")),
            "lines": len(body.splitlines()),
            "approx_tokens": approx_tokens(path),
            "hash": hash_file(path),
            "requirement_ids": ids,
        })

    slices = sorted([item for item in items if item["kind"] == "slice"],
                    key=lambda item: item["file"])
    cross = sorted([item for item in items if item["kind"] == "cross"],
                   key=lambda item: item["file"])

    def_files: Dict[str, List[str]] = {}
    for ticket_id, file_rel, _title in defs:
        def_files.setdefault(ticket_id, []).append(file_rel)
    duplicate_ids = sorted([ticket_id for ticket_id, files in def_files.items()
                            if len(files) > 1])
    errors = [f"requirement defined more than once: {ticket_id}: "
              + " ".join(def_files[ticket_id]) for ticket_id in duplicate_ids]

    defined = set(def_files)
    undefined = sorted({f"{ticket_id} (in {file_rel})" for ticket_id, file_rel in refs
                        if ticket_id not in defined})
    requirements: Dict[str, Dict[str, str]] = {}
    for ticket_id, file_rel, title in defs:
        requirements[ticket_id] = {"file": file_rel, "title": title}

    warnings: List[str] = []
    for item in slices:
        if item["lines"] > SLICE_LINES_WARN or item["approx_tokens"] > SLICE_TOKENS_WARN:
            warnings.append(f"slice {item['slug']} is large ({item['lines']} lines, "
                            f"~{item['approx_tokens']} tokens); consider splitting it")
    for item in slices:
        if not item["requirement_ids"]:
            warnings.append(f"slice {item['slug']} defines no requirement IDs")
    warnings.extend(f"referenced but never defined: {message}" for message in undefined)

    return {
        "schema_version": 1, "feature": feature,
        "id_policy": pack_meta.get("id_policy") or "keep", "id_regex": regex,
        "slices": slices, "cross_cutting": cross, "requirements": requirements,
        "totals": {"slices": len(slices), "requirements": len(requirements),
                   "lines": sum(item["lines"] for item in slices + cross)},
        "errors": errors, "warnings": warnings,
    }


def update_index_table(pack: Path, index: Dict[str, Any]) -> None:
    index_path = pack / "00-index.md"
    if not index_path.is_file():
        text = fill_template(template("requirements-index.template.md"),
                             FEATURE=index["feature"], TITLE=index["feature"],
                             SOURCE="n/a").replace("{{OVERVIEW}}", "TODO")
        write_text_lf(index_path, text)
    table = ["| # | Slice | Status | Priority | Requirements | Lines | Depends on | Summary |",
             "|---|---|---|---|---|---|---|---|"]
    for idx, item in enumerate(index["slices"], 1):
        table.append(f"| {idx} | [{item['title'] or item['slug']}]({item['file']}) | "
                     f"{item['status']} | {item['priority']} | "
                     f"{len(item['requirement_ids'])} | {item['lines']} | "
                     f"{', '.join(item['depends_on'])} | {item['summary']} |")
    lines = read_text(index_path).splitlines()
    output: List[str] = []
    idx = 0
    while idx < len(lines):
        output.append(lines[idx])
        if "<!-- slices:start" in lines[idx]:
            output.extend(table)
            idx += 1
            while idx < len(lines) and "<!-- slices:end" not in lines[idx]:
                idx += 1
            continue
        idx += 1
    write_text_lf(index_path, "\n".join(output) + "\n")


def build_index(feature: str, quiet: bool = False) -> Dict[str, Any]:
    index = compute_index(feature)
    pack = pack_dir(feature)
    json_dump(pack / "index.json", index)
    update_index_table(pack, index)
    if not quiet:
        print(f"Built {index['totals']['slices']} slices, "
              f"{index['totals']['requirements']} requirements, "
              f"{index['totals']['lines']} lines. Errors: {len(index['errors'])}  "
              f"Warnings: {len(index['warnings'])}")
        for message in index["errors"]:
            print(f"  ERROR {message}")
        for message in index["warnings"]:
            print(f"  WARN  {message}")
    return index


def cmd_build(args: argparse.Namespace) -> int:
    build_index(need_feature(args.feature))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    pack = pack_dir(feature)
    if not pack.is_dir():
        raise ReqError(f"no pack at {rel(pack)} (run init-pack or split)")
    index = compute_index(feature)
    errors: List[str] = []
    warnings: List[str] = []

    if not (pack / "00-index.md").is_file():
        errors.append("missing 00-index.md")
    if not (pack / "pack.json").is_file():
        errors.append("missing pack.json")
    if not index["slices"]:
        warnings.append("pack has no slices yet")
    errors.extend(index["errors"])
    warnings.extend(index["warnings"])

    for item in index["slices"]:
        if item["status"] not in ("draft", "in-review", "approved"):
            errors.append(f"{item['file']}: status must be draft | in-review | approved "
                          f"(got '{item['status']}')")
        if item["priority"] and item["priority"] not in ("Must", "Should", "Could", "Won't"):
            warnings.append(f"{item['file']}: priority should be Must | Should | Could | "
                            f"Won't (got '{item['priority']}')")
        if not item["priority"]:
            warnings.append(f"{item['file']}: priority is empty")
        stem = Path(item["file"]).stem
        if _strip_slice_prefix(stem) != item["slug"] and stem != item["slug"]:
            errors.append(f"{item['file']}: filename does not end with the slice slug "
                          f"'{item['slug']}'")
        for dep in item["depends_on"]:
            if dep and not slice_file(pack, dep):
                errors.append(f"{item['file']}: depends_on unknown slice '{dep}'")

    slugs = [item["slug"] for item in index["slices"]]
    duplicates = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    if duplicates:
        errors.append("duplicate slice slugs: " + ", ".join(duplicates))

    for item in index["slices"]:
        prefix = item["prefix"]
        if not prefix:
            continue
        for ticket_id in item["requirement_ids"]:
            if (re.match(r"^(REQ|NFR)-[A-Z][A-Z0-9]*-[0-9]+$", ticket_id)
                    and f"-{prefix}-" not in ticket_id):
                warnings.append(f"{item['file']}: {ticket_id} does not contain the slice "
                                f"prefix {prefix}")

    existing = pack / "index.json"
    if existing.is_file():
        if existing.read_text(encoding="utf-8") != json_text(index):
            warnings.append(f"index.json is out of date; run: "
                            f"req_index.py build --feature {feature}")
    else:
        warnings.append("index.json missing; run build")

    for message in errors:
        print(f"ERROR {message}")
    for message in warnings:
        print(f"WARN  {message}")
    if errors:
        print(f"Pack INVALID: {len(errors)} error(s), {len(warnings)} warning(s)",
              file=sys.stderr)
        return 1
    print(f"Pack OK: {len(warnings)} warning(s)")
    return 0

def cmd_show(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    pack = pack_dir(feature)
    if not pack.is_dir():
        raise ReqError(f"no pack at {rel(pack)}")
    if not (pack / "index.json").is_file():
        build_index(feature, quiet=True)

    if args.index:
        print(read_text(pack / "00-index.md"), end="")
        return 0
    if args.slice:
        path = slice_file(pack, args.slice)
        if not path:
            raise ReqError(f"unknown slice: {args.slice}")
        print(read_text(path), end="")
        return 0
    if args.id:
        index = json.loads(read_text(pack / "index.json"))
        file_rel = (index.get("requirements", {}).get(args.id) or {}).get("file")
        if not file_rel:
            raise ReqError(f"requirement not found: {args.id}")
        print(f"file: {rel(pack, ROOT)}/{file_rel}")
        print("---")
        pack_json = pack / "pack.json"
        regex = (json.loads(read_text(pack_json)).get("id_regex")
                 if pack_json.is_file() else DEFAULT_PACK_RE)
        anchored = re.compile(r"^(" + (regex or DEFAULT_PACK_RE) + ")")
        printing = False
        count = 0
        for line in body_of(read_text(pack / file_rel)).splitlines():
            match = anchored.match(line.lstrip(" \t|*>#-"))
            if match and match.group(1) == args.id:
                printing = True
                count = 0
            elif printing and (match or re.match(r"^#+ ", line)):
                break
            if printing:
                print(line)
                count += 1
                if count >= 60:
                    break
        return 0
    raise ReqError("usage: show --feature SLUG (--index | --slice S | --id REQ-ID)")


def cmd_stale(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    pack = pack_dir(feature)
    state_path = ROOT / ".sdlc" / "state.json"
    if not state_path.is_file():
        print("No .sdlc/state.json; nothing to compare.")
        return 0
    state = json.loads(read_text(state_path))
    hashes = ((state.get("features", {}).get(feature) or {}).get("slice_hashes") or {})
    stale = 0
    for slug, recorded in hashes.items():
        path = slice_file(pack, slug)
        if not path:
            print(f"MISSING {slug} (slice file no longer exists)")
            stale += 1
            continue
        current = hash_file(path)
        if current != recorded:
            print(f"STALE  {slug} (changed since recorded hash {recorded}; now {current}): "
                  "re-review design and backlog for this slice")
            stale += 1
    if stale == 0:
        print("All recorded slices are unchanged.")
    return 0 if stale == 0 else 1


def cmd_to_graph(args: argparse.Namespace) -> int:
    feature = need_feature(args.feature)
    build_index(feature, quiet=True)
    pack = pack_dir(feature)
    index = json.loads(read_text(pack / "index.json"))
    items: List[Dict[str, Any]] = []
    for slice_item in index["slices"]:
        items.append({"type": "entity", "id": "SLICE-" + slice_item["slug"],
                      "kind": "slice", "title": slice_item["title"],
                      "source": slice_item["file"], "status": slice_item["status"]})
    for ticket_id, requirement in index["requirements"].items():
        items.append({"type": "entity", "id": ticket_id,
                      "kind": "nfr" if ticket_id.startswith("NFR") else "requirement",
                      "title": requirement.get("title", ""),
                      "source": requirement.get("file", "")})
    for slice_item in index["slices"]:
        for ticket_id in slice_item["requirement_ids"]:
            items.append({"type": "relation", "from": ticket_id,
                          "rel": "part_of", "to": "SLICE-" + slice_item["slug"]})
        for dep in slice_item["depends_on"]:
            items.append({"type": "relation", "from": "SLICE-" + slice_item["slug"],
                          "rel": "depends_on", "to": "SLICE-" + dep})
    cleaned = [{key: value for key, value in item.items() if value not in ("", None)}
               for item in items]
    if not args.apply:
        for item in cleaned:
            print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        return 0

    graph = ROOT / ".sdlc" / "memory" / "graph.jsonl"
    graph.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if graph.is_file():
        existing = {line.strip() for line in read_text(graph).splitlines() if line.strip()}
    with open(graph, "a", encoding="utf-8", newline="\n") as handle:
        for item in cleaned:
            line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            if line not in existing:
                handle.write(line + "\n")
                existing.add(line)
    print(f"Imported {len(cleaned)} graph item(s) into {rel(graph)}.")
    return 0


HANDLERS = {
    "analyze": cmd_analyze,
    "skeleton": cmd_skeleton,
    "split": cmd_split,
    "init-pack": cmd_init_pack,
    "new-slice": cmd_new_slice,
    "build": cmd_build,
    "validate": cmd_validate,
    "show": cmd_show,
    "stale": cmd_stale,
    "to-graph": cmd_to_graph,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="req_index.py",
        description="Requirements packs: split large documents, build and validate the index.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("analyze", help="Size, outline, ID stats, and a pack recommendation")
    p.add_argument("--file", required=True)
    p.add_argument("--id-regex", default=ANALYZE_RE)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("skeleton", help="Draft a split plan from headings")
    p.add_argument("--file", required=True)
    p.add_argument("--feature", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--level", type=int, default=None)
    p.add_argument("--id-policy", choices=["keep", "renumber"], default="keep")
    p.add_argument("--out", default="")
    p.add_argument("--id-regex", default="")

    p = sub.add_parser("split", help="Split a document into a pack with a coverage check")
    p.add_argument("--plan", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-unassigned", action="store_true")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("init-pack", help="Scaffold an empty pack")
    p.add_argument("--feature", required=True)
    p.add_argument("--title", default="")

    p = sub.add_parser("new-slice", help="Add a capability slice to a pack")
    p.add_argument("--feature", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--priority", default="Must")
    p.add_argument("--depends", default="")
    p.add_argument("--summary", default="")

    for name, help_text in (
        ("build", "Regenerate index.json and the slice table"),
        ("validate", "Check structure, IDs, dependencies, sizes, and index freshness"),
        ("stale", "List slices changed since their recorded approval hash"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--feature", required=True)

    p = sub.add_parser("show", help="Print the index, a slice, or one requirement")
    p.add_argument("--feature", required=True)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--index", action="store_true")
    group.add_argument("--slice", default="")
    group.add_argument("--id", default="")

    p = sub.add_parser("to-graph", help="Emit slices and requirements as graph facts")
    p.add_argument("--feature", required=True)
    p.add_argument("--apply", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    global ROOT, REQ_BASE
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    env_root = os.environ.get("SDLC_REQ_ROOT")
    ROOT = Path(env_root).resolve() if env_root else sdlc_common.find_repo_root()
    REQ_BASE = ROOT / os.environ.get("SDLC_REQ_DIR", "docs/requirements")

    try:
        return HANDLERS[args.command](args)
    except ReqError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
