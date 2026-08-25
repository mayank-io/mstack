---
name: linkedin-post
description: "Extract a LinkedIn post — author, headline, full text, engagement metrics, images, and any URLs it shares — using the gstack browser. Use when the user says \"read this linkedin post\", \"get this linkedin post\", \"extract this linkedin post\", or shares a linkedin.com/posts or linkedin.com/feed/update URL. Returns content and images to a directory; it does not write notes."
---

# Fetch LinkedIn Post

Pull a LinkedIn post's content and media into a directory. **This skill knows nothing about vaults** — it retrieves, and stops. `notes:clip` turns the result into a note.

## Browser — always gstack, never headless

LinkedIn shows almost nothing to a logged-out session, and what it does show looks like a valid short post rather than an error. Browser work goes through the **gstack browser**, which holds the user's session.

```bash
B="$HOME/.claude/skills/gstack/browse/dist/browse"
"$B" connect        # run from the target directory — another cwd spawns a second
                    # daemon and kills the headed session
"$B" goto "<url>"
"$B" js '<expression>'
```

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a fresh `chromium.launch()`. If gstack is unavailable, stop and say so — a logged-out capture is worse than none, because it looks fine.

**Do not `disconnect` a daemon you did not start.** It would close the user's browser and drop their tabs, cookies and logins. The `_browse.py` adapter handles this; if driving `$B` directly, leave a pre-existing daemon running.

## Input

`$ARGUMENTS`:

- **First argument** — LinkedIn post URL (required): `linkedin.com/posts/…` or `linkedin.com/feed/update/…`
- **Second argument** — output directory (optional). Omitted, a temp directory is used. Created if missing. **Never write outside it.**

## Step 1 — Navigate and expand

```bash
"$B" goto "<url>"
```

**LinkedIn truncates long posts behind "…see more".** Expand before reading, or you will capture a fragment that reads as a complete short post:

```bash
"$B" click 'text=see more'   # ignore failure — not every post is truncated
```

If the page shows a login form, retry once; the daemon carries existing cookies. If it persists, **stop and ask the user to log in inside the gstack browser**, then retry. Do not fall back to a logged-out fetch.

## Step 2 — Extract

Use `"$B" snapshot` for the accessibility tree, and `$B js` for anything structural. Collect:

| Field | Notes |
|---|---|
| `author_name` | display name |
| `author_headline` | title / company line beneath the name |
| `date` | LinkedIn shows a relative age ("2w"); resolve to an absolute date where possible and say so when you cannot |
| `text` | **the expanded text** — verify "…see more" is gone |
| `images` | post images, at the largest available resolution |
| `metrics` | likes, comments, reposts |
| `links` | every URL in the post body **and** in any link-preview card |

**Return `links` — do not follow them.** Recursing into shared content is `notes:clip`'s job; a fetch skill that pulls in a YouTube video has stopped being a fetch skill. Capture the preview card's title, description and image too: it is often the only trace left when the target link rots.

⚠️ **Page JavaScript must be synchronous.** `$B js` returns before a promise resolves, so an in-page `await` silently loses its result. Drive any wait or scroll loop from Python with `page.wait_for_timeout(ms)` between synchronous `evaluate` calls — see `fetch:blog-post` Step 3 for the shape.

## Step 3 — Download images

```bash
curl -L -o "<output_dir>/linkedin-<author>-<n>.jpg" "<image_url>"
```

LinkedIn's CDN sometimes rejects a bare `curl`. If it does, screenshot the image element through gstack rather than skipping it — **and say in your report that the image was screenshotted rather than downloaded**, since a re-encoded screenshot is not the original asset.

## Step 4 — Report

Write the extracted fields as JSON alongside the images, then print the directory as the **final stdout line**:

```
OUTPUT_DIR:/absolute/path/to/output
```

The marker must be last. Callers chain on it and must never reconstruct the path.

## Failure modes worth naming

- **A short post that should be long** — "…see more" was never expanded. Re-check before reporting.
- **Author headline missing** — common on reshares; report it absent rather than substituting the reshared author's.
- **Zero images on a post that clearly has them** — usually lazy-loading. Scroll the post into view, wait, re-collect.
- **A login wall captured as content** — the failure this skill exists to prevent. If the text mentions signing in or joining LinkedIn, treat the capture as failed.
