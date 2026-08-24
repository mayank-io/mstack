---
name: save-local-file
description: "File a local file — PDF, image, or document already on disk — into the current Obsidian vault as a clipping with the file attached. Use when the user gives a file path and wants it saved to their vault, or when notes:clip has fetched a file and needs it filed. For URLs, use notes:clip instead."
---

# Save Local File

Copy a file already on disk into the vault's attachments and write a clipping note that embeds it.

## Input

`$ARGUMENTS` — a path to a local file, optionally followed by extra instructions (a title, a project to tag, a folder). Honour those after filing.

## Step 1 — Locate the vault

**Walk up from the current working directory looking for a `.obsidian/` directory.** The first ancestor containing one is the vault root.

```bash
d="$PWD"
while [ "$d" != "/" ]; do
  [ -d "$d/.obsidian" ] && { echo "$d"; break; }
  d="$(dirname "$d")"
done
```

If none is found, **stop and say so** — never write outside a vault. There is no config file.

## Step 2 — Read the vault's conventions

If the vault root has a `CLAUDE.md`, read it and follow what it says about clippings folder, attachments folder, frontmatter, tags, and daily-note updates. **The vault's own conventions win.** The defaults below apply only when it is silent.

Defaults: clippings in `Clippings/`, attachments in `Clippings/attachments/`.

## Step 3 — Validate and copy

Confirm the file exists and is readable. Copy it into the attachments folder, **keeping the original filename** so the source stays identifiable. If a file of that name already exists, append a timestamp (`report-20260824-143022.pdf`) rather than overwriting.

## Step 4 — Read the file before writing about it

**Read the file's contents.** For a PDF, check for a text layer first (`pdftotext`) and fall back to the Read tool's `pages:` parameter; for an image, look at it. Never write a summary of a file you have not opened — a filed-but-unexamined attachment is worse than no note, because it looks complete.

## Step 5 — Write the clipping note

Title from the filename: strip the extension, replace underscores and dashes with spaces, title-case it. `quarterly_report_2024.pdf` → `Quarterly Report 2024`.

```markdown
---
tags:
  - clippings
  - inbox
source: <origin if known, else "local file">
date_captured: YYYY-MM-DD
---

# <Title>

![[<original-filename.ext>]]

---

## Summary

<what the file actually contains, from having read it>
```

Embed with Obsidian's wikilink syntax `![[filename]]` — PDFs and images then render inline.

## Step 6 — Update today's daily note

Add a link to the clipping. If today's daily note does not exist, create it from the vault's daily-note template if one exists.

## Step 7 — Report

Print the note path as the **final line**, machine-parseable so callers can chain:

```
OUTPUT_FILE:/absolute/path/to/vault/Clippings/Title.md
```

## Errors

- **No vault found** — stop, explain, write nothing.
- **File missing or unreadable** — stop and say which.
- **Name collision** — never overwrite; suffix with a timestamp.
- **Unreadable PDF (no text layer, Read fails)** — still file it, but say plainly in the note that the contents could not be extracted rather than inventing a summary.
