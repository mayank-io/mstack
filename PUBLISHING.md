# Publishing changes

This marketplace is distributed via GitHub. Claude Code clones it and caches
plugin files keyed by commit SHA. Two things must happen for a change to reach
a user's Claude Code session:

1. The commit must be pushed to `origin/main`.
2. `.claude-plugin/marketplace.json` `metadata.version` must have been bumped
   in that same commit. Without a version change, `autoUpdate: true` on the
   consumer side does **not** fetch new commits.

## The one-command flow

```bash
# After editing plugin files (and `git add`-ing them):
scripts/publish.sh                       # patch bump
scripts/publish.sh minor                 # new plugin / breaking-ish change
scripts/publish.sh major                 # big restructure
scripts/publish.sh patch "custom msg"    # override commit message
```

`publish.sh` bumps `marketplace.json`, commits your staged changes alongside
the bump, and pushes to origin. It then prints the two manual steps you still
need to run in Claude Code itself.

## The two manual steps (Claude Code side)

After `publish.sh` finishes, switch to Claude Code and run:

```
/plugin update mstack
/reload-plugins
```

These cannot be automated from a shell script — they're Claude Code slash
commands, not OS-level operations.

## Why this is necessary

- **Commit SHA vs. version.** Claude Code caches plugins under
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<short-sha>/`. A new commit
  produces a new cache dir. But `autoUpdate: true` decides *whether to pull a
  new commit at all* by watching `marketplace.json` `metadata.version`. No
  version change → no fetch → stale cache.
- **Local working tree is invisible.** The `mstack` entry in
  `~/.claude/plugins/known_marketplaces.json` points at
  `github:mayank-io/mstack` — not your working directory. Claude Code reads
  files from a *clone* of the remote, not from this repo. Unpushed commits
  don't exist as far as Claude Code is concerned.

## Safety net: pre-commit hook

`scripts/pre-commit-hook.sh` (installed via `scripts/install-hooks.sh`)
blocks commits that modify `plugins/**` without bumping the marketplace
version. Use `scripts/publish.sh` and you'll never hit it; it's there for
manual commits so you don't ship a dead update.

It also enforces:
- Every directory under `plugins/` is registered in `marketplace.json`.
- No `version` field appears in any per-plugin `plugin.json` (caching is
  keyed by commit SHA — a per-plugin version would be misleading).
- No hardcoded personal paths (e.g., `iCloud~md~obsidian`,
  `/Users/<owner>/...`) sneak into distributed plugins. Extend the pattern
  list in the hook as needed.

## One-time setup (fresh clone)

```bash
scripts/install-hooks.sh
```
