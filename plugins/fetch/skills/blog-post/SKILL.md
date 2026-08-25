---
name: blog-post
description: This skill should be used when the user shares a blog/article URL (Medium, Substack, personal blog, news/long-form post) and asks to "download this blog post", "save this article", "archive this post with images", "clip this medium article", or otherwise wants a self-contained local copy. Extracts clean markdown via Defuddle, recovers lazy-loaded images via the gstack browser (which Defuddle drops), and — when the article contains Vedic astrology charts — invokes the fetch:vedic-chart skill to digitize them. Saves a folder with frontmatter + an images/ subfolder.
---

# Download Blog Post

Save a web article as a self-contained local folder: clean markdown with YAML
frontmatter, every inline image downloaded and re-referenced, and any Vedic
astrology charts digitized to JSON + ASCII.

This combines two tools: **Defuddle** (clean text, fast, low-token) for the article
body, and the **gstack browser** for images — because Defuddle strips lazy-loaded `<img>`
tags, leaving empty `![]()` placeholders. A real browser recovers the image URLs
in document order.


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
```

**The daemon must be in `headed` mode.** `browse status` reports either `headed`
(attached to the user's real Chrome, carrying their logins) or `launched` (gstack's
own Chromium on a fresh profile, logged into nothing). A `launched` daemon returns
a login wall for every gated page, and a login wall reads as a *short page* rather
than an error — nothing downstream will flag it. Verify the mode, and force a
restart when it is wrong:

```bash
"$B" status                     # must report `mode: headed`
"$B" connect --force-restart    # only when it does not — a launched daemon holds a
                                # fresh profile with no logins, so nothing is lost
```

The `_browse.py` adapter runs this check inside `connect()` and refuses to continue
if it cannot reach `headed`. Do the same by hand when driving `$B` directly.

**Do NOT `disconnect` when done.** `browse disconnect` tears down the daemon and
the logged-in sessions with it. Leave it running — the daemon is a shared user
resource, `connect` is safe to call again, and only whoever started it should
close it. The
adapter's `close()` is deliberately a no-op, so leaving the `async with
browse_page()` block tears down nothing.

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a
fresh `chromium.launch()`. If gstack is unavailable, stop and say so rather than
falling back — a logged-out capture is worse than no capture, because it looks fine.

**Page JavaScript must be synchronous, and values are passed as arguments.** `$B js`
returns before a promise resolves, so `evaluate()` refuses any expression that is an
`async` function or contains `await` — the result would be silently lost. Drive the
waiting and looping from Python with `await page.wait_for_timeout(ms)` between
synchronous `evaluate()` calls. Pass values with `await page.evaluate(js, arg)`
rather than string-interpolating them into the JavaScript: an interpolated value
containing a quote breaks the expression.

## Input

The user provided: `$ARGUMENTS`

- **First argument**: the article URL (required).
- **Second argument**: output directory (optional, defaults to the current working
  directory). The article is saved as `<output_dir>/<slug>/`.

Derive `<slug>` as a short kebab-case form of the title.

## Process

### Step 1: Extract metadata and clean body (Defuddle)

Fetch once as JSON — it carries the metadata and the markdown body together, so a
single page load covers both:

```bash
defuddle parse "<url>" --json -o /tmp/<slug>.json
```

Read `title`, `author`, `published`, and the markdown body from that JSON. If a
field is missing, fall back to a targeted property fetch for just that field
(`defuddle parse "<url>" -p author`). If `defuddle` is missing:
`npm install -g defuddle-cli`.

### Step 2: Trim site chrome

Defuddle is clean on most sites but leaves navigation/footer cruft on some (Medium
especially: SVG logo nav at the top, clap/tag/author footer at the bottom). Bound
the body to the real article using structural landmarks, not the extractor's edges:

- **Start**: the first real content heading/paragraph after the byline line (e.g.
  the line with `N min read` / the date).
- **End**: the last prose line before the footer block (tag links like
  `[Astrology](…/tag/…)`, "Written by", clap/response widgets).

Drop any empty `![]()` image placeholders — real images are wired in at Step 4.

### Step 3: Recover image URLs in order

Scroll to trigger lazy-loading, then collect each article image's high-res URL **and an anchor** (nearest preceding heading) so it can be placed correctly later. Select **all** content `<img>` elements — figure-wrapped (Medium) and bare (Substack, WordPress, personal blogs) alike — filtering out icons and avatars by size, and de-duplicate by URL.

**The scroll loop runs in Python, not in the page.** `$B js` returns before a promise resolves, so `await sleep()` inside page JavaScript silently loses its result — this step returned "no images found" that way. Every `evaluate` below is synchronous; the waiting is `wait_for_timeout`:

```python
import asyncio, json, sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/scripts")
from _browse import browse_page

async def main():
    async with browse_page() as page:
        await page.goto("THE_URL_HERE")
        await page.wait_for_selector("article, body")

        height = await page.evaluate("() => document.body.scrollHeight")
        for y in range(0, height + 1, 600):          # trigger lazy-loading
            await page.evaluate("(y) => window.scrollTo(0, y)", y)
            await page.wait_for_timeout(120)
        await page.evaluate("() => window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)             # let the top settle

        print(json.dumps(await page.evaluate(COLLECT_JS)))

asyncio.run(main())
```

`COLLECT_JS` — synchronous, because everything async now happens above:

```javascript
() => {
  const article = document.querySelector('article') || document.body;
  const imgs = Array.from(article.querySelectorAll('img'))
    .filter(img => (img.naturalWidth || img.width || 0) >= 200);  // skip icons/avatars
  const seen = new Set();
  return imgs.map(img => {
    let url = img.currentSrc || img.src || '';
    const ss = img.getAttribute('srcset');
    if (ss) { const p = ss.split(',').map(s => s.trim().split(' ')[0]).filter(Boolean); if (p.length) url = p[p.length - 1]; }
    let heading = '', node = img.closest('figure') || img;
    while (node && !heading) {
      let sib = node.previousElementSibling;
      while (sib) { if (/^H[1-6]$/.test(sib.tagName)) { heading = sib.innerText.trim(); break; } sib = sib.previousElementSibling; }
      node = node.parentElement;
    }
    return { url, heading };
  }).filter(o => o.url && !seen.has(o.url) && seen.add(o.url));
}
```

**Count check**: trust this browser-collected list as the complete, ordered set. Defuddle's
`![]()` placeholder count is often lower — it drops figures entirely. If the list is
empty but the body clearly references images, scroll further and re-run (some sites
defer loading until deep in the viewport).

### Step 4: Download images and wire them in

Create `<output_dir>/<slug>/images/`. Download each image with a descriptive,
zero-padded name (`NN-<short-label>.<ext>`). For Medium's `miro.medium.com` URLs,
request high resolution and the native format by rewriting to
`https://miro.medium.com/v2/resize:fit:2400/<fileId>` (drop any `format:webp`
segment to keep the original png/jpeg).

```bash
curl -sSL -A "Mozilla/5.0" -o "<slug>/images/NN-<label>.<ext>" "<image_url>"
```

Insert a Markdown reference for each image at its anchor (right after the matching
heading; place multiple charts under the same heading in order). Verify every
`![…](images/…)` reference resolves to a downloaded file.

### Step 5: Detect and digitize charts

Inspect the downloaded images. When any are **Vedic astrology charts** (North-Indian
diamond / South-Indian square kundli, often a JHora / Parashara's Light printout
with a planet longitude table), invoke the **`fetch:vedic-chart`** skill on them
to produce `<image>.json` + `<image>.txt` sidecars in the same `images/` folder.
Note the sidecars near each chart reference (e.g. a line linking the `.json`).

Skip this step for articles with no chart imagery.

### Step 6: Write the markdown file

Save `<output_dir>/<slug>/<slug>.md` with YAML frontmatter:

```yaml
---
title: "<title>"
author: "<author>"
published: <ISO8601 date>
url: <original url>
type: blog
---
```

Followed by the title as an `# H1`, then the trimmed body with images wired in.

## Output

Report: the saved markdown path, image count + folder, and how many charts (if any)
were digitized.

```
<output_dir>/<slug>/
├── <slug>.md          # frontmatter + body + image refs
└── images/            # downloaded images (+ chart .json/.txt sidecars)
```

## Tips

- Defuddle over WebFetch: cleaner markdown, far fewer tokens.
- Medium blocks plain HTTP for images and lazy-loads them — a real browser is required
  to get real URLs; Defuddle alone yields empty `![]()`.
- Anchor images by their nearest preceding heading; placing by raw order breaks when
  Defuddle drops a figure.
- Keep images co-located with the markdown (relative `images/...` refs) so the
  folder is portable.
- The charts themselves are lost as images if a site lazy-loads them and the gstack
  browser cannot reach the real src — re-run Step 3 after a fuller scroll if a
  figure is empty.
