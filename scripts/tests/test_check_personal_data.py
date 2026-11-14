"""Tests for the personal-data scanner.

Two properties matter most. Every rule has a fixture it must catch, so a clean
result is evidence and not a regex that matches nothing. And the scan refuses
to pass when it could not look: a missing or empty terms file is exit 2.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_personal_data as c  # noqa: E402


def write_terms(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "private-terms.txt"
    path.write_text(text)
    return path


def rules(line: str, terms=(), path: str = "plugins/x/skills/y/SKILL.md", allow=()) -> list[str]:
    return [f.rule for f in c.scan_text(path, line, list(terms), list(allow))]


# --- every pattern rule catches its fixture ---------------------------------

@pytest.mark.parametrize("line, rule", [
    ("B=/Users/realname/.claude/skills/x", "home-path"),
    ("cd /home/realname/project", "home-path"),
    ("contact someone@gmail.com for access", "email"),
    ("call (425) 555-0142 to confirm", "phone"),
    ("call 425-555-0142 to confirm", "phone"),
    ("https://site.test/history?student_id=7654321", "url-id"),
    ("~/Library/Mobile Documents/iCloud~md~obsidian/Documents", "icloud-vault"),
])
def test_pattern_rule_catches_fixture(line, rule):
    assert rules(line) == [rule]


@pytest.mark.parametrize("line", [
    "B=/Users/alex/dev/ledger/docs/design.md",
    "the account was student1@example.org",
    "Co-Authored-By: Someone <noreply@anthropic.com>",
    "origin is ssh://git@host.internal:2222/org/repo.git",
    "x.com/u/status/1?s=20",
    "published: 2026-03-07, duration 425-555",
    "a perfectly ordinary instruction",
])
def test_pattern_rules_pass_placeholders_and_plain_text(line):
    assert rules(line) == []


# --- private terms ------------------------------------------------------------

def test_load_terms_plain_and_case_sensitive(tmp_path):
    terms = c.load_terms(write_terms(tmp_path, "# comment\n\nSecret Vault\ncs:QZ\n"))
    assert rules("saved in secret vault today", terms) == ["private-term"]
    assert rules("signed QZ", terms) == ["private-term"]
    assert rules("signed qz", terms) == []


def test_terms_match_on_word_boundaries_only(tmp_path):
    terms = c.load_terms(write_terms(tmp_path, "cs:QZ\nvault\n"))
    assert rules("the QZX register and the vaulted roof", terms) == []


def test_load_terms_dirs_makes_each_subdirectory_a_term(tmp_path):
    projects = tmp_path / "projects"
    (projects / "example-project").mkdir(parents=True)
    (projects / "research").mkdir()
    (projects / ".hidden").mkdir()
    (projects / "a-file.txt").write_text("")
    terms = c.load_terms(write_terms(tmp_path, f"dirs:{projects}\nnot:research\n"))
    assert rules("ported from Example-Project last week", terms) == ["private-term"]
    assert rules("see the research notes", terms) == []
    assert rules("the .hidden directory and a-file.txt", terms) == []


def test_load_terms_new_directory_is_covered_without_editing_the_file(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    terms_file = write_terms(tmp_path, f"dirs:{projects}\n")
    assert rules("built for sample-app", c.load_terms(terms_file)) == []
    (projects / "sample-app").mkdir()
    assert rules("built for sample-app", c.load_terms(terms_file)) == ["private-term"]


def test_load_terms_missing_file_raises(tmp_path):
    with pytest.raises(OSError):
        c.load_terms(tmp_path / "absent.txt")


def test_load_terms_missing_dirs_target_raises(tmp_path):
    with pytest.raises(OSError):
        c.load_terms(write_terms(tmp_path, f"dirs:{tmp_path / 'absent'}\n"))


# --- allow file and marker ------------------------------------------------------

def test_ok_marker_skips_the_line():
    assert rules("mail someone@gmail.com  # personal-data-ok: public contact") == []


def test_allow_entry_blanks_only_what_it_names():
    allow = [("LICENSE", re.compile(r"Copyright \(c\) Ada"))]
    line = "Copyright (c) Ada, reach her at ada@gmail.com"
    assert rules(line, path="LICENSE", allow=allow) == ["email"]


def test_allow_entry_applies_only_to_matching_paths(tmp_path):
    terms = c.load_terms(write_terms(tmp_path, "Ada\n"))
    allow = [("LICENSE", re.compile(r"Ada"))]
    assert rules("by Ada", terms, path="LICENSE", allow=allow) == []
    assert rules("by Ada", terms, path="README.md", allow=allow) == ["private-term"]


def test_load_allow_parses_and_rejects_malformed(tmp_path):
    path = tmp_path / "allow.txt"
    path.write_text("# reason\n\nplugins/*\tfoo\\d+\n")
    assert [(g, r.pattern) for g, r in c.load_allow(path)] == [("plugins/*", "foo\\d+")]
    path.write_text("no tab here\n")
    with pytest.raises(ValueError, match="expected"):
        c.load_allow(path)


def test_load_allow_missing_file_allows_nothing(tmp_path):
    assert c.load_allow(tmp_path / "absent.txt") == []


# --- path rules -------------------------------------------------------------------

@pytest.mark.parametrize("path, flagged", [
    ("plugins/notes/templates/channels/some-channel.md", True),
    ("plugins/notes/config-defaults/channels/some-channel.md", True),
    ("plugins/notes/config-defaults/channels/example.md", False),
    ("plugins/notes/templates/youtube.md", False),
])
def test_user_config_path_rule(path, flagged):
    assert [f.rule for f in c.scan_path_rules(path)] == (["user-config-path"] if flagged else [])


def test_finding_render_and_line_numbers():
    findings = c.scan_text("a.md", "fine\nmail someone@gmail.com\n", [], [])
    assert [f.render() for f in findings] == ["a.md:2: email: someone@gmail.com"]


def test_decode_binary_is_none():
    assert c.decode(b"\x89PNG\0\0") is None
    assert c.decode(b"\xff\xfe") is None
    assert c.decode("plain é".encode()) == "plain é"


# --- main(), against a real temporary repository ------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    monkeypatch.chdir(root)
    return root


def commit_file(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text)
    subprocess.run(["git", "add", name], cwd=root, check=True)


def test_main_all_clean_exits_0(repo, tmp_path, capsys):
    commit_file(repo, "README.md", "nothing personal\n")
    terms = write_terms(tmp_path, "Secret Vault\n")
    assert c.main(["--all", "--terms", str(terms), "--allow", str(tmp_path / "none")]) == 0
    assert capsys.readouterr().out == ""


def test_main_all_reports_findings_and_exits_1(repo, tmp_path, capsys):
    commit_file(repo, "docs/guide.md", "kept in Secret Vault\n")
    terms = write_terms(tmp_path, "Secret Vault\n")
    assert c.main(["--all", "--terms", str(terms), "--allow", str(tmp_path / "none")]) == 1
    captured = capsys.readouterr()
    assert captured.out == "docs/guide.md:1: private-term: Secret Vault\n"
    assert "1 finding(s) in 1 file(s)" in captured.err


def test_main_staged_reads_the_index_not_the_working_tree(repo, tmp_path, capsys):
    commit_file(repo, "a.md", "mail someone@gmail.com\n")
    (repo / "a.md").write_text("cleaned up after staging\n")
    assert c.main(["--staged", "--no-private-terms", "--allow", str(tmp_path / "none")]) == 1
    assert "a.md:1: email: someone@gmail.com" in capsys.readouterr().out


def test_main_named_files(repo, tmp_path, capsys):
    (repo / "b.md").write_text("cd /Users/realname/x\n")
    assert c.main(["b.md", "--no-private-terms", "--allow", str(tmp_path / "none")]) == 1
    assert capsys.readouterr().out == "b.md:1: home-path: /Users/realname/\n"


def test_main_missing_terms_file_exits_2_not_0(repo, tmp_path, capsys):
    commit_file(repo, "README.md", "nothing personal\n")
    assert c.main(["--all", "--terms", str(tmp_path / "absent.txt")]) == 2
    assert "nothing was checked" in capsys.readouterr().err


def test_main_empty_terms_file_exits_2(repo, tmp_path, capsys):
    commit_file(repo, "README.md", "nothing personal\n")
    assert c.main(["--all", "--terms", str(write_terms(tmp_path, "# only a comment\n"))]) == 2
    assert "lists no terms" in capsys.readouterr().err


def test_main_no_private_terms_runs_patterns_only(repo, tmp_path):
    commit_file(repo, "README.md", "kept in Secret Vault\n")
    assert c.main(["--all", "--no-private-terms", "--allow", str(tmp_path / "none")]) == 0


def test_main_malformed_allow_file_exits_2(repo, tmp_path):
    commit_file(repo, "README.md", "x\n")
    bad = tmp_path / "allow.txt"
    bad.write_text("no tab\n")
    assert c.main(["--all", "--no-private-terms", "--allow", str(bad)]) == 2


def test_main_requires_a_mode():
    with pytest.raises(SystemExit) as exc:
        c.main([])
    assert exc.value.code == 2


def test_main_flags_user_config_path_for_binary_file(repo, tmp_path, capsys):
    (repo / "plugins/notes/templates/channels").mkdir(parents=True)
    (repo / "plugins/notes/templates/channels/pic.png").write_bytes(b"\x89PNG\0")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    assert c.main(["--all", "--no-private-terms", "--allow", str(tmp_path / "none")]) == 1
    assert "user-config-path" in capsys.readouterr().out


def test_main_does_not_scan_the_allow_file_itself(repo, tmp_path, capsys):
    terms = write_terms(tmp_path, "Ada\n")
    commit_file(repo, "scripts/allow.txt", "LICENSE\tAda\n")
    commit_file(repo, "LICENSE", "by Ada\n")
    assert c.main(["--all", "--terms", str(terms), "--allow", str(repo / "scripts/allow.txt")]) == 0
    assert capsys.readouterr().out == ""
