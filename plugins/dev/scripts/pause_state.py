#!/usr/bin/env python3
"""Durable pause state for /dev:safe-pause and /dev:safe-resume.

State root: $MK_PAUSE_ROOT, default ~/.local/state/mk-pause (never /tmp).
Layout:
    <root>/<session-name>/RESUME.md     the resume memory (YAML frontmatter + markdown body)
    <root>/.index/<session-id>          one line: the session name (lets a hook find it by id)

Subcommands (data on stdout, messages on stderr):
    snapshot      --cwd DIR                       JSON rows: every worktree with branch, tip, dirty, primary
    dirty         --cwd DIR                       exit 1 and list dirty worktree paths on stderr
    write         --session NAME --session-id ID --mode task|milestone|project --cwd DIR --body FILE
                  [--coordinator NAME] [--lander NAME]   refuses while any worktree is dirty; prints RESUME.md path
    locate        [--session-id ID] [--cwd DIR]   print the un-resumed RESUME.md for this session, exit 1 if none
    verify        --resume PATH                   exit 2 and name every worktree whose tip moved, is dirty, or is gone
    mark-resumed  --resume PATH                   stamp resumed_at so locate stops returning it
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MODES = ("task", "milestone", "project")
DEFAULT_ROOT = Path.home() / ".local" / "state" / "mk-pause"


class DirtyWorktree(Exception):
    """Raised when a pause would record a worktree that still has uncommitted work."""


def state_root() -> Path:
    return Path(os.environ.get("MK_PAUSE_ROOT") or DEFAULT_ROOT)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


# ---- worktree facts ---------------------------------------------------------

def snapshot(cwd: Path) -> list[dict]:
    """Every worktree of the repo containing `cwd`: path, branch, tip, dirty, primary.

    `primary` is the main working tree (the first `git worktree list` entry); the
    pause rules never touch it.
    """
    rows: list[dict] = []
    block: dict = {}
    for line in _git(Path(cwd), "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if block:
                rows.append(block)
                block = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            block = {"path": value}
        elif key == "HEAD":
            block["tip"] = value
        elif key == "branch":
            block["branch"] = value.removeprefix("refs/heads/")
        elif key == "detached":
            block["branch"] = None
    for i, row in enumerate(rows):
        row.setdefault("branch", None)
        row["primary"] = i == 0
        row["dirty"] = bool(_git(Path(row["path"]), "status", "--porcelain", "--untracked-files=all").strip())
    return rows


def dirty(cwd: Path) -> list[str]:
    return [r["path"] for r in snapshot(cwd) if r["dirty"]]


# ---- RESUME.md ----------------------------------------------------------------

def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return json.dumps(str(v))


def _frontmatter(fields: dict) -> str:
    out = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            out.append(f"{k}:")
            for item in v:
                first = True
                for ik, iv in item.items():
                    out.append(f"  {'- ' if first else '  '}{ik}: {_yaml_scalar(iv)}")
                    first = False
        else:
            out.append(f"{k}: {_yaml_scalar(v)}")
    out.append("---")
    return "\n".join(out) + "\n"


def read_frontmatter(path: Path) -> dict:
    """Parse the flat YAML subset this module writes (scalars + one list of flat maps)."""
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: no frontmatter")
    block = text[4:].split("\n---\n", 1)[0]
    fm: dict = {}
    current_list = None
    for raw in block.splitlines():
        if raw.startswith("  "):
            item_line = raw.strip()
            if item_line.startswith("- "):
                current_list.append({})
                item_line = item_line[2:]
            k, _, v = item_line.partition(": ")
            current_list[-1][k] = json.loads(v) if v not in ("null", "true", "false") else {"null": None, "true": True, "false": False}[v]
            continue
        k, _, v = raw.partition(":")
        v = v.strip()
        if v == "":
            fm[k] = current_list = []
        else:
            current_list = None
            fm[k] = json.loads(v) if v not in ("null", "true", "false") else {"null": None, "true": True, "false": False}[v]
    return fm


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write(root: Path, *, session: str, session_id: str, mode: str, cwd: Path, body: str,
          coordinator: str | None = None, lander: str | None = None) -> Path:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    cwd = Path(cwd).resolve()
    bad = dirty(cwd)
    if bad:
        raise DirtyWorktree("dirty worktrees, commit (wip(pause): ...) first: " + ", ".join(bad))
    fields = {
        "session": session,
        "session_id": session_id,
        "mode": mode,
        "paused_at": _now(),
        "resumed_at": None,
        "cwd": str(cwd),
        "coordinator": coordinator,
        "lander": lander,
        "worktrees": [{k: r[k] for k in ("path", "branch", "tip", "primary")} for r in snapshot(cwd)],
    }
    session_dir = Path(root) / session
    session_dir.mkdir(parents=True, exist_ok=True)
    path = session_dir / "RESUME.md"
    path.write_text(_frontmatter(fields) + "\n" + body.rstrip("\n") + "\n", encoding="utf-8")
    index = Path(root) / ".index"
    index.mkdir(parents=True, exist_ok=True)
    (index / session_id).write_text(session + "\n", encoding="utf-8")
    return path


def _candidates(root: Path) -> list[Path]:
    root = Path(root)
    return sorted(root.glob("*/RESUME.md")) if root.is_dir() else []


def locate(root: Path, *, session_id: str | None = None, cwd: Path | None = None) -> Path | None:
    """The un-resumed RESUME.md for this session: by session id first, then by cwd (newest pause wins)."""
    root = Path(root)
    if session_id:
        pointer = root / ".index" / session_id
        if pointer.is_file():
            path = root / pointer.read_text().strip() / "RESUME.md"
            if path.is_file() and read_frontmatter(path).get("resumed_at") is None:
                return path
    if cwd:
        want = str(Path(cwd).resolve())
        live = [p for p in _candidates(root) if (fm := read_frontmatter(p)).get("cwd") == want and fm.get("resumed_at") is None]
        if live:
            return max(live, key=lambda p: read_frontmatter(p)["paused_at"])
    return None


def verify(path: Path) -> list[dict]:
    """Problems that make the recorded state unsafe to continue from. Empty means go."""
    fm = read_frontmatter(path)
    problems = []
    for rec in fm.get("worktrees", []):
        wt = Path(rec["path"])
        if not (wt / ".git").exists():
            problems.append({**rec, "reason": "missing", "expected": rec["tip"], "actual": None})
            continue
        actual = _git(wt, "rev-parse", "HEAD").strip()
        if actual != rec["tip"]:
            problems.append({**rec, "reason": "tip-moved", "expected": rec["tip"], "actual": actual})
        elif _git(wt, "status", "--porcelain", "--untracked-files=all").strip():
            problems.append({**rec, "reason": "dirty", "expected": rec["tip"], "actual": actual})
    return problems


def mark_resumed(path: Path) -> None:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    head, sep, tail = text[4:].partition("\n---\n")
    lines = [f"resumed_at: {_yaml_scalar(_now())}" if l.startswith("resumed_at:") else l for l in head.splitlines()]
    path.write_text("---\n" + "\n".join(lines) + sep + tail, encoding="utf-8")


# ---- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pause_state.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot"); p.add_argument("--cwd", required=True)
    p = sub.add_parser("dirty"); p.add_argument("--cwd", required=True)
    p = sub.add_parser("write")
    p.add_argument("--session", required=True); p.add_argument("--session-id", required=True)
    p.add_argument("--mode", required=True, choices=MODES); p.add_argument("--cwd", required=True)
    p.add_argument("--body", required=True, help="markdown file with the resume sections")
    p.add_argument("--coordinator"); p.add_argument("--lander")
    p = sub.add_parser("locate"); p.add_argument("--session-id"); p.add_argument("--cwd")
    p = sub.add_parser("verify"); p.add_argument("--resume", required=True)
    p = sub.add_parser("mark-resumed"); p.add_argument("--resume", required=True)
    a = ap.parse_args(argv)
    root = state_root()

    if a.cmd == "snapshot":
        print(json.dumps(snapshot(Path(a.cwd)), indent=2))
    elif a.cmd == "dirty":
        bad = dirty(Path(a.cwd))
        for p in bad:
            print(p, file=sys.stderr)
        return 1 if bad else 0
    elif a.cmd == "write":
        try:
            print(write(root, session=a.session, session_id=a.session_id, mode=a.mode, cwd=Path(a.cwd),
                        body=Path(a.body).read_text(encoding="utf-8"), coordinator=a.coordinator, lander=a.lander))
        except DirtyWorktree as e:
            print(e, file=sys.stderr)
            return 1
    elif a.cmd == "locate":
        found = locate(root, session_id=a.session_id, cwd=Path(a.cwd) if a.cwd else None)
        if not found:
            return 1
        print(found)
    elif a.cmd == "verify":
        problems = verify(Path(a.resume))
        for p in problems:
            print(f"{p['reason']}: {p['branch']} at {p['path']} expected {p['expected']} got {p['actual']}", file=sys.stderr)
        return 2 if problems else 0
    elif a.cmd == "mark-resumed":
        mark_resumed(Path(a.resume))
    return 0


if __name__ == "__main__":
    sys.exit(main())
