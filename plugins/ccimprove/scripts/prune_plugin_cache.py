#!/usr/bin/env python3
"""Remove plugin-cache directories that no longer back an installed plugin.

`claude plugin update` copies the plugin into a NEW commit-sha directory and
leaves the old one in place:

    ~/.claude/plugins/cache/<marketplace>/<plugin>/<old-sha>/   <- orphaned
    ~/.claude/plugins/cache/<marketplace>/<plugin>/<new-sha>/   <- pinned

The orphan is not merely wasted disk — it is still loaded. Observed 2026-08-24:
`/fetch:x-post` appeared THREE times in the slash menu, because each sha
directory contributed both a command and a skill. Every update adds another.

Safety: the only directories removed are those under a `<marketplace>/<plugin>/`
whose absolute path is absent from `installed_plugins.json`. A plugin that is
installed keeps its pinned directory no matter what. If the manifest cannot be
read, nothing is removed — an unreadable manifest means every path looks
unreferenced, which would delete the entire cache.

Usage:
    prune_plugin_cache.py [--dry-run] [--quiet] [--root DIR]
"""

import argparse
import json
import os
import shutil
import sys

DEFAULT_ROOT = os.path.expanduser("~/.claude/plugins")


def pinned_paths(root: str) -> set[str] | None:
    """Absolute installPaths of every installed plugin, or None if unreadable.

    None is distinct from the empty set. Empty means "nothing installed, prune
    freely"; None means "we cannot tell" — and pruning on a guess would wipe
    the cache.
    """
    manifest = os.path.join(root, "installed_plugins.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None

    out = set()
    for entries in (data.get("plugins") or {}).values():
        for e in entries or []:
            p = e.get("installPath")
            if p:
                out.add(os.path.normpath(p))
    return out


def find_orphans(root: str, pinned: set[str]) -> list[str]:
    """Cache dirs at <cache>/<marketplace>/<plugin>/<sha> not in `pinned`."""
    cache = os.path.join(root, "cache")
    orphans = []
    if not os.path.isdir(cache):
        return orphans

    for marketplace in sorted(os.listdir(cache)):
        mdir = os.path.join(cache, marketplace)
        if not os.path.isdir(mdir):
            continue
        for plugin in sorted(os.listdir(mdir)):
            pdir = os.path.join(mdir, plugin)
            if not os.path.isdir(pdir):
                continue
            for sha in sorted(os.listdir(pdir)):
                sdir = os.path.normpath(os.path.join(pdir, sha))
                if os.path.isdir(sdir) and sdir not in pinned:
                    orphans.append(sdir)
    return orphans


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list, do not delete")
    ap.add_argument("--quiet", action="store_true", help="print nothing when there is nothing to do")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="plugins dir (default ~/.claude/plugins)")
    args = ap.parse_args(argv)

    pinned = pinned_paths(args.root)
    if pinned is None:
        print("prune-plugin-cache: cannot read installed_plugins.json — nothing removed.",
              file=sys.stderr)
        return 2

    orphans = find_orphans(args.root, pinned)
    if not orphans:
        if not args.quiet:
            print("prune-plugin-cache: nothing to prune.")
        return 0

    freed = 0
    for d in orphans:
        for dirpath, _, files in os.walk(d):
            for f in files:
                try:
                    freed += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        if not args.dry_run:
            shutil.rmtree(d, ignore_errors=True)

    verb = "would remove" if args.dry_run else "removed"
    rel = [d[len(os.path.join(args.root, "cache")) + 1:] for d in orphans]
    print(f"prune-plugin-cache: {verb} {len(orphans)} orphaned cache dir(s), "
          f"{freed // 1024} KB", file=sys.stderr)
    for r in rel[:10]:
        print(f"  {r}", file=sys.stderr)
    if len(rel) > 10:
        print(f"  … and {len(rel) - 10} more", file=sys.stderr)

    # Never remove a pinned path — assert it, do not assume it.
    still = [p for p in pinned if os.path.isdir(os.path.dirname(p)) and not os.path.isdir(p)]
    if still and not args.dry_run:
        print(f"prune-plugin-cache: WARNING — {len(still)} pinned path(s) missing "
              f"after prune. This should be impossible; report it.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
