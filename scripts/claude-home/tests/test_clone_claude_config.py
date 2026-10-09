"""Tests for clone-claude-config: per-account ~/.claude-<name> dirs symlinked to ~/.claude.

Each test runs the real bash script against a throwaway HOME. Nothing touches
the real ~/.claude.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "clone-claude-config"

# Every external command the script runs, for the PATH-without-jq fixture.
TOOLS = ("bash", "env", "find", "mv", "mkdir", "ln", "chmod", "date", "basename",
         "readlink", "wc", "tr", "mktemp", "rm", "ls", "cat", "head")


def run(home, *args, path=None):
    env = {"HOME": str(home), "PATH": path or os.environ["PATH"]}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env,
                          capture_output=True, text=True)


@pytest.fixture
def home(tmp_path):
    c = tmp_path / ".claude"
    (c / "projects").mkdir(parents=True)
    (c / "daemon").mkdir()
    (c / "settings.json").write_text("{}")
    (c / "CLAUDE.md").write_text("# rules\n")
    (tmp_path / ".claude.json").write_text(json.dumps({
        "oauthAccount": {"emailAddress": "main@x"}, "userID": "u1",
        "mcpServers": {"s": {}}}))
    return tmp_path


@pytest.fixture
def no_jq_path(tmp_path):
    bin_dir = tmp_path / "nojq-bin"
    bin_dir.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        assert found, f"{tool} not on PATH"
        (bin_dir / tool).symlink_to(found)
    assert shutil.which("jq", path=str(bin_dir)) is None
    return str(bin_dir)


def listing(d: Path):
    return sorted((p.name, p.is_symlink(), os.readlink(p) if p.is_symlink() else None)
                  for p in d.iterdir())


def links(d: Path):
    return sorted(p.name for p in d.iterdir() if p.is_symlink())


def clone(home, name="sk"):
    r = run(home, name)
    assert r.returncode == 0, r.stderr
    return home / f".claude-{name}"


# ---------------------------------------------------------------- create mode

def test_create_links_shared_entries_but_not_excluded(home):
    d = clone(home)
    assert links(d) == ["CLAUDE.md", "projects", "settings.json"]
    assert os.readlink(d / "settings.json") == str(home / ".claude" / "settings.json")


def test_create_writes_config_without_identity(home):
    d = clone(home)
    cfg = json.loads((d / ".claude.json").read_text())
    assert cfg["mcpServers"] == {"s": {}}
    assert "oauthAccount" not in cfg and "userID" not in cfg
    assert stat.S_IMODE((d / ".claude.json").stat().st_mode) == 0o600


def test_convert_carries_the_fresh_login(home):
    d = home / ".claude-sk"
    d.mkdir()
    (d / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "a@b"}}))
    r = run(home, "sk")
    assert r.returncode == 0, r.stderr
    assert len(list(home.glob(".claude-sk.fresh-*"))) == 1
    cfg = json.loads((d / ".claude.json").read_text())
    assert cfg["oauthAccount"]["emailAddress"] == "a@b"
    assert cfg["mcpServers"] == {"s": {}}


def test_linked_dir_without_sync_is_left_alone(home):
    d = clone(home)
    before = listing(d)
    r = run(home, "sk")
    assert r.returncode == 0
    assert "already linked" in r.stderr
    assert listing(d) == before


# ---------------------------------------------------------------- --sync

def test_sync_links_a_new_entry(home):
    d = clone(home)
    (home / ".claude" / "skills").mkdir()
    r = run(home, "--sync", "sk")
    assert r.returncode == 0, r.stderr
    assert "skills" in links(d)


def test_sync_prunes_a_dangling_link_into_claude(home):
    d = clone(home)
    (home / ".claude" / "CLAUDE.md").unlink()
    r = run(home, "--sync", "sk")
    assert r.returncode == 0, r.stderr
    assert not (d / "CLAUDE.md").is_symlink()


def test_sync_keeps_a_dangling_link_outside_claude(home):
    """`$HOME/.claude-other/x` shares the `$HOME/.claude` prefix but is not ours."""
    d = clone(home)
    (d / "foreign").symlink_to(home / ".claude-other" / "x")
    r = run(home, "--sync", "sk")
    assert r.returncode == 0, r.stderr
    assert (d / "foreign").is_symlink()


def test_sync_keeps_real_files_and_valid_links(home):
    d = clone(home)
    (home / ".claude" / "notes.md").write_text("src")
    (d / "notes.md").write_text("local")
    cfg_before = (d / ".claude.json").read_bytes()
    r = run(home, "--sync", "sk")
    assert r.returncode == 0, r.stderr
    assert (d / "notes.md").read_text() == "local"
    assert (d / "settings.json").is_symlink()
    assert "kept local notes.md" in r.stderr
    assert (d / ".claude.json").read_bytes() == cfg_before


def test_dry_run_sync_prints_and_changes_nothing(home):
    d = clone(home)
    (home / ".claude" / "CLAUDE.md").unlink()
    (home / ".claude" / "skills").mkdir()
    before = listing(d)
    r = run(home, "--sync", "--dry-run", "sk")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [f"link {d}/skills", f"unlink {d}/CLAUDE.md"]
    assert listing(d) == before


def test_sync_removes_links_to_names_now_excluded(home):
    d = clone(home)
    (home / ".claude" / "daemon.log").write_text("")
    (d / "daemon.log").symlink_to(home / ".claude" / "daemon.log")
    (d / "mcp-needs-auth-cache.json").write_text("{}")
    r = run(home, "--sync", "sk")
    assert r.returncode == 0, r.stderr
    assert not (d / "daemon.log").exists() and not (d / "daemon.log").is_symlink()
    assert (d / "mcp-needs-auth-cache.json").read_text() == "{}"
    assert "mcp-needs-auth-cache.json" not in r.stderr


# ---------------------------------------------------------------- error paths

def test_no_args_is_a_usage_error(home):
    r = run(home)
    assert r.returncode == 2
    assert "usage" in r.stderr.lower()


def test_empty_home_refuses(tmp_path):
    r = subprocess.run(["bash", str(SCRIPT), "sk"], env={"HOME": "", "PATH": os.environ["PATH"]},
                       capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode != 0
    assert list(tmp_path.iterdir()) == []


def test_missing_settings_json_exits_1(home):
    (home / ".claude" / "settings.json").unlink()
    assert run(home, "sk").returncode == 1


def test_missing_claude_json_exits_1_and_creates_nothing(home):
    (home / ".claude.json").unlink()
    r = run(home, "sk")
    assert r.returncode == 1
    assert not (home / ".claude-sk").exists()


def test_empty_name_refuses(home):
    r = run(home, "")
    assert r.returncode != 0
    assert not list(home.glob(".claude-*"))


def test_missing_jq_exits_1_and_creates_nothing(home, no_jq_path):
    r = run(home, "sk", path=no_jq_path)
    assert r.returncode == 1, r.stderr
    assert "jq" in r.stderr
    assert not (home / ".claude-sk").exists()


def test_dry_run_convert_prints_plan_and_changes_nothing(home):
    d = home / ".claude-sk"
    d.mkdir()
    (d / ".claude.json").write_text("{}")
    before = listing(d)
    r = run(home, "--dry-run", "sk")
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    moves = [l for l in out if l.startswith("move ")]
    assert len(moves) == 1 and moves[0].startswith(f"move {d} {d}.fresh-")
    assert out.count(f"write {d}/.claude.json") == 1
    assert sorted(l for l in out if l.startswith("link ")) == [
        f"link {d}/CLAUDE.md", f"link {d}/projects", f"link {d}/settings.json"]
    assert listing(d) == before
    assert not list(home.glob(".claude-sk.fresh-*"))


def test_unparseable_fresh_config_leaves_dir_untouched(home):
    d = home / ".claude-sk"
    d.mkdir()
    (d / ".claude.json").write_text("{not json")
    r = run(home, "sk")
    assert r.returncode == 1
    assert (d / ".claude.json").read_text() == "{not json"
    assert listing(d) == [(".claude.json", False, None)]
    assert not list(home.glob(".claude-sk.fresh-*"))
