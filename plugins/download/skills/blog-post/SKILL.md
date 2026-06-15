---
name: blog-post
description: This skill should be used when the user shares a blog/article URL (Medium, Substack, personal blog, news/long-form post) and asks to "download this blog post", "save this article", "archive this post with images", "clip this medium article", or otherwise wants a self-contained local copy. Extracts clean markdown via Defuddle, recovers lazy-loaded images via Playwright (which Defuddle drops), and — when the article contains Vedic astrology charts — invokes the download:vedic-chart skill to digitize them. Saves a folder with frontmatter + an images/ subfolder.
---

# Download Blog Post

Save a web article as a self-contained local folder: clean markdown with YAML
frontmatter, every inline image downloaded and re-referenced, and any Vedic
astrology charts digitized to JSON + ASCII.

This combines two tools: **Defuddle** (clean text, fast, low-token) for the article
body, and **Playwright** for images — because Defuddle strips lazy-loaded `<img>`
tags, leaving empty `![]()` placeholders. Playwright recovers the real image URLs
in document order.

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

### Step 3: Recover image URLs in order (Playwright)

Navigate with Playwright, scroll to trigger lazy-loading, then collect each article
image's high-res URL **and an anchor** (nearest preceding heading) so it can be
placed correctly later. Select **all** content `<img>` elements — figure-wrapped
(Medium) and bare (Substack, WordPress, personal blogs) alike — filtering out icons
and avatars by size, and de-duplicate by URL:

```javascript
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const h = document.body.scrollHeight;
  for (let y = 0; y <= h; y += 600) { window.scrollTo(0, y); await sleep(120); }
  window.scrollTo(0, 0); await sleep(500);
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

**Count check**: trust this Playwright list as the complete, ordered set. Defuddle's
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
with a planet longitude table), invoke the **`download:vedic-chart`** skill on them
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
- Medium blocks plain HTTP for images and lazy-loads them — Playwright is required
  to get real URLs; Defuddle alone yields empty `![]()`.
- Anchor images by their nearest preceding heading; placing by raw order breaks when
  Defuddle drops a figure.
- Keep images co-located with the markdown (relative `images/...` refs) so the
  folder is portable.
- The charts themselves are lost as images if a site lazy-loads them and Playwright
  cannot reach the real src — re-run Step 3 after a fuller scroll if a figure is
  empty.
