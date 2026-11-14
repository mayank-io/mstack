"""Tests for the config seeder.

The property that matters: a file the user already has is never overwritten,
and an unreadable manifest writes nothing.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seed_config as s  # noqa: E402


def make_plugin(base: Path, name: str, files: dict[str, str]) -> Path:
    plugin_dir = base / name
    for rel, text in files.items():
        path = plugin_dir / s.DEFAULTS_DIRNAME / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    plugin_dir.mkdir(parents=True, exist_ok=True)
    return plugin_dir


def write_manifest(plugins_root: Path, installs: dict[str, Path]) -> None:
    plugins_root.mkdir(parents=True, exist_ok=True)
    data = {"version": 2, "plugins": {key: [{"installPath": str(path)}] for key, path in installs.items()}}
    (plugins_root / "installed_plugins.json").write_text(json.dumps(data))


def test_seed_plugin_copies_nested_defaults(tmp_path):
    plugin = make_plugin(tmp_path / "src", "notes", {"channels/example.md": "x", "top.json": "{}"})
    home = tmp_path / "home"
    results = s.seed_plugin("notes", plugin, home, dry_run=False)
    assert results == [("created", home / "notes/channels/example.md"), ("created", home / "notes/top.json")]
    assert (home / "notes/channels/example.md").read_text() == "x"


def test_seed_plugin_never_overwrites(tmp_path):
    plugin = make_plugin(tmp_path / "src", "dev", {"feedback-tags.json": "default"})
    home = tmp_path / "home"
    (home / "dev").mkdir(parents=True)
    (home / "dev/feedback-tags.json").write_text("mine")
    assert s.seed_plugin("dev", plugin, home, dry_run=False) == [("kept", home / "dev/feedback-tags.json")]
    assert (home / "dev/feedback-tags.json").read_text() == "mine"


def test_seed_plugin_dry_run_writes_nothing(tmp_path):
    plugin = make_plugin(tmp_path / "src", "dev", {"feedback-tags.json": "default"})
    home = tmp_path / "home"
    assert s.seed_plugin("dev", plugin, home, dry_run=True) == [("created", home / "dev/feedback-tags.json")]
    assert not home.exists()


def test_seed_plugin_without_defaults_dir(tmp_path):
    plugin = make_plugin(tmp_path / "src", "think", {})
    assert s.seed_plugin("think", plugin, tmp_path / "home", dry_run=False) == []


def test_find_installed_plugins_filters_by_marketplace(tmp_path):
    root = tmp_path / "plugins"
    write_manifest(root, {"dev@mstack": tmp_path / "a", "other@elsewhere": tmp_path / "b"})
    assert s.find_installed_plugins(root, "mstack") == {"dev": tmp_path / "a"}


def test_find_installed_plugins_unreadable_is_none(tmp_path):
    assert s.find_installed_plugins(tmp_path / "missing", "mstack") is None
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text("{not json")
    assert s.find_installed_plugins(root, "mstack") is None


def test_find_installed_plugins_empty_is_not_none(tmp_path):
    root = tmp_path / "plugins"
    write_manifest(root, {})
    assert s.find_installed_plugins(root, "mstack") == {}


def test_default_plugins_root_honours_claude_config_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "alt"))
    assert s.default_plugins_root() == tmp_path / "alt" / "plugins"


def test_main_from_manifest(tmp_path, capsys):
    plugin = make_plugin(tmp_path / "cache", "dev", {"feedback-tags.json": "default"})
    root = tmp_path / "plugins"
    write_manifest(root, {"dev@mstack": plugin})
    home = tmp_path / "home"
    assert s.main(["--plugins-root", str(root), "--home", str(home)]) == 0
    assert capsys.readouterr().out == f"created {home / 'dev/feedback-tags.json'}\n"
    assert s.main(["--plugins-root", str(root), "--home", str(home)]) == 0
    assert capsys.readouterr().out == f"kept {home / 'dev/feedback-tags.json'}\n"


def test_main_unreadable_manifest_exits_2_and_writes_nothing(tmp_path, capsys):
    home = tmp_path / "home"
    assert s.main(["--plugins-root", str(tmp_path / "missing"), "--home", str(home)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot read" in captured.err
    assert not home.exists()


def test_main_from_checkout(tmp_path, capsys):
    plugins_dir = tmp_path / "plugins"
    make_plugin(plugins_dir, "notes", {"channels/example.md": "x"})
    make_plugin(plugins_dir, "think", {})
    home = tmp_path / "home"
    assert s.main(["--plugins-dir", str(plugins_dir), "--home", str(home)]) == 0
    assert capsys.readouterr().out == f"created {home / 'notes/channels/example.md'}\n"


def test_main_checkout_dir_missing_exits_2(tmp_path, capsys):
    assert s.main(["--plugins-dir", str(tmp_path / "nope"), "--home", str(tmp_path / "home")]) == 2
    assert "is not a directory" in capsys.readouterr().err


def test_repo_defaults_are_seedable(tmp_path):
    """The real plugins/ tree seeds the two config files the skills read."""
    plugins_dir = Path(__file__).resolve().parents[3]
    home = tmp_path / "home"
    assert s.main(["--plugins-dir", str(plugins_dir), "--home", str(home)]) == 0
    assert json.loads((home / "dev/feedback-tags.json").read_text())["tags"][0]["tag"] == "REV"
    assert (home / "notes/channels/example.md").is_file()
