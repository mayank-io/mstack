"""Tests for the plugin-cache pruner.

This script deletes directories, so the safety properties are the point:
a pinned plugin must survive every path through the code, and an unreadable
manifest must delete nothing at all.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import prune_plugin_cache as p  # noqa: E402


def build(tmp_path, tree, pinned=None, manifest=True):
    """tree = {marketplace: {plugin: [sha, ...]}}; pinned = [(mk, plug, sha)]."""
    root = tmp_path / "plugins"
    cache = root / "cache"
    for mk, plugs in tree.items():
        for plug, shas in plugs.items():
            for sha in shas:
                d = cache / mk / plug / sha
                d.mkdir(parents=True)
                (d / "SKILL.md").write_text("x", encoding="utf-8")
    if manifest:
        plugins = {}
        for mk, plug, sha in (pinned or []):
            plugins[f"{plug}@{mk}"] = [{"installPath": str(cache / mk / plug / sha)}]
        (root / "installed_plugins.json").write_text(
            json.dumps({"version": 1, "plugins": plugins}), encoding="utf-8")
    return root


def shas(root, mk, plug):
    d = root / "cache" / mk / plug
    return sorted(os.listdir(d)) if d.is_dir() else []


# ---------------------------------------------------------------- core

def test_removes_the_orphan_keeps_the_pinned(tmp_path):
    """The exact shape `claude plugin update` leaves behind."""
    root = build(tmp_path, {"mstack": {"notes": ["oldsha", "newsha"]}},
                 pinned=[("mstack", "notes", "newsha")])
    assert p.main(["--root", str(root)]) == 0
    assert shas(root, "mstack", "notes") == ["newsha"]


def test_prunes_across_marketplaces_and_plugins(tmp_path):
    root = build(tmp_path, {
        "mstack": {"notes": ["a", "b"], "fetch": ["a", "b"]},
        "mk": {"kuber": ["c", "d"]},
    }, pinned=[("mstack", "notes", "b"), ("mstack", "fetch", "b"), ("mk", "kuber", "d")])
    assert p.main(["--root", str(root)]) == 0
    assert shas(root, "mstack", "notes") == ["b"]
    assert shas(root, "mstack", "fetch") == ["b"]
    assert shas(root, "mk", "kuber") == ["d"]


def test_three_stale_generations_all_go(tmp_path):
    """Updates accumulate. Two rounds of updating leaves three copies."""
    root = build(tmp_path, {"mstack": {"fetch": ["v1", "v2", "v3"]}},
                 pinned=[("mstack", "fetch", "v3")])
    p.main(["--root", str(root)])
    assert shas(root, "mstack", "fetch") == ["v3"]


def test_nothing_to_do_is_success(tmp_path):
    root = build(tmp_path, {"mstack": {"notes": ["only"]}},
                 pinned=[("mstack", "notes", "only")])
    assert p.main(["--root", str(root)]) == 0
    assert shas(root, "mstack", "notes") == ["only"]


# ---------------------------------------------------------------- safety

def test_unreadable_manifest_deletes_nothing(tmp_path):
    """THE safety property. Every path looks unreferenced without the manifest,
    so a naive implementation would wipe the whole cache."""
    root = build(tmp_path, {"mstack": {"notes": ["a", "b"]}}, manifest=False)
    assert p.main(["--root", str(root)]) == 2
    assert shas(root, "mstack", "notes") == ["a", "b"]


def test_malformed_manifest_deletes_nothing(tmp_path):
    root = build(tmp_path, {"mstack": {"notes": ["a", "b"]}}, pinned=[])
    (root / "installed_plugins.json").write_text("{not json", encoding="utf-8")
    assert p.main(["--root", str(root)]) == 2
    assert shas(root, "mstack", "notes") == ["a", "b"]


def test_empty_manifest_is_not_unreadable(tmp_path):
    """No plugins installed is a real state, distinct from 'cannot tell'.
    Everything in the cache is genuinely orphaned and should go."""
    root = build(tmp_path, {"mstack": {"notes": ["a"]}}, pinned=[])
    assert p.main(["--root", str(root)]) == 0
    assert shas(root, "mstack", "notes") == []


def test_pinned_path_outside_cache_is_left_alone(tmp_path):
    """A directory-mode plugin can point outside the cache entirely."""
    root = build(tmp_path, {"mstack": {"notes": ["a"]}})
    (root / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"dev@mstack": [{"installPath": "/somewhere/else"}]}}), encoding="utf-8")
    assert p.main(["--root", str(root)]) == 0
    assert shas(root, "mstack", "notes") == []      # 'a' really is unreferenced


def test_path_normalisation(tmp_path):
    """A pinned path with a trailing slash or '..' must still match."""
    root = build(tmp_path, {"mstack": {"notes": ["keep"]}})
    odd = str(root / "cache" / "mstack" / "notes" / "x" / ".." / "keep")
    (root / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"notes@mstack": [{"installPath": odd}]}}), encoding="utf-8")
    assert p.main(["--root", str(root)]) == 0
    assert shas(root, "mstack", "notes") == ["keep"]


def test_missing_cache_dir_is_not_an_error(tmp_path):
    root = tmp_path / "plugins"
    root.mkdir()
    (root / "installed_plugins.json").write_text('{"plugins":{}}', encoding="utf-8")
    assert p.main(["--root", str(root)]) == 0


def test_stray_file_among_sha_dirs_is_ignored(tmp_path):
    root = build(tmp_path, {"mstack": {"notes": ["keep"]}},
                 pinned=[("mstack", "notes", "keep")])
    (root / "cache" / "mstack" / "notes" / ".DS_Store").write_text("", encoding="utf-8")
    assert p.main(["--root", str(root)]) == 0
    assert (root / "cache" / "mstack" / "notes" / ".DS_Store").exists()


# ---------------------------------------------------------------- dry run

def test_dry_run_deletes_nothing(tmp_path):
    root = build(tmp_path, {"mstack": {"notes": ["old", "new"]}},
                 pinned=[("mstack", "notes", "new")])
    assert p.main(["--root", str(root), "--dry-run"]) == 0
    assert shas(root, "mstack", "notes") == ["new", "old"]


def test_quiet_suppresses_the_no_op_line(tmp_path, capsys):
    root = build(tmp_path, {"mstack": {"notes": ["only"]}},
                 pinned=[("mstack", "notes", "only")])
    p.main(["--root", str(root), "--quiet"])
    assert capsys.readouterr().out == ""


def test_not_quiet_reports_the_no_op(tmp_path, capsys):
    root = build(tmp_path, {"mstack": {"notes": ["only"]}},
                 pinned=[("mstack", "notes", "only")])
    p.main(["--root", str(root)])
    assert "nothing to prune" in capsys.readouterr().out
