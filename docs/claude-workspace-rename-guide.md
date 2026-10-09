---
title: Renaming a Claude Code workspace directory
created: 2026-03-14
updated: 2026-10-10
status: reference
---

# Renaming a Claude Code workspace directory

## 1. Bottom line

Renaming a directory on a Claude Code project's path orphans its sessions, project memory and subagent artifacts, because Claude Code files them under an encoded form of the absolute path. To keep them: rename, let Claude Code create the new encoded directory, copy the old data into it, then rewrite the old path in the session JSONL files and in `~/.claude/history.jsonl` (§3).

**Never derive the new encoded name by hand.** Claude Code replaces every character matching `/[^a-zA-Z0-9_-]/g` with `-`, so dots and spaces become dashes. Always read the name off a directory Claude Code created itself (§3.2).

## 2. Path encoding

| Absolute path | Encoded directory under `~/.claude/projects/` |
|---|---|
| `/Users/mayank/my-project` | `-Users-mayank-my-project` |
| `/Users/mayank/jyotish.ai` | `-Users-mayank-jyotish-ai` (the dot becomes a dash) |
| `/tmp/foo bar` | `-tmp-foo-bar` (the space becomes a dash) |

Found the hard way while renaming `jyotishai-dev` to `jyotish.ai`. We assumed the dot survived and copied the sessions into `-…-jyotish.ai`, but Claude Code reads `-…-jyotish-ai`, so it never found them.

## 3. Procedure

### 3.1 Rename the directory

```bash
mv /old/path/project-name /old/path/new-name
```

### 3.2 Discover the new encoded directory

```bash
cd /old/path/new-name
echo "test" | claude -p "say hi"
ls -lt ~/.claude/projects/ | head -5     # the newest entry is the new encoding
```

### 3.3 Copy project data across

Claude Code created the new directory (with a `memory/` subfolder) in §3.2. Copy the old data into it:

```bash
set -euo pipefail
OLD="$HOME/.claude/projects/-Old-Encoded-Path"
NEW="$HOME/.claude/projects/-New-Encoded-Path"   # from §3.2
[ -d "${OLD:?}" ] && [ -d "${NEW:?}" ]

cp "$OLD"/*.jsonl "$NEW"/                        # session logs
for d in "$OLD"/*/; do                           # subagent artifacts, not memory/
  [ "$(basename "$d")" != "memory" ] && cp -r "$d" "$NEW"/
done
cp "$OLD"/memory/*.md "$NEW"/memory/             # project memory
```

### 3.4 Rewrite the old path in session files

Each session JSONL carries a `cwd` field with the old path, and so do subagent JSONL files:

```bash
find "${NEW:?}" -name '*.jsonl' -exec sed -i '' 's|/old/path/project-name|/old/path/new-name|g' {} +
```

### 3.5 Rewrite the global session index

`~/.claude/history.jsonl` records a `project` path per entry:

```bash
sed -i '' 's|/old/path/project-name|/old/path/new-name|g' ~/.claude/history.jsonl
```

### 3.6 Re-index QMD (only if the project uses it)

```bash
cd /old/path/new-name
BUN_INSTALL= qmd collection remove <collection-name>
BUN_INSTALL= qmd collection add <data-path>/ --name <collection-name>
BUN_INSTALL= qmd update
BUN_INSTALL= qmd embed
```

### 3.7 Verify

From a new terminal in the renamed directory, `claude --resume <session-id>` finds an old session, `claude -c` continues the most recent one, and project memories appear in context.

## 4. What lives where

| What | Location | Action |
|---|---|---|
| Session logs | `~/.claude/projects/<encoded>/*.jsonl` | Copy, then rewrite path |
| Project memory | `~/.claude/projects/<encoded>/memory/` | Copy |
| Subagent artifacts | `~/.claude/projects/<encoded>/<session-id>/` | Copy |
| Session index | `~/.claude/history.jsonl` | Rewrite path |
| In-project config | `<project>/.claude/` | Moves with the rename |
| QMD index | `~/.cache/qmd/index.sqlite` | Re-index |
| IDE lock files | `~/.claude/ide/*.lock` | Refresh on reconnect; skip |

Safe to skip: IDE lock files, old paths inside conversation text (history, not config; only `cwd` matters), and git (repos ignore parent directory names).

The account dirs `~/.claude-sk` and `~/.claude-sovo` link `projects` and `history.jsonl` from `~/.claude`, so a rename done in `~/.claude` covers all three accounts.
