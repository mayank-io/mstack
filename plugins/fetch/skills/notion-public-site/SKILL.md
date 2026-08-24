---
name: notion-public-site
description: "Download all pages from a public Notion site as Markdown files with cross-references and embedded images. Use when the user shares a public Notion site URL and wants to archive, save, mirror, or extract the contents as local markdown."
---

# Download Notion Site

Download all content from a public Notion site as Markdown files.


## Browser — always gstack, never headless

Browser work goes through the **gstack browser**, which holds the user's logged-in
sessions. A fresh Playwright instance is logged out: it silently returns login walls
or truncated content that looks like a successful capture.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect        # run from the target directory — another cwd spawns a second
                    # daemon and kills the headed session
"$B" goto "<url>"
"$B" js '<expression>'
"$B" disconnect
```

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a
fresh `chromium.launch()`. If gstack is unavailable, stop and say so rather than
falling back — a logged-out capture is worse than no capture, because it looks fine.

## Arguments

- `$ARGUMENTS` should contain: `<url> <output_dir> [--test]`

## Instructions

Run the Notion downloader script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/notion_public_site_downloader.py $ARGUMENTS
```

If httpx or playwright are not installed, install them first:
```bash
pip3 install httpx playwright
python3 -m playwright install chromium
```

## Features

- Automatically crawls all internal pages starting from the base URL
- Downloads embedded images to `attachments/` folder
- Converts Notion content to clean Markdown
- Rewrites internal links as Obsidian wikilinks
- Creates an index file with table of contents
- Use `--test` flag to download only the first page for testing

## Verification Steps

After download completes, verify the content:

1. **Count verification**: Compare number of downloaded pages against expected (check _page_map.json)
2. **Content spot-check**: Use Playwright to open 2-3 random pages and compare visible content with downloaded markdown
3. **Link verification**: Confirm wikilinks in markdown files point to existing files
4. **Image verification**: Confirm images in attachments/ folder are valid and referenced

## Example Usage

```bash
# Test mode - download first page only
/fetch:notion-public-site https://guide.sillymoney.com/ ./output --test

# Full download
/fetch:notion-public-site https://guide.sillymoney.com/ ./output
```
