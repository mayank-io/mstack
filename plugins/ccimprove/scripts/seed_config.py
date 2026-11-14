#!/usr/bin/env python3
"""Create the per-user mstack config directory from each plugin's shipped defaults.

Every mstack plugin keeps its user-editable config under `~/.mstack/<plugin>/`
and ships the starting files in its own `config-defaults/` directory:

    <plugin install dir>/config-defaults/feedback-tags.json
        -> ~/.mstack/dev/feedback-tags.json

A file that already exists is never overwritten: the user's copy is the config,
the shipped one is only where it starts.

Plugins are found through Claude Code's `installed_plugins.json`, or, with
`--plugins-dir`, as the subdirectories of a checkout's `plugins/` directory.

Usage:
    seed_config.py [--dry-run] [--home DIR] [--marketplace NAME]
                   [--plugins-root DIR | --plugins-dir DIR]

stdout: one line per file, `created <path>` or `kept <path>`.
Exit 0 on success, 2 when the installed-plugins manifest cannot be read.
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

DEFAULTS_DIRNAME = "config-defaults"


def default_plugins_root() -> Path:
    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return Path(claude_dir) / "plugins"


def find_installed_plugins(plugins_root: Path, marketplace: str) -> dict[str, Path] | None:
    """Map plugin name to install directory for one marketplace, or None if unreadable.

    None is distinct from an empty map: empty means nothing from this
    marketplace is installed, None means the manifest could not be read.
    """
    try:
        data = json.loads((plugins_root / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    suffix = f"@{marketplace}"
    found: dict[str, Path] = {}
    for key, entries in (data.get("plugins") or {}).items():
        if not key.endswith(suffix):
            continue
        for entry in entries or []:
            install_path = entry.get("installPath")
            if install_path:
                found.setdefault(key[: -len(suffix)], Path(install_path))
    return found


def find_checkout_plugins(plugins_dir: Path) -> dict[str, Path]:
    """Map plugin name to directory for every subdirectory of a checkout's plugins/."""
    return {d.name: d for d in sorted(plugins_dir.iterdir()) if d.is_dir()}


def seed_plugin(name: str, plugin_dir: Path, home: Path, dry_run: bool) -> list[tuple[str, Path]]:
    """Copy one plugin's defaults into home/<name>/, skipping files that exist."""
    defaults = plugin_dir / DEFAULTS_DIRNAME
    results: list[tuple[str, Path]] = []
    if not defaults.is_dir():
        return results
    for source in sorted(p for p in defaults.rglob("*") if p.is_file()):
        target = home / name / source.relative_to(defaults)
        if target.exists():
            results.append(("kept", target))
            continue
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        results.append(("created", target))
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report what would be created, write nothing")
    ap.add_argument("--home", type=Path, default=Path(os.path.expanduser("~/.mstack")),
                    help="config directory to seed (default ~/.mstack)")
    ap.add_argument("--marketplace", default="mstack", help="marketplace whose plugins are seeded")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--plugins-root", type=Path, default=None,
                        help="Claude Code plugins dir holding installed_plugins.json")
    source.add_argument("--plugins-dir", type=Path, default=None,
                        help="a checkout's plugins/ directory, used instead of the installed set")
    args = ap.parse_args(argv)

    if args.plugins_dir is not None:
        if not args.plugins_dir.is_dir():
            print(f"seed-config: {args.plugins_dir} is not a directory.", file=sys.stderr)
            return 2
        plugins = find_checkout_plugins(args.plugins_dir)
    else:
        plugins_root = args.plugins_root or default_plugins_root()
        plugins = find_installed_plugins(plugins_root, args.marketplace)
        if plugins is None:
            print(f"seed-config: cannot read {plugins_root / 'installed_plugins.json'}; nothing written.",
                  file=sys.stderr)
            return 2

    for name in sorted(plugins):
        for action, target in seed_plugin(name, plugins[name], args.home, args.dry_run):
            print(f"{action} {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
