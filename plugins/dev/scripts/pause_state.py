#!/usr/bin/env python3
"""Durable pause state for /dev:safe-pause and /dev:safe-resume.

State root: $MK_PAUSE_ROOT, default ~/.local/state/mk-pause (never /tmp).
Layout:
    <root>/<session-name>/RESUME.md     the resume memory (YAML frontmatter + markdown body)
    <root>/.index/<session-id>          one line: the session name (lets a hook find it by id)

What is recorded, per repo the session worked in:
    owned worktrees    every non-primary worktree, or only those named with --owned.
                       Must be clean to pause; on resume, tip moved / dirty / missing refuses.
    primary checkout   recorded as a baseline (tip, plus a hash of its uncommitted files),
                       never required clean: the pause rules forbid touching it, and other
                       sessions may land onto it. On resume a change is a warning, not a refusal.

Subcommands (data on stdout, messages on stderr). --repo is repeatable; --cwd is its alias.
    snapshot      --repo DIR...                         JSON rows: every worktree with repo, branch, tip, dirty, primary
    dirty         --repo DIR... [--owned B...]          exit 1 and list dirty owned worktrees on stderr
    write         --session NAME --session-id ID --mode task|milestone|project --repo DIR...
                  [--owned BRANCH_OR_PATH...] --body FILE [--coordinator NAME] [--lander NAME]
                                                        refuses while an owned worktree is dirty; prints RESUME.md path
    locate        [--session-id ID] [--cwd DIR]         print the un-resumed RESUME.md for this session, exit 1 if none
    verify        --resume PATH                         exit 2 naming owned worktrees whose tip moved, are dirty or gone;
                                                        primary-checkout changes print as warnings and exit 0
    mark-resumed  --resume PATH                         stamp resumed_at so locate stops returning it
"""
from __future__ import annotations

import argparse
import hashlib
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

def _status(path: Path) -> list[str]:
    return sorted(_git(path, "status", "--porcelain", "--untracked-files=all").splitlines())


def snapshot(cwd: Path) -> list[dict]:
    """Every worktree of the repo containing `cwd`: repo, path, branch, tip, dirty, primary.

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
    repo = rows[0]["path"] if rows else str(Path(cwd).resolve())
    for i, row in enumerate(rows):
        row.setdefault("branch", None)
        row["repo"] = repo
        row["primary"] = i == 0
        row["status"] = _status(Path(row["path"]))
        row["dirty"] = bool(row["status"])
    return rows


def _owned_rows(repos: list[Path], owned: list[str] | None) -> tuple[list[dict], list[dict]]:
    """(primaries, owned worktrees) across `repos`.

    With no `owned`, every non-primary worktree counts as the session's. Otherwise only
    worktrees whose branch name or resolved path is listed; a name matching nothing is an
    error, because a typo would otherwise record nothing and look like a clean pause.
    """
    rows = [r for repo in repos for r in snapshot(repo)]
    primaries = [r for r in rows if r["primary"]]
    others = [r for r in rows if not r["primary"]]
    if owned is None:
        return primaries, others
    keys = {o: (o, str(Path(o).expanduser().resolve())) for o in owned}
    picked = [r for r in others if any(r["branch"] == k[0] or str(Path(r["path"]).resolve()) == k[1] for k in keys.values())]
    missing = [o for o, k in keys.items()
               if not any(r["branch"] == k[0] or str(Path(r["path"]).resolve()) == k[1] for r in others)]
    if missing:
        raise ValueError("--owned matches no worktree in the given repos: " + ", ".join(missing))
    return primaries, picked


def dirty(cwd: Path | None = None, *, repos: list[Path] | None = None, owned: list[str] | None = None) -> list[str]:
    """Paths of owned worktrees with uncommitted work. The primary checkout is never listed."""
    _, rows = _owned_rows(_repo_list(cwd, repos), owned)
    return [r["path"] for r in rows if r["dirty"]]


def _repo_list(cwd: Path | None, repos: list[Path] | None) -> list[Path]:
    out = list(repos or []) + ([cwd] if cwd is not None else [])
    if not out:
        raise ValueError("at least one repo is required")
    seen, uniq = set(), []
    for r in out:
        top = Path(_git(Path(r), "rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent
        if top not in seen:
            seen.add(top)
            uniq.append(Path(r).resolve())
    return uniq


def _baseline(status: list[str]) -> str:
    return hashlib.sha256("\n".join(status).encode()).hexdigest()


# ---- RESUME.md ----------------------------------------------------------------

def _yaml_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
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


def write(root: Path, *, session: str, session_id: str, mode: str, body: str,
          cwd: Path | None = None, repos: list[Path] | None = None, owned: list[str] | None = None,
          coordinator: str | None = None, lander: str | None = None) -> Path:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    repo_paths = _repo_list(cwd, repos)
    primaries, mine = _owned_rows(repo_paths, owned)
    bad = [r["path"] for r in mine if r["dirty"]]
    if bad:
        raise DirtyWorktree("dirty worktrees, commit (wip(pause): ...) first: " + ", ".join(bad))
    worktrees = [
        {"repo": r["repo"], "path": r["path"], "branch": r["branch"], "tip": r["tip"], "primary": True,
         "baseline_sha": _baseline(r["status"]), "baseline_count": len(r["status"])}
        for r in primaries
    ] + [
        {"repo": r["repo"], "path": r["path"], "branch": r["branch"], "tip": r["tip"], "primary": False}
        for r in mine
    ]
    fields = {
        "session": session,
        "session_id": session_id,
        "mode": mode,
        "paused_at": _now(),
        "resumed_at": None,
        "cwd": str(repo_paths[0]),
        "coordinator": coordinator,
        "lander": lander,
        "repos": [{"path": str(p)} for p in repo_paths],
        "worktrees": worktrees,
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
        def recorded(fm: dict) -> set[str]:
            return {fm.get("cwd")} | {r["path"] for r in fm.get("repos", [])}
        live = [p for p in _candidates(root)
                if want in recorded(fm := read_frontmatter(p)) and fm.get("resumed_at") is None]
        if live:
            return max(live, key=lambda p: read_frontmatter(p)["paused_at"])
    return None


def verify(path: Path, *, warnings: bool = False) -> list[dict]:
    """Problems that make the recorded state unsafe to continue from. Empty means go.

    Owned worktrees refuse on `missing`, `tip-moved` or `dirty`. The primary checkout
    never refuses: with `warnings=True` this returns its changes instead
    (`primary-tip-moved`, `primary-changed`), which the caller reports and continues past.
    """
    fm = read_frontmatter(path)
    problems, notes = [], []
    for rec in fm.get("worktrees", []):
        wt = Path(rec["path"])
        if rec.get("primary"):
            if not (wt / ".git").exists():
                notes.append({**rec, "reason": "primary-missing", "expected": rec["tip"], "actual": None})
                continue
            actual = _git(wt, "rev-parse", "HEAD").strip()
            if actual != rec["tip"]:
                notes.append({**rec, "reason": "primary-tip-moved", "expected": rec["tip"], "actual": actual})
            if "baseline_sha" in rec and _baseline(_status(wt)) != rec["baseline_sha"]:
                notes.append({**rec, "reason": "primary-changed", "expected": rec["tip"], "actual": actual})
            continue
        if not (wt / ".git").exists():
            problems.append({**rec, "reason": "missing", "expected": rec["tip"], "actual": None})
            continue
        actual = _git(wt, "rev-parse", "HEAD").strip()
        if actual != rec["tip"]:
            problems.append({**rec, "reason": "tip-moved", "expected": rec["tip"], "actual": actual})
        elif _status(wt):
            problems.append({**rec, "reason": "dirty", "expected": rec["tip"], "actual": actual})
    return notes if warnings else problems


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

    def repo_args(p: argparse.ArgumentParser, owned: bool) -> None:
        p.add_argument("--repo", "--cwd", dest="repos", action="append", required=True,
                       help="a repo (any of its worktrees) the session worked in; repeat for each")
        if owned:
            p.add_argument("--owned", action="append",
                           help="branch name or worktree path the session owns; repeat. Default: every non-primary worktree")

    p = sub.add_parser("snapshot"); repo_args(p, owned=False)
    p = sub.add_parser("dirty"); repo_args(p, owned=True)
    p = sub.add_parser("write")
    p.add_argument("--session", required=True); p.add_argument("--session-id", required=True)
    p.add_argument("--mode", required=True, choices=MODES); repo_args(p, owned=True)
    p.add_argument("--body", required=True, help="markdown file with the resume sections")
    p.add_argument("--coordinator"); p.add_argument("--lander")
    p = sub.add_parser("locate"); p.add_argument("--session-id"); p.add_argument("--cwd")
    p = sub.add_parser("verify"); p.add_argument("--resume", required=True)
    p = sub.add_parser("mark-resumed"); p.add_argument("--resume", required=True)
    a = ap.parse_args(argv)
    root = state_root()
    repos = [Path(r) for r in getattr(a, "repos", None) or []]

    try:
        if a.cmd == "snapshot":
            rows = [{k: v for k, v in r.items() if k != "status"} for repo in repos for r in snapshot(repo)]
            print(json.dumps(rows, indent=2))
        elif a.cmd == "dirty":
            bad = dirty(repos=repos, owned=a.owned)
            for p in bad:
                print(p, file=sys.stderr)
            return 1 if bad else 0
        elif a.cmd == "write":
            print(write(root, session=a.session, session_id=a.session_id, mode=a.mode, repos=repos, owned=a.owned,
                        body=Path(a.body).read_text(encoding="utf-8"), coordinator=a.coordinator, lander=a.lander))
        elif a.cmd == "locate":
            found = locate(root, session_id=a.session_id, cwd=Path(a.cwd) if a.cwd else None)
            if not found:
                return 1
            print(found)
        elif a.cmd == "verify":
            for w in verify(Path(a.resume), warnings=True):
                print(f"warning: {w['reason']}: {w['branch']} at {w['path']} recorded {w['expected']} now {w['actual']}", file=sys.stderr)
            problems = verify(Path(a.resume))
            for p in problems:
                print(f"{p['reason']}: {p['branch']} at {p['path']} expected {p['expected']} got {p['actual']}", file=sys.stderr)
            return 2 if problems else 0
        elif a.cmd == "mark-resumed":
            mark_resumed(Path(a.resume))
    except (DirtyWorktree, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
