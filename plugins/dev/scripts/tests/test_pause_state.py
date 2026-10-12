"""Tests for pause_state.py: the durable state behind /dev:safe-pause and /dev:safe-resume.

Every test runs against throwaway git repos and a throwaway state root, so nothing
touches ~/.local/state. The contract pinned here: a pause leaves every worktree
clean with a recorded tip, and a resume refuses when any tip has moved.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pause_state as ps  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("a\n")
    git(r, "add", "a.txt")
    git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def other_repo(tmp_path):
    r = tmp_path / "other"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("a\n")
    git(r, "add", "a.txt")
    git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def state_root(tmp_path):
    return tmp_path / "state"


def add_worktree(repo, name):
    wt = repo.parent / f"wt-{repo.name}-{name}"
    git(repo, "worktree", "add", "-q", "-b", name, str(wt))
    return wt


# ---- snapshot ---------------------------------------------------------------

def test_snapshot_lists_every_worktree_with_branch_and_tip(repo):
    wt = add_worktree(repo, "feat")
    rows = ps.snapshot(repo)
    by_path = {Path(r["path"]).resolve(): r for r in rows}
    assert set(by_path) == {repo.resolve(), wt.resolve()}
    assert by_path[repo.resolve()]["branch"] == "main"
    assert by_path[wt.resolve()]["branch"] == "feat"
    assert by_path[wt.resolve()]["tip"] == git(wt, "rev-parse", "HEAD")
    assert all(r["dirty"] is False for r in rows)


def test_snapshot_flags_dirty_worktrees(repo):
    wt = add_worktree(repo, "feat")
    (wt / "b.txt").write_text("b\n")  # untracked counts as dirty
    (repo / "a.txt").write_text("changed\n")  # modified counts as dirty
    rows = {Path(r["path"]).resolve(): r for r in ps.snapshot(repo)}
    assert rows[wt.resolve()]["dirty"] is True
    assert rows[repo.resolve()]["dirty"] is True


def test_snapshot_marks_primary_main_so_it_is_never_touched(repo):
    add_worktree(repo, "feat")
    rows = {r["branch"]: r for r in ps.snapshot(repo)}
    assert rows["main"]["primary"] is True
    assert rows["feat"]["primary"] is False


# ---- dirty ------------------------------------------------------------------

def test_dirty_returns_only_dirty_paths(repo):
    wt = add_worktree(repo, "feat")
    (wt / "b.txt").write_text("b\n")
    assert [Path(p).resolve() for p in ps.dirty(repo)] == [wt.resolve()]


def test_dirty_ignores_the_primary_checkout(repo):
    add_worktree(repo, "feat")
    (repo / "untracked.txt").write_text("not ours\n")
    assert ps.dirty(repo) == []


def test_dirty_is_empty_when_everything_is_committed(repo):
    add_worktree(repo, "feat")
    assert ps.dirty(repo) == []


# ---- write / locate ---------------------------------------------------------

def test_write_creates_resume_under_session_dir_and_indexes_session_id(repo, state_root):
    path = ps.write(
        state_root,
        session="mstack-main",
        session_id="abc-123",
        mode="task",
        cwd=repo,
        body="## In-flight\n\nnothing\n",
    )
    assert path == state_root / "mstack-main" / "RESUME.md"
    text = path.read_text()
    assert text.startswith("---\n")
    fm = ps.read_frontmatter(path)
    assert fm["session"] == "mstack-main"
    assert fm["session_id"] == "abc-123"
    assert fm["mode"] == "task"
    assert fm["cwd"] == str(repo)
    assert fm["paused_at"].endswith(("+00:00", "Z")) or "+" in fm["paused_at"] or "-" in fm["paused_at"][10:]
    assert fm["worktrees"][0]["branch"] == "main"
    assert "## In-flight" in text
    assert ps.locate(state_root, session_id="abc-123") == path


def test_write_refuses_when_an_owned_worktree_is_dirty(repo, state_root):
    wt = add_worktree(repo, "feat")
    (wt / "b.txt").write_text("dirty\n")
    with pytest.raises(ps.DirtyWorktree) as e:
        ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    assert str(wt.resolve()) in str(e.value)


def test_write_rejects_unknown_mode(repo, state_root):
    with pytest.raises(ValueError):
        ps.write(state_root, session="s", session_id="id", mode="sprint", cwd=repo, body="")


def test_locate_falls_back_to_cwd_when_session_id_unknown(repo, state_root):
    path = ps.write(state_root, session="s", session_id="id-1", mode="task", cwd=repo, body="")
    assert ps.locate(state_root, cwd=repo) == path


def test_locate_returns_none_when_nothing_is_paused(repo, state_root):
    assert ps.locate(state_root, session_id="nope", cwd=repo) is None


def test_locate_ignores_already_resumed_state(repo, state_root):
    path = ps.write(state_root, session="s", session_id="id-1", mode="task", cwd=repo, body="")
    ps.mark_resumed(path)
    assert ps.locate(state_root, session_id="id-1", cwd=repo) is None
    assert ps.read_frontmatter(path)["resumed_at"]


# ---- primary checkout is a baseline, not a gate --------------------------------

def test_write_accepts_untracked_files_in_the_primary_checkout(repo, state_root):
    add_worktree(repo, "feat")
    (repo / "docs").mkdir()
    (repo / "docs" / "app.json").write_text("{}\n")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    primary = [w for w in ps.read_frontmatter(path)["worktrees"] if w["primary"]][0]
    assert primary["baseline_count"] == 1
    assert len(primary["baseline_sha"]) == 64
    assert ps.verify(path) == []


def test_verify_warns_when_the_primary_baseline_changes(repo, state_root):
    add_worktree(repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    (repo / "new.txt").write_text("x\n")
    assert ps.verify(path) == []
    assert [w["reason"] for w in ps.verify(path, warnings=True)] == ["primary-changed"]


def test_verify_warns_but_does_not_refuse_when_primary_tip_moves(repo, state_root):
    add_worktree(repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    (repo / "a.txt").write_text("landed by someone else\n")
    git(repo, "commit", "-qam", "lander")
    assert ps.verify(path) == []
    assert [w["reason"] for w in ps.verify(path, warnings=True)] == ["primary-tip-moved"]


# ---- several repos ---------------------------------------------------------------

def test_write_records_worktrees_from_every_repo(repo, other_repo, state_root):
    a = add_worktree(repo, "feat")
    b = add_worktree(other_repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", repos=[repo, other_repo], body="")
    fm = ps.read_frontmatter(path)
    paths = {Path(w["path"]).resolve() for w in fm["worktrees"]}
    assert {a.resolve(), b.resolve(), repo.resolve(), other_repo.resolve()} <= paths
    assert [Path(r["path"]).resolve() for r in fm["repos"]] == [repo.resolve(), other_repo.resolve()]


def test_verify_checks_tips_in_the_second_repo(repo, other_repo, state_root):
    add_worktree(repo, "feat")
    b = add_worktree(other_repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", repos=[repo, other_repo], body="")
    (b / "c.txt").write_text("c\n")
    git(b, "add", "c.txt"); git(b, "commit", "-qm", "moved")
    problems = ps.verify(path)
    assert [(Path(p["path"]).resolve(), p["reason"]) for p in problems] == [(b.resolve(), "tip-moved")]


def test_write_refuses_a_dirty_worktree_in_the_second_repo(repo, other_repo, state_root):
    b = add_worktree(other_repo, "feat")
    (b / "x.txt").write_text("x\n")
    with pytest.raises(ps.DirtyWorktree):
        ps.write(state_root, session="s", session_id="id", mode="task", repos=[repo, other_repo], body="")


def test_locate_finds_state_from_any_recorded_repo(repo, other_repo, state_root):
    path = ps.write(state_root, session="s", session_id="id", mode="task", repos=[repo, other_repo], body="")
    assert ps.locate(state_root, cwd=other_repo) == path


def test_write_rejects_no_repo(state_root):
    with pytest.raises(ValueError):
        ps.write(state_root, session="s", session_id="id", mode="task", repos=[], body="")


# ---- owned worktrees only --------------------------------------------------------

def test_owned_limits_recording_to_named_branches(repo, state_root):
    mine = add_worktree(repo, "mine")
    theirs = add_worktree(repo, "theirs")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, owned=["mine"], body="")
    recorded = {Path(w["path"]).resolve() for w in ps.read_frontmatter(path)["worktrees"] if not w["primary"]}
    assert recorded == {mine.resolve()}
    (theirs / "t.txt").write_text("t\n")
    git(theirs, "add", "t.txt"); git(theirs, "commit", "-qm", "another session")
    assert ps.verify(path) == []


def test_owned_ignores_dirty_worktrees_of_other_sessions(repo, state_root):
    add_worktree(repo, "mine")
    theirs = add_worktree(repo, "theirs")
    (theirs / "wip.txt").write_text("not mine\n")
    ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, owned=["mine"], body="")


def test_owned_accepts_a_worktree_path(repo, state_root):
    mine = add_worktree(repo, "mine")
    add_worktree(repo, "theirs")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, owned=[str(mine)], body="")
    recorded = [w["branch"] for w in ps.read_frontmatter(path)["worktrees"] if not w["primary"]]
    assert recorded == ["mine"]


def test_owned_name_that_matches_nothing_is_an_error(repo, state_root):
    add_worktree(repo, "mine")
    with pytest.raises(ValueError) as e:
        ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, owned=["mnie"], body="")
    assert "mnie" in str(e.value)


def test_verify_still_reads_state_written_before_repos_existed(repo, state_root):
    path = state_root / "old" / "RESUME.md"
    path.parent.mkdir(parents=True)
    tip = git(repo, "rev-parse", "HEAD")
    path.write_text(f'---\nsession: "old"\nresumed_at: null\ncwd: "{repo}"\nworktrees:\n  - path: "{repo}"\n    branch: "main"\n    tip: "{tip}"\n    primary: true\n---\n')
    (repo / "a.txt").write_text("landed\n"); git(repo, "commit", "-qam", "landed")
    assert ps.verify(path) == []


# ---- verify -----------------------------------------------------------------

def test_verify_passes_when_every_tip_matches(repo, state_root):
    add_worktree(repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    assert ps.verify(path) == []


def test_verify_names_the_worktree_whose_tip_moved(repo, state_root):
    wt = add_worktree(repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    (wt / "c.txt").write_text("c\n")
    git(wt, "add", "c.txt")
    git(wt, "commit", "-qm", "moved")
    problems = ps.verify(path)
    assert len(problems) == 1
    assert problems[0]["branch"] == "feat"
    assert problems[0]["reason"] == "tip-moved"
    assert problems[0]["expected"] != problems[0]["actual"]


def test_verify_names_a_worktree_that_disappeared(repo, state_root):
    wt = add_worktree(repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    git(repo, "worktree", "remove", "--force", str(wt))
    problems = ps.verify(path)
    assert [p["reason"] for p in problems] == ["missing"]


def test_verify_names_a_worktree_that_is_dirty_now(repo, state_root):
    wt = add_worktree(repo, "feat")
    path = ps.write(state_root, session="s", session_id="id", mode="task", cwd=repo, body="")
    (wt / "c.txt").write_text("c\n")
    problems = ps.verify(path)
    assert [p["reason"] for p in problems] == ["dirty"]


# ---- CLI ---------------------------------------------------------------------

SCRIPT = Path(__file__).resolve().parents[1] / "pause_state.py"


def cli(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env)


def test_cli_help_exits_zero():
    r = cli("--help")
    assert r.returncode == 0
    assert "safe-pause" in r.stdout


def test_cli_snapshot_prints_json_rows(repo):
    r = cli("snapshot", "--cwd", str(repo))
    assert r.returncode == 0
    assert json.loads(r.stdout)[0]["branch"] == "main"


def test_cli_dirty_exits_one_and_lists_paths_on_stderr(repo):
    wt = add_worktree(repo, "feat")
    (wt / "a.txt").write_text("x\n")
    r = cli("dirty", "--cwd", str(repo))
    assert r.returncode == 1
    assert str(wt.resolve()) in r.stderr


def test_cli_write_then_locate_then_verify_then_mark(repo, state_root, tmp_path):
    body = tmp_path / "body.md"
    body.write_text("## Queue\n\n1. x\n")
    env = {**os.environ, "MK_PAUSE_ROOT": str(state_root)}
    r = cli("write", "--session", "s", "--session-id", "id", "--mode", "milestone", "--cwd", str(repo), "--body", str(body), env=env)
    assert r.returncode == 0, r.stderr
    path = Path(r.stdout.strip())
    assert path.exists()
    r = cli("locate", "--session-id", "id", env=env)
    assert r.stdout.strip() == str(path)
    r = cli("verify", "--resume", str(path))
    assert r.returncode == 0
    r = cli("mark-resumed", "--resume", str(path), env=env)
    assert r.returncode == 0
    r = cli("locate", "--session-id", "id", env=env)
    assert r.returncode == 1 and r.stdout == ""


def test_cli_verify_exits_two_and_names_mismatch(repo, state_root, tmp_path):
    env = {**os.environ, "MK_PAUSE_ROOT": str(state_root)}
    wt = add_worktree(repo, "feat")
    body = tmp_path / "b.md"; body.write_text("")
    path = Path(cli("write", "--session", "s", "--session-id", "id", "--mode", "task", "--cwd", str(repo), "--body", str(body), env=env).stdout.strip())
    (wt / "a.txt").write_text("moved\n")
    git(wt, "commit", "-qam", "moved")
    r = cli("verify", "--resume", str(path))
    assert r.returncode == 2
    assert "feat" in r.stderr and "tip-moved" in r.stderr


def test_cli_write_takes_several_repos_and_owned_branches(repo, other_repo, state_root, tmp_path):
    env = {**os.environ, "MK_PAUSE_ROOT": str(state_root)}
    add_worktree(repo, "feat"); add_worktree(repo, "theirs"); add_worktree(other_repo, "feat")
    body = tmp_path / "b.md"; body.write_text("")
    r = cli("write", "--session", "s", "--session-id", "id", "--mode", "task",
            "--repo", str(repo), "--repo", str(other_repo), "--owned", "feat", "--body", str(body), env=env)
    assert r.returncode == 0, r.stderr
    fm = ps.read_frontmatter(Path(r.stdout.strip()))
    owned = sorted((Path(w["repo"]).name, w["branch"]) for w in fm["worktrees"] if not w["primary"])
    assert owned == [("other", "feat"), ("repo", "feat")]


def test_cli_verify_prints_warnings_but_exits_zero(repo, state_root, tmp_path):
    env = {**os.environ, "MK_PAUSE_ROOT": str(state_root)}
    add_worktree(repo, "feat")
    body = tmp_path / "b.md"; body.write_text("")
    path = cli("write", "--session", "s", "--session-id", "id", "--mode", "task", "--cwd", str(repo), "--body", str(body), env=env).stdout.strip()
    (repo / "new.txt").write_text("x\n")
    r = cli("verify", "--resume", path)
    assert r.returncode == 0
    assert "warning" in r.stderr and "primary-changed" in r.stderr
