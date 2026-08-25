---
name: create
description: "Write a note into the current Obsidian vault. Use when content is already in hand and needs saving as a note — including when another skill (such as notes:clip) has fetched content and needs it filed. Handles frontmatter, folder placement, filename sanitising, and collision avoidance."
---

# Create Note

Write a Markdown note into the Obsidian vault Claude Code is running in. This skill owns vault conventions — callers supply content, not layout.

## Input

`$ARGUMENTS`:

- `--title` **(required)** — note title, also the filename
- `--content` **(required)** — Markdown body
- `--folder` *(optional)* — subfolder within the vault; defaults to the vault root
- `--frontmatter` *(optional)* — JSON object of extra frontmatter fields

## Step 1 — Locate the vault

**Walk up from the current working directory looking for a `.obsidian/` directory.** The first ancestor containing one is the vault root.

```bash
d="$PWD"
while [ "$d" != "/" ]; do
  [ -d "$d/.obsidian" ] && { echo "$d"; break; }
  d="$(dirname "$d")"
done
```

If no `.obsidian/` is found, **stop and say so** — do not guess a path and do not write outside a vault. Ask the user to run from inside their vault or to name the target vault explicitly.

There is no config file. The vault is wherever the session is.

## Step 2 — Read the vault's conventions

If the vault root has a `CLAUDE.md`, read it first and follow any conventions it states — folder layout, frontmatter fields, tagging, wikilink rules, daily-note behaviour. **A vault's own documented conventions override the defaults below.**

Reading it is not optional and neither is acting on it. Delegation here has silently failed before: a clipping was written correctly and its daily-note link was never added, because "follow any conventions it states" was treated as advisory. Steps 3a and 3b make the two that are almost always stated explicit.

## Step 3 — Build the note

**Filename** — from the title, with `/ \ : * ? " < > |` replaced by `-`, and whitespace trimmed. If the file already exists, append ` 2`, ` 3`, … rather than overwriting.

**Frontmatter** — always include `title` and `created` (today, `YYYY-MM-DD`), then merge in anything from `--frontmatter`. Preserve the caller's values on conflict.

**Folder** — `--folder` if given, else the vault root. Create the folder if it does not exist.

**Links in the body** — if the vault documents an entity-linking rule (stock tickers as `[[$AAPL]]`, people as `[[@Name]]`, dates as `[[YYYY-MM-DD]]`), apply it to the content you were handed. The caller supplies text; converting bare mentions into the vault's link syntax is this skill's job, because this skill is the one that read the conventions.

## Step 4 — Write the file

## Step 5 — Link it into today's daily note

Most vaults want every new note discoverable from the day it was made. Unless the vault's `CLAUDE.md` says otherwise:

1. Find today's daily note — commonly `Daily Notes/YYYY-MM-DD.md`. Match the vault's actual folder and date format; do not assume.
2. Append a link to the new note: `- [[Note Title]]`.
3. If the daily note does not exist, create it from the vault's daily-note template if there is one.

## Step 6 — Verify, then report

**Check before claiming.** Every `[[wikilink]]` written should resolve to a real file, or be a deliberate stub the vault's conventions call for. Escaped pipes in tables (`[[Target\|Alias]]`) produce false "broken" hits — strip the trailing backslash before comparing. Every embedded image path should exist on disk.

**Say what happened to the daily note either way** — "linked into `Daily Notes/2026-08-24.md`", or that you did not and why. Never leave the caller to assume it happened.

Then print the path as the **final line** in machine-parseable form so callers can chain on it:

```
OUTPUT_FILE:/absolute/path/to/vault/Folder/Note Title.md
```

Print a human-readable confirmation before that line if useful, but the `OUTPUT_FILE:` line must be last.

## Errors

- **No vault found** — stop, explain, do not write.
- **Missing `--title` or `--content`** — stop and say which.
- **Folder missing** — create it.
- **File exists** — never overwrite; suffix the name.
