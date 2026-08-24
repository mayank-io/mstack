---
name: scribd-document
description: "Download all pages from a Scribd document as images. Use when the user shares a scribd.com URL and wants to save, download, archive, or extract the pages/images of a Scribd document."
---

# Download Scribd Document

Download all page images from a Scribd document via its embed view.


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

- `$ARGUMENTS` should contain: `<url> [output_dir]`

## Instructions

Run the Scribd extractor script with a **10-minute timeout** (large documents can take several minutes to scroll and download):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/scribd_extractor.py $ARGUMENTS
```

**IMPORTANT:** When running this via the Bash tool, set `timeout: 600000` (10 minutes).

If httpx or playwright are not installed, install them first:
```bash
pip3 install httpx playwright
python3 -m playwright install chromium
```

The script handles everything:
1. Converts the Scribd URL to its embed form (`/embeds/{id}/content`)
2. Launches a headless browser and navigates to the embed
3. Reads the toolbar to detect total page count
4. Scrolls through the document to trigger lazy loading of all pages
5. Runs targeted scrolling passes for any pages that didn't load
6. Downloads all page images as zero-padded `.jpg` files

## Verification

After the script finishes:
1. Count the `.jpg` files in the output directory
2. Compare against the total page count reported by the script
3. Report any gaps to the user

## Notes

- The script is idempotent — re-running skips already-downloaded pages
- Filenames are zero-padded (`page_0001.jpg`) for correct sort order
- Output directory defaults to `./scribd_output` if not specified
- The script prints status to stderr and the output directory path to stdout

## Example Usage

```bash
# Download with default output directory
/fetch:scribd-document https://www.scribd.com/document/123456789/Sample-Document-Title

# Download to a specific directory
/fetch:scribd-document https://www.scribd.com/document/123456789/Sample-Document-Title ./my-book
```
