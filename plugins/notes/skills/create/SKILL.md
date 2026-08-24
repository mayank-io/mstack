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

## Step 3 — Build the note

**Filename** — from the title, with `/ \ : * ? " < > |` replaced by `-`, and whitespace trimmed. If the file already exists, append ` 2`, ` 3`, … rather than overwriting.

**Frontmatter** — always include `title` and `created` (today, `YYYY-MM-DD`), then merge in anything from `--frontmatter`. Preserve the caller's values on conflict.

**Folder** — `--folder` if given, else the vault root. Create the folder if it does not exist.

## Step 4 — Write and report

Write the file, then print the path as the **final line** in machine-parseable form so callers can chain on it:

```
OUTPUT_FILE:/absolute/path/to/vault/Folder/Note Title.md
```

Print a human-readable confirmation before that line if useful, but the `OUTPUT_FILE:` line must be last.

## Errors

- **No vault found** — stop, explain, do not write.
- **Missing `--title` or `--content`** — stop and say which.
- **Folder missing** — create it.
- **File exists** — never overwrite; suffix the name.
