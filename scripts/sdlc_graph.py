#!/usr/bin/env python3
"""sdlc_graph.py - minimal knowledge-graph CLI (.sdlc/memory/graph.jsonl).

Replaces the former shell graph helpers with a Python-only implementation.

Commands:
    add-entity --id ID --kind KIND [--title T] [--source S] [--attr k=v ...]
    add-relation --from A --rel REL --to B
    import --file FILE.jsonl [--dry-run]
    backlog-to-graph --file BACKLOG.json [--apply]
    gaps
    normalize
    validate

Graph lines are JSON objects:
    {"type": "entity", "id": "...", "kind": "...", "title": "...", "source": "...", "attrs": {...}}
    {"type": "relation", "from": "...", "rel": "...", "to": "..."}

Environment: SDLC_GRAPH_ROOT (repo root override).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

HERE = Path(__file__).resolve().parent


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
GRAPH: Path = ROOT / ".sdlc" / "memory" / "graph.jsonl"


class GraphError(RuntimeError):
    """User-facing graph error (exit code 2)."""


def rel(path: Path) -> str:
    try:
        return os.path.relpath(str(path), str(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def canon(item: Dict[str, Any]) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def read_items(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    items: List[Dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError as exc:
            raise GraphError(f"{rel(path)}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise GraphError(f"{rel(path)}:{lineno}: each line must be a JSON object")
        items.append(data)
    return items


def write_items(items: Sequence[Dict[str, Any]]) -> None:
    GRAPH.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH, "w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(canon(item) + "\n")


def append_items(items: Iterable[Dict[str, Any]]) -> int:
    existing = {canon(item) for item in read_items(GRAPH)}
    added = 0
    GRAPH.parent.mkdir(parents=True, exist_ok=True)
    with open(GRAPH, "a", encoding="utf-8", newline="\n") as handle:
        for item in items:
            line = canon(item)
            if line not in existing:
                handle.write(line + "\n")
                existing.add(line)
                added += 1
    return added


def entity(ticket_id: str, kind: str, title: str = "", source: str = "",
           attrs: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {"type": "entity", "id": ticket_id, "kind": kind}
    if title:
        item["title"] = title
    if source:
        item["source"] = source
    if attrs:
        item["attrs"] = attrs
    return item


def relation(src: str, name: str, dst: str) -> Dict[str, Any]:
    return {"type": "relation", "from": src, "rel": name, "to": dst}


def sort_key(item: Dict[str, Any]):
    if item.get("type") == "relation":
        return (1, item.get("from", ""), item.get("rel", ""), item.get("to", ""))
    return (0, item.get("id", ""))


def print_items(items: Sequence[Dict[str, Any]]) -> None:
    for item in items:
        print(json.dumps(item, ensure_ascii=False, separators=(",", ":")))


def cmd_add_entity(args: argparse.Namespace) -> int:
    attrs: Dict[str, str] = {}
    for raw in args.attr or []:
        if "=" not in raw:
            raise GraphError(f"--attr must be key=value, got {raw!r}")
        key, value = raw.split("=", 1)
        attrs[key.strip()] = value.strip()
    item = entity(args.id, args.kind, args.title, args.source, attrs)
    append_items([item])
    print(f"Added entity {args.id} ({args.kind}).")
    return 0


def cmd_add_relation(args: argparse.Namespace) -> int:
    append_items([relation(args.src, args.rel, args.to)])
    print(f"Added relation {args.src} {args.rel} {args.to}.")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_absolute():
        path = ROOT / path
    items = read_items(path)
    if args.dry_run:
        print_items(items)
        return 0
    added = append_items(items)
    print(f"Imported {added} new item(s) from {rel(path)} into {rel(GRAPH)}.")
    return 0


def cmd_backlog_to_graph(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        raise GraphError(f"backlog not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise GraphError(f"{rel(path)}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise GraphError(f"{rel(path)} is not a backlog (items[])")

    source = rel(path)
    items: List[Dict[str, Any]] = []
    for item in data["items"]:
        ticket_id = str(item.get("id") or "")
        if not ticket_id:
            continue
        items.append(entity(ticket_id, str(item.get("type") or "task"),
                            str(item.get("title") or ""), source))
        for req in item.get("req_refs") or []:
            items.append(relation(ticket_id, "covers", str(req)))
        if item.get("parent"):
            items.append(relation(ticket_id, "part_of", str(item["parent"])))
        for dep in item.get("depends_on") or []:
            items.append(relation(ticket_id, "depends_on", str(dep)))

    if args.apply:
        added = append_items(items)
        print(f"Imported {added} new graph item(s) from {source} into {rel(GRAPH)}.")
    else:
        print_items(items)
    return 0


def cmd_gaps(args: argparse.Namespace) -> int:
    items = read_items(GRAPH)
    entities = {str(item.get("id")): item for item in items
                if item.get("type") == "entity" and item.get("id")}
    relations = [item for item in items if item.get("type") == "relation"]
    covered = {str(item.get("to")) for item in relations if item.get("rel") == "covers"}
    mitigated = {str(item.get("from")) for item in relations if item.get("rel") == "mitigated_by"}
    tracked = {str(item.get("from")) for item in relations if item.get("rel") == "tracked_by"}

    gaps: List[str] = []
    for ticket_id, item in sorted(entities.items()):
        kind = str(item.get("kind") or "")
        attrs = item.get("attrs") or {}
        severity = str(attrs.get("severity") or "").lower()
        status = str(attrs.get("status") or "").lower()
        if kind in ("requirement", "nfr") and ticket_id not in covered:
            gaps.append(f"UNCOVERED {ticket_id}")
        if kind == "threat" and severity in ("high", "critical") and ticket_id not in mitigated:
            gaps.append(f"UNMITIGATED {ticket_id} ({severity})")
        if (kind == "finding" and severity in ("high", "critical")
                and status not in ("closed", "resolved", "false-positive")
                and ticket_id not in tracked):
            gaps.append(f"UNTRACKED {ticket_id} ({severity})")

    if not gaps:
        print("No gaps: all requirements covered, high threats mitigated, high findings tracked.")
        return 0
    for gap in gaps:
        print(gap)
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    items = read_items(GRAPH)
    unique: Dict[str, Dict[str, Any]] = {}
    for item in items:
        unique[canon(item)] = item
    normalized = sorted(unique.values(), key=sort_key)
    write_items(normalized)
    print(f"Normalized {len(normalized)} item(s) -> {rel(GRAPH)}.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        items = read_items(GRAPH)
    except GraphError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    errors: List[str] = []
    entity_count = relation_count = 0
    for lineno, item in enumerate(items, 1):
        kind = item.get("type")
        if kind == "entity":
            entity_count += 1
            if not item.get("id"):
                errors.append(f"line {lineno}: entity has no id")
        elif kind == "relation":
            relation_count += 1
            for field in ("from", "rel", "to"):
                if not item.get(field):
                    errors.append(f"line {lineno}: relation has no {field}")
        else:
            errors.append(f"line {lineno}: type must be entity or relation")
    if errors:
        print(f"FAIL: {rel(GRAPH)}")
        for error in errors[:20]:
            print(f"  - {error}")
        return 1
    print(f"{rel(GRAPH)}: OK ({entity_count} entities, {relation_count} relations)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdlc_graph.py",
        description="Knowledge graph for requirements, threats, findings, and tickets.",
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("add-entity", help="Add or update an entity")
    p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--source", default="")
    p.add_argument("--attr", action="append", default=None, help="key=value (repeatable)")

    p = sub.add_parser("add-relation", help="Add a relation")
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--rel", required=True)
    p.add_argument("--to", required=True)

    p = sub.add_parser("import", help="Import JSONL graph items")
    p.add_argument("--file", required=True)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("backlog-to-graph", help="Convert a backlog JSON into graph items")
    p.add_argument("--file", required=True)
    p.add_argument("--apply", action="store_true")

    sub.add_parser("gaps", help="List uncovered requirements, unmitigated threats, untracked findings")
    sub.add_parser("normalize", help="Sort and de-duplicate graph.jsonl")
    sub.add_parser("validate", help="Validate graph.jsonl structure")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    global ROOT, GRAPH
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    env_root = os.environ.get("SDLC_GRAPH_ROOT")
    ROOT = Path(env_root).resolve() if env_root else sdlc_common.find_repo_root()
    GRAPH = ROOT / ".sdlc" / "memory" / "graph.jsonl"

    handlers = {
        "add-entity": cmd_add_entity,
        "add-relation": cmd_add_relation,
        "import": cmd_import,
        "backlog-to-graph": cmd_backlog_to_graph,
        "gaps": cmd_gaps,
        "normalize": cmd_normalize,
        "validate": cmd_validate,
    }
    try:
        return handlers[args.command](args)
    except GraphError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
