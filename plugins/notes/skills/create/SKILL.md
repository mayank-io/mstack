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

### Entity linking — scan, resolve, then create

**Run these in order. Each step exists because skipping it has produced a wrong note.**

**1. Scan for company and organisation NAMES, not for ticker-shaped strings.** Every company named in the body is a candidate for a page and a link. A note about "SpaceX" that links `[[$NVDA]]` because *that* one was already written as a symbol, while leaving the actual subject unlinked, is the failure this step prevents. Read the content for entities; do not pattern-match for `$`.

**2. Resolve the official symbol before writing any link. A ticker is a fact to look up, never a string to construct.**

```bash
# Authoritative for US listings. A descriptive User-Agent is REQUIRED — SEC returns 403 without one.
curl -sL --max-time 30 -A '<you>@<domain> research' https://www.sec.gov/files/company_tickers.json \
  | python3 -c "import sys,json;[print(str(v['cik_str']).zfill(10),v['ticker'],v['title']) for v in json.load(sys.stdin).values() if '<COMPANY>' in v['title'].upper()]"

# Cross-check the symbol actually trades.
curl -s -A 'Mozilla/5.0' "https://query1.finance.yahoo.com/v8/finance/chart/<SYM>?range=1d&interval=1d"
#   -> meta.instrumentType == "EQUITY", meta.longName, meta.fullExchangeName
```

**The symbol is frequently not an abbreviation of the name.** Space Exploration Technologies Corp. trades as **`SPCX`**, not `SPACEX`. Guessing produced a duplicate page, a wrong "private company" framing, and a note asserting that figures were unverifiable when a 10-Q had already been filed.

**3. Search existing pages by `name:` and `aliases:`, NEVER by filename.**

```bash
grep -ril "<company name>" Notes/Tickers/     # matches frontmatter name/aliases
# NOT: ls Notes/Tickers/ | grep '^\$SPACEX\.md'   # returns nothing, looks like "no page exists"
```

A filename search answers "is there a page named after my guess", which is a different question from "does this company have a page". The page for SpaceX is `$SPCX.md`, and its frontmatter carries `name: SpaceX` plus `aliases: ["SpaceX", "Space Exploration Technologies"]` — precisely so a name search finds it.

**4. Create a page only after both 2 and 3 come back empty**, from the vault's ticker template. Carry the resolved symbol, and set `aliases:` to every name the company is called in the wild, so the next scan finds it by step 3.

**5. Never invent a symbol as a placeholder.** If a public company's symbol cannot be resolved, say so and leave the mention unlinked rather than minting one — an invented symbol becomes a duplicate page that later has to be found and merged. If no symbol exists because the company is private, follow the vault's private-company convention; if the vault documents none, ask rather than inventing.

**6. Link every resolved entity**, including in frontmatter where the vault uses a `tickers:` field.

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
