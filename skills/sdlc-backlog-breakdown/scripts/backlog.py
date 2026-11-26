#!/usr/bin/env python3
"""backlog.py - push/pull tracker tickets from a neutral backlog JSON.

Python tracker adapter CLI (local + GitHub). Requires only Python 3.8+ and git
(no jq). GitHub mode also needs an authenticated ``gh`` CLI.

Usage:
    python backlog.py push --file docs/backlog/<feature>-backlog.json \
        [--dry-run] [--only ID] [--tracker github|local]
    python backlog.py pull [--state open|closed|all] [--label L] [--limit N] \
        [--tracker github|local]

Tracker precedence: --tracker > SDLC_TRACKER > .sdlc/config.yaml ``tracker:`` > github.
* push writes ticket references back to ``items[].external`` (not in --dry-run).
* pull prints a JSON array ``[{number,title,state,labels,url}]`` to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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
CONFIG: Dict[str, Any] = {}
TRACKER: str = "github"


class BacklogError(RuntimeError):
    """User-facing backlog error (exit code 2)."""


def _tool_cmd(name: str) -> Optional[List[str]]:
    path = shutil.which(name)
    if not path:
        return None
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path]
    return [path]


def _run(cmd: Sequence[str], cwd: Optional[Path] = None) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            list(cmd), cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"WARN: {cmd[0]}: {exc}", file=sys.stderr)
        return None


def fmt_issue(value: Any) -> str:
    if value is None or value == "":
        return ""
    text = str(value)
    return f"#{text}" if text.isdigit() else text


def labels_for(item: Dict[str, Any]) -> str:
    labels: List[str] = []
    labels.append("epic" if item.get("type") == "epic" else f"type:{item.get('type')}")
    if item.get("priority") is not None:
        labels.append(f"priority:{item['priority']}")
    if item.get("estimate") is not None:
        labels.append(f"estimate:{item['estimate']}")
    labels.extend(item.get("labels") or [])
    return ",".join(sorted(set(str(label) for label in labels)))


def make_issue_ref(items: List[Dict[str, Any]]) -> Callable[[str], str]:
    by_id = {item.get("id"): item for item in items}

    def issue_ref(item_id: str) -> str:
        item = by_id.get(item_id) or {}
        key = (item.get("external") or {}).get("key")
        if key is None or key == "":
            return ""
        return fmt_issue(key)

    return issue_ref


def body_for(item: Dict[str, Any], issue_ref: Callable[[str], str]) -> str:
    parts: List[str] = [str(item.get("body_markdown") or "")]
    user_story = item.get("user_story")
    if user_story:
        parts.append(f"\n**User story:** {user_story}\n")
    criteria = item.get("acceptance_criteria") or []
    if criteria:
        parts.append("\n### Acceptance criteria\n")
        parts.extend(f"- [ ] {criterion}\n" for criterion in criteria)
    req_refs = item.get("req_refs") or []
    if req_refs:
        parts.append(f"\n**Requirements:** {', '.join(str(r) for r in req_refs)}\n")
    design_ref = item.get("design_ref")
    if design_ref:
        parts.append(f"**Design:** `{design_ref}`\n")
    parent = item.get("parent")
    if parent:
        parts.append(f"\n**Part of:** {issue_ref(parent) or parent}\n")
    deps = []
    for dep in item.get("depends_on") or []:
        deps.append(issue_ref(dep) or str(dep))
    if deps:
        parts.append(f"**Blocked by:** {', '.join(deps)}\n")
    parts.append(
        f"\n<!-- sdlc-id: {item.get('id')} | managed by backlog.py; "
        "edit backlog JSON, not this marker -->\n"
    )
    return "".join(parts)


def _json_array(value: Any) -> str:
    return json.dumps(list(value or []), ensure_ascii=False, separators=(",", ":"))


def _frontmatter(text: str) -> Dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: Dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip()] = value.strip()
    return data


def _title_value(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith('"'):
        try:
            return str(json.loads(raw))
        except ValueError:
            pass
    return raw.strip('"')


class LocalAdapter:
    name = "local"

    def __init__(self, root: Path, config: Dict[str, Any], dry: bool) -> None:
        local_cfg = config.get("local") if isinstance(config.get("local"), dict) else {}
        self.dir = str(os.environ.get("SDLC_LOCAL_DIR")
                       or (local_cfg or {}).get("output_dir")
                       or "docs/backlog/tickets").rstrip("/\\")
        directory = Path(self.dir)
        self.abs_dir = directory if directory.is_absolute() else root / directory

    def describe(self) -> str:
        return f"Tickets: {self.dir}"

    def project_desc(self) -> str:
        return ""

    def dry_run_note(self) -> str:
        return ""

    def _target(self, ticket_id: str) -> Path:
        return self.abs_dir / f"{ticket_id}.md"

    def _rel_url(self, ticket_id: str) -> str:
        return f"{self.dir}/{ticket_id}.md"

    def find(self, ticket_id: str) -> Optional[Tuple[str, str]]:
        if self._target(ticket_id).is_file():
            return ticket_id, self._rel_url(ticket_id)
        return None

    def sync_labels(self, items: List[Dict[str, Any]]) -> None:
        return None

    def _write(self, item: Dict[str, Any], bodyfile: Path) -> None:
        ticket_id = str(item.get("id"))
        target = self._target(ticket_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        state = "open"
        if target.is_file():
            existing = _frontmatter(target.read_text(encoding="utf-8", errors="replace"))
            state = existing.get("state", "open").strip('"') or "open"

        lines = [
            "---",
            f"id: {ticket_id}",
            f"title: {json.dumps(str(item.get('title') or ''), ensure_ascii=False)}",
            f"type: {item.get('type')}",
        ]
        if item.get("parent"):
            lines.append(f"parent: {item['parent']}")
        lines.append(f"state: {state}")
        if item.get("priority") is not None:
            lines.append(f"priority: {item['priority']}")
        estimate = item.get("estimate")
        lines.append(f"estimate: {estimate if estimate is not None else 'null'}")
        lines.append(f"labels: {_json_array(item.get('labels'))}")
        lines.append(f"depends_on: {_json_array(item.get('depends_on'))}")
        lines.append(f"req_refs: {_json_array(item.get('req_refs'))}")
        if item.get("design_ref"):
            lines.append(f"design_ref: {json.dumps(str(item['design_ref']), ensure_ascii=False)}")
        lines.append(f"tracker: {self.name}")
        lines.append("---")
        body = bodyfile.read_text(encoding="utf-8", errors="replace")
        if not body.endswith("\n"):
            body += "\n"
        content = "\n".join(lines) + "\n" + body

        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(tmp, target)

    def create(self, item: Dict[str, Any], title: str, bodyfile: Path, labels: str) -> Tuple[str, str]:
        self._write(item, bodyfile)
        ticket_id = str(item.get("id"))
        return ticket_id, self._rel_url(ticket_id)

    def update(self, key: str, item: Dict[str, Any], title: str, bodyfile: Path, labels: str) -> None:
        self._write(item, bodyfile)

    def refresh(self, key: str, item: Dict[str, Any], bodyfile: Path) -> None:
        return None

    def link(self, child: str, parent: str) -> None:
        return None

    def project_add(self, key: str, url: str) -> None:
        return None

    def pull(self, state: str, label: str, limit: int) -> List[Dict[str, Any]]:
        if not self.abs_dir.is_dir():
            return []
        items: List[Dict[str, Any]] = []
        for path in sorted(self.abs_dir.glob("*.md")):
            meta = _frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            ticket_id = meta.get("id", "")
            if not ticket_id:
                continue
            ticket_state = meta.get("state", "open").strip('"') or "open"
            if state != "all" and ticket_state != state:
                continue
            try:
                labels = json.loads(meta.get("labels") or "[]")
                if not isinstance(labels, list):
                    labels = []
            except ValueError:
                labels = []
            if label and label not in labels:
                continue
            items.append({
                "number": ticket_id,
                "title": _title_value(meta.get("title", "")),
                "state": ticket_state,
                "url": self._rel_url(ticket_id),
                "labels": labels,
            })
            if len(items) >= limit:
                break
        return items


class GitHubAdapter:
    name = "github"

    def __init__(self, root: Path, config: Dict[str, Any], dry: bool) -> None:
        github_cfg = config.get("github") if isinstance(config.get("github"), dict) else {}
        github_cfg = github_cfg or {}
        self.repo = str(os.environ.get("SDLC_REPO") or github_cfg.get("repo") or "")
        self.project = str(github_cfg.get("project_number") or "")
        self.owner = str(github_cfg.get("project_owner") or (self.repo.split("/")[0] if "/" in self.repo else ""))
        if not self.repo or self.repo == "your-org/your-repo":
            raise BacklogError("set github.repo in .sdlc/config.yaml (or SDLC_REPO)")
        self.have_gh = bool(shutil.which("gh")) and self._auth_ok()
        if not dry and not self.have_gh:
            raise BacklogError("gh CLI not installed or not authenticated (run: gh auth login)")

    def _gh(self, args: Sequence[str]) -> Optional[subprocess.CompletedProcess]:
        base = _tool_cmd("gh")
        if not base:
            return None
        return _run(base + list(args))

    def _auth_ok(self) -> bool:
        proc = self._gh(["auth", "status"])
        return bool(proc and proc.returncode == 0)

    def describe(self) -> str:
        return f"Repo: {self.repo}"

    def project_desc(self) -> str:
        return f"Project: {self.owner} #{self.project}" if self.project else ""

    def dry_run_note(self) -> str:
        if self.have_gh:
            return ""
        return ("Note: gh unavailable, so existing issues were not looked up; "
                "'create' may become 'update'.")

    def find(self, ticket_id: str) -> Optional[Tuple[str, str]]:
        if not self.have_gh:
            return None
        proc = self._gh([
            "issue", "list", "--repo", self.repo, "--state", "all",
            "--search", f"{ticket_id} in:title", "--json", "number,title,url", "--limit", "30",
        ])
        if not proc or proc.returncode != 0:
            return None
        try:
            rows = json.loads(proc.stdout or "[]")
        except ValueError:
            return None
        prefix = f"[{ticket_id}] "
        for row in rows:
            if str(row.get("title") or "").startswith(prefix):
                return str(row.get("number")), str(row.get("url") or "")
        return None

    def sync_labels(self, items: List[Dict[str, Any]]) -> None:
        labels = set()
        for item in items:
            labels.add("epic" if item.get("type") == "epic" else f"type:{item.get('type')}")
            if item.get("priority") is not None:
                labels.add(f"priority:{item['priority']}")
            if item.get("estimate") is not None:
                labels.add(f"estimate:{item['estimate']}")
            labels.update(str(label) for label in (item.get("labels") or []))
        for label in sorted(labels):
            self._gh(["label", "create", label, "--repo", self.repo, "--force"])

    def create(self, item: Dict[str, Any], title: str, bodyfile: Path, labels: str) -> Tuple[str, str]:
        proc = self._gh([
            "issue", "create", "--repo", self.repo, "--title", title,
            "--body-file", str(bodyfile), "--label", labels,
        ])
        output = ((proc.stdout or "") + (proc.stderr or "")) if proc else "gh is unavailable"
        if not proc or proc.returncode != 0:
            raise BacklogError(output.strip() or "gh issue create failed")
        match = re.search(r"https://\S+/issues/(\d+)", output)
        if not match:
            raise BacklogError(f"could not parse issue URL from gh output: {output.strip()}")
        return match.group(1), match.group(0)

    def update(self, key: str, item: Dict[str, Any], title: str, bodyfile: Path, labels: str) -> None:
        proc = self._gh([
            "issue", "edit", str(key), "--repo", self.repo, "--title", title,
            "--body-file", str(bodyfile), "--add-label", labels,
        ])
        if not proc or proc.returncode != 0:
            output = ((proc.stdout or "") + (proc.stderr or "")) if proc else "gh is unavailable"
            raise BacklogError(output.strip() or "gh issue edit failed")

    def refresh(self, key: str, item: Dict[str, Any], bodyfile: Path) -> None:
        self._gh(["issue", "edit", str(key), "--repo", self.repo, "--body-file", str(bodyfile)])

    def link(self, child: str, parent: str) -> None:
        proc = self._gh(["api", f"repos/{self.repo}/issues/{child}", "--jq", ".id"])
        if not proc or proc.returncode != 0 or not proc.stdout.strip():
            return
        child_id = proc.stdout.strip()
        proc = self._gh([
            "api", "-X", "POST", f"repos/{self.repo}/issues/{parent}/sub_issues",
            "-F", f"sub_issue_id={child_id}",
        ])
        if not proc or proc.returncode != 0:
            print(
                f"  note: sub-issue link {fmt_issue(child)} -> {fmt_issue(parent)} skipped "
                "(already linked or feature unavailable); 'Part of' text is in the body",
                file=sys.stderr,
            )

    def project_add(self, key: str, url: str) -> None:
        if not self.project or not url:
            return
        proc = self._gh([
            "project", "item-add", self.project, "--owner", self.owner, "--url", url,
        ])
        if not proc or proc.returncode != 0:
            print(
                f"  warn: could not add {fmt_issue(key)} to project {self.project} "
                "(needs 'project' scope: gh auth refresh -s project)",
                file=sys.stderr,
            )

    def pull(self, state: str, label: str, limit: int) -> List[Dict[str, Any]]:
        args = [
            "issue", "list", "--repo", self.repo, "--state", state,
            "--limit", str(limit), "--json", "number,title,state,labels,url",
        ]
        if label:
            args.extend(["--label", label])
        proc = self._gh(args)
        if not proc or proc.returncode != 0:
            output = ((proc.stdout or "") + (proc.stderr or "")) if proc else "gh is unavailable"
            raise BacklogError(output.strip() or "gh issue list failed")
        rows = json.loads(proc.stdout or "[]")
        return [{
            "number": row.get("number"),
            "title": row.get("title"),
            "state": row.get("state"),
            "url": row.get("url"),
            "labels": [
                (entry.get("name") if isinstance(entry, dict) else entry)
                for entry in (row.get("labels") or [])
            ],
        } for row in rows]


def make_adapter(tracker: str, root: Path, config: Dict[str, Any], dry: bool):
    if tracker == "local":
        return LocalAdapter(root, config, dry)
    if tracker == "github":
        return GitHubAdapter(root, config, dry)
    raise BacklogError(
        f"Unknown or unsupported tracker '{tracker}'. Available adapters: github local"
    )


def select_tracker(argument: Optional[str]) -> str:
    return argument or os.environ.get("SDLC_TRACKER") or str(CONFIG.get("tracker") or "github")


def resolve_file(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = ROOT / path
    if candidate.exists():
        return candidate
    return Path.cwd() / path


def save_external(path: Path, data: Dict[str, Any], ticket_id: str,
                  tracker: str, key: str, url: str) -> None:
    for item in data.get("items", []):
        if item.get("id") == ticket_id:
            item["external"] = {"tracker": tracker, "key": key, "url": url}
            break
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def _write_body(item: Dict[str, Any], issue_ref: Callable[[str], str]) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".md", delete=False
    )
    handle.write(body_for(item, issue_ref))
    handle.close()
    return Path(handle.name)


def push(args: argparse.Namespace) -> int:
    path = resolve_file(args.file)
    if not path.is_file():
        raise BacklogError("--file <backlog.json> is required and must exist")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BacklogError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("items"), list):
        raise BacklogError(f"{path} is not a valid backlog (schema_version 1 with items[])")

    items: List[Dict[str, Any]] = data["items"]
    ids = [item.get("id") for item in items]
    duplicates = sorted({str(i) for i in ids if ids.count(i) > 1})
    if duplicates:
        raise BacklogError(f"duplicate ids: {', '.join(duplicates)}")
    known = set(ids)
    unknown = [item.get("id") for item in items
               if item.get("parent") and item["parent"] not in known]
    if unknown:
        raise BacklogError(f"unknown parent for: {', '.join(str(i) for i in unknown)}")

    by_id = {item.get("id"): item for item in items}
    only = args.only or ""
    selected: List[Dict[str, Any]] = []
    for item in items:
        if not only:
            selected.append(item)
        elif item.get("id") == only:
            selected.append(item)
        elif item.get("parent") == only:
            selected.append(item)
        else:
            parent = by_id.get(item.get("parent"))
            if parent and parent.get("parent") == only:
                selected.append(item)
    rank = {"epic": 0, "story": 1}
    selected.sort(key=lambda item: rank.get(item.get("type"), 2))
    if not selected:
        print("Nothing to do (no items matched).")
        return 0

    tracker = select_tracker(args.tracker)
    adapter = make_adapter(tracker, ROOT, CONFIG, args.dry_run)
    issue_ref = make_issue_ref(items)
    ordered_ids = [str(item.get("id")) for item in selected]

    print(f"{adapter.describe()}   File: {path}   Mode: {'DRY-RUN' if args.dry_run else 'APPLY'}")
    project_desc = adapter.project_desc()
    if project_desc:
        print(project_desc)
    print()
    print(f"{'ID':<10} {'TYPE':<6} {'ACTION':<9} {'ISSUE':<8} TITLE")

    actions: Dict[str, str] = {}
    numbers: Dict[str, str] = {}
    urls: Dict[str, str] = {}
    for item in selected:
        ticket_id = str(item.get("id"))
        title = str(item.get("title") or "")
        ticket_type = str(item.get("type") or "")
        external = item.get("external") or {}
        number = str(external.get("key") or "")
        url = str(external.get("url") or "")
        if not number:
            found = adapter.find(ticket_id)
            if found:
                number, url = found
        action = "update" if number else "create"
        actions[ticket_id] = action
        numbers[ticket_id] = number
        urls[ticket_id] = url
        print(f"{ticket_id:<10} {ticket_type:<6} {action:<9} {fmt_issue(number):<8} {title}")

    if args.dry_run:
        print()
        print("Dry run complete. No changes were made.")
        note = adapter.dry_run_note()
        if note:
            print(note)
        return 0

    print()
    print("Ensuring labels...")
    adapter.sync_labels(items)

    print("Applying...")
    created = updated = failed = 0
    for ticket_id in ordered_ids:
        item = by_id[ticket_id]
        title = f"[{ticket_id}] {item.get('title') or ''}"
        labels = labels_for(item)
        bodyfile = _write_body(item, issue_ref)
        try:
            if actions[ticket_id] == "create":
                try:
                    key, url = adapter.create(item, title, bodyfile, labels)
                except BacklogError as exc:
                    failed += 1
                    print(f"  FAILED create [{ticket_id}]: {exc}", file=sys.stderr)
                    continue
                numbers[ticket_id] = key
                urls[ticket_id] = url
                save_external(path, data, ticket_id, tracker, key, url)
                created += 1
                print(f"  created {fmt_issue(key)}  [{ticket_id}]")
            else:
                key = numbers[ticket_id]
                try:
                    adapter.update(key, item, title, bodyfile, labels)
                except BacklogError as exc:
                    failed += 1
                    print(f"  FAILED update {fmt_issue(key)} [{ticket_id}]: {exc}", file=sys.stderr)
                    continue
                save_external(path, data, ticket_id, tracker, key, urls[ticket_id])
                updated += 1
                print(f"  updated {fmt_issue(key)}  [{ticket_id}]")
        finally:
            try:
                bodyfile.unlink()
            except OSError:
                pass

    print()
    print("Linking...")
    for ticket_id in ordered_ids:
        item = by_id[ticket_id]
        external = item.get("external") or {}
        number = str(external.get("key") or "")
        if not number:
            continue
        parent = item.get("parent")
        has_deps = bool(item.get("depends_on"))
        if parent or has_deps:
            bodyfile = _write_body(item, issue_ref)
            try:
                adapter.refresh(number, item, bodyfile)
            except BacklogError as exc:
                print(f"  warn: could not refresh body of {fmt_issue(number)}: {exc}", file=sys.stderr)
            finally:
                try:
                    bodyfile.unlink()
                except OSError:
                    pass
        if parent:
            parent_key = str((by_id.get(parent, {}).get("external") or {}).get("key") or "")
            if parent_key:
                adapter.link(number, parent_key)
        adapter.project_add(number, str(external.get("url") or ""))

    print()
    print(f"Summary: created={created} updated={updated} failed={failed}")
    print(f"Tracker references were written back to {path} - commit it.")
    return 0 if failed == 0 else 1


def pull(args: argparse.Namespace) -> int:
    tracker = select_tracker(args.tracker)
    adapter = make_adapter(tracker, ROOT, CONFIG, dry=False)
    try:
        limit = int(args.limit)
    except (TypeError, ValueError):
        limit = 200
    rows = adapter.pull(args.state, args.label or "", limit)
    print(json.dumps(rows, ensure_ascii=False))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    global ROOT, CONFIG, TRACKER

    parser = argparse.ArgumentParser(
        prog="backlog.py",
        description="Push or pull tracker tickets from a neutral backlog JSON.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_push = sub.add_parser("push", help="Create/update tickets from a backlog JSON")
    p_push.add_argument("--file", required=True, help="Backlog JSON path")
    p_push.add_argument("--dry-run", action="store_true", help="Show the plan without writing")
    p_push.add_argument("--only", default="", help="Limit to one epic and its children")
    p_push.add_argument("--tracker", default=None, help="Tracker override (github|local)")

    p_pull = sub.add_parser("pull", help="List existing tickets as a JSON array")
    p_pull.add_argument("--state", default="open", choices=["open", "closed", "all"])
    p_pull.add_argument("--label", default="", help="Filter by label")
    p_pull.add_argument("--limit", default="200", help="Maximum rows (default: 200)")
    p_pull.add_argument("--tracker", default=None, help="Tracker override (github|local)")

    args = parser.parse_args(argv)

    env_root = os.environ.get("SDLC_BACKLOG_ROOT")
    ROOT = Path(env_root).resolve() if env_root else sdlc_common.find_repo_root()
    CONFIG = sdlc_common.parse_simple_yaml(ROOT / ".sdlc" / "config.yaml")
    TRACKER = select_tracker(getattr(args, "tracker", None))

    try:
        if args.action == "push":
            return push(args)
        return pull(args)
    except BacklogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
