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
close it. The adapter's `close()` is deliberately a no-op, so leaving the
`async with browse_page()` block tears down nothing.

**Never launch a headless browser.** Not `headless=True`, not `--headless`, not a fresh `chromium.launch()`. If gstack is unavailable, stop and say so — a logged-out capture is worse than none, because it looks fine.

**Page JavaScript must be synchronous, and values are passed as arguments.** `$B js`
returns before a promise resolves, so `evaluate()` refuses any expression that is an
`async` function or contains `await` — the result would be silently lost. Drive the
waiting and looping from Python with `await page.wait_for_timeout(ms)` between
synchronous `evaluate()` calls. Pass values with `await page.evaluate(js, arg)`
rather than string-interpolating them into the JavaScript: an interpolated value
containing a quote breaks the expression.

## Input

`$ARGUMENTS`:

- **First argument** — LinkedIn post URL (required): `linkedin.com/posts/…` or `linkedin.com/feed/update/…`
- **Second argument** — output directory (optional). Omitted, a temp directory is used. Created if missing. **Never write outside it.**

## Step 1 — Navigate and expand

```bash
"$B" goto "<url>"
```

### Expanding the body

**LinkedIn truncates long posts and hides the rest behind a "…more" control.** A truncated capture reads as a complete short post, so expanding is not optional.

The control is **not always present**, and where it appears depends on the surface:

| Surface | "…more" present? |
|---|---|
| A company or member **posts listing** — `linkedin.com/company/<name>/posts/` | **Yes**, on every post whose text overflows |
| A **post permalink** — `linkedin.com/posts/<slug>-<id>` | **Often not.** The permalink frequently renders the truncated public variant with no expander at all. |

**So try the listing surface when the permalink is short.** If a permalink yields a body under ~250 characters with no expander, the same post on its author's `/posts/` listing usually carries the full text plus a working "…more".

### Match the control by its TEXT, never by class or aria-label

**LinkedIn ships obfuscated, rotating class names.** The real control looks like this:

```
<button class="_5a3a1b6d _22e49b38 _060cf413 _6093ac50 …">… more</button>
```

Hashed classes, and **`aria-label` is empty**. Every class-based or aria-based selector fails silently — it matches nothing and reports zero expanders, which is indistinguishable from a post that needed no expansion. The only stable signal is the **button's text: `… more`**.

Match it exactly. A loose `/more/i` also catches `"More actions for <company>"`, which opens a menu:

```javascript
() => {
  let n = 0;
  Array.from(document.querySelectorAll('button')).forEach(b => {
    const t = (b.innerText || '').trim();
    if (!/^(…|\.\.\.)?\s*(see|show)?\s*more$/i.test(t)) return;   // exact, not "More actions for X"
    if (b.closest('.comments-comment-item, .comments-comment-entity')) return;  // comments, not body
    b.click(); n++;
  });
  return n;
}
```

### Loop until no expanders remain — one pass is not enough

Expanding reveals **more posts**, each with its own control. Measured on a real company listing: round 1 clicked 3, which surfaced 10 more; round 2 clicked those 10; round 3 found none.

```python
for _ in range(8):
    n = await page.evaluate(EXPAND_JS)
    if n == 0:
        break                       # converged
    await page.wait_for_timeout(1800)
```

**Verified 2026-08-24** on `linkedin.com/company/kodiakai/posts/`: 13 expanders over 3 rounds, body **5,725 → 11,628 characters — 2× the text**. Stopping after one pass would have captured roughly half the page and looked complete.

**Report the character delta.** A click that adds ~50 characters expanded a comment, not the post — the signature of hitting the wrong control, which otherwise looks like success.

### Login walls

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

⚠️ Page JavaScript stays synchronous — see the browser section above. `fetch:blog-post` Step 3 shows the Python-driven loop shape.

## Step 3 — Download the attachments

**The attachment is frequently the content.** A post whose body reads "The Ultimate List of AI Neolabs — there are now 63 of them!" carries those 63 names in an attached image, not in text. Capturing the body and skipping the image captures the caption and loses the post.

### Tell attachments apart from page furniture

Filtering by size alone does not work — avatars are 400×400 and pass any sensible threshold. Discriminate on the **URL path segment**, which LinkedIn sets by role.

Measured 2026-08-24 against the live site:

| Surface | naive `naturalWidth >= 200` | path-segment filter |
|---|---|---|
| A post permalink | 2 images | **1** — the actual attachment |
| A company posts listing | 5 images | **1** — the actual attachment |
| (an earlier read of the same permalink) | 8 images | **1** — the other 7 were avatars, a banner and sidebar covers |


| URL contains | What it is | Take it? |
|---|---|---|
| `/image-shrink_` , `/feedshare-shrink_` , `/feedshare-image-high-res` , `/feedshare-` | **post attachment** — all four observed live | ✅ yes |
| `/profile-displayphoto` | author or commenter avatar | ❌ no |
| `/profile-displaybackgroundimage` | profile banner | ❌ no |
| `/article-cover_image` | "more from LinkedIn" sidebar | ❌ no |
| `/company-logo_` , `/spotlight-` | brand furniture | ❌ no |

```javascript
() => Array.from(document.querySelectorAll('img'))
  .map(i => i.currentSrc || i.src || '')
  .filter(u => /\/(image-shrink_|feedshare-shrink_|feedshare-)/.test(u))
  .filter((u, n, a) => a.indexOf(u) === n)
```

### Ask for the largest rendition

LinkedIn encodes the rendition in the path — `image-shrink_800` is a downscale. Rewrite the size upward before downloading and fall back if the larger one 404s:

```bash
big="${url/image-shrink_800/image-shrink_1280}"
curl -fsL -o "<output_dir>/linkedin-<author>-<n>.jpg" "$big" \
  || curl -fsL -o "<output_dir>/linkedin-<author>-<n>.jpg" "$url"
```

Same reasoning as requesting `name=orig` on X: **a downscaled image is unreadable exactly when it matters** — a list, a table, a chart, a screenshot of text.

### Carousels and documents

A post can attach a multi-page PDF carousel (`.native-document`, `[class*=carousel]`) rather than a single image. Those paginate — capture **every** page, and report the page count. One page of a twelve-page carousel is not the attachment.

### When curl is refused

LinkedIn's CDN sometimes rejects a bare `curl`. Screenshot the image element through gstack rather than skipping it — **and say in your report that it was screenshotted rather than downloaded**, since a re-encode is not the original asset.

### Read what you downloaded

If the body is short and an attachment is present, **the attachment is the post.** Open the image and describe or transcribe its content into the note. Filing an unexamined image and summarising from the caption is how the list of 63 gets lost.

## Step 4 — Report

Write the extracted fields as JSON alongside the images, then print the directory as the **final stdout line**:

```
OUTPUT_DIR:/absolute/path/to/output
```

The marker must be last. Callers chain on it and must never reconstruct the path.

## ⚠️ LinkedIn serves a truncated public view on post permalinks

**Verified 2026-08-24, and it is not a session problem you can fix by logging in.** With a live LinkedIn session in the gstack browser — `/feed/` rendering fully, notifications present — a `/posts/…` permalink still returned the logged-out chrome ("Sign in · Join now") and a post body of **203 characters**, cut mid-thought at "There are now 63 of them!". The list of 63 was not on the page at all.

What was checked, so you do not repeat it:

| Attempt | Result |
|---|---|
| Session live? | Yes — `/feed/` signed in, notifications visible |
| Auth modal blocking? | No — `.authwall` absent |
| A "Show more" button? | Present, but it expands **comments**. Clicking added 48 characters, all of them replies. |
| A separate expander for the body? | **None exists.** The only expanders are "Show more" and "See more comments". |
| `/feed/update/urn:li:activity:<id>/` (the authenticated form) | Redirects to `/signup/cold-join` |

**Two things to try before accepting the truncation**, in order:

1. **The author's posts listing.** `linkedin.com/company/<name>/posts/` (or a member's `/recent-activity/all/`) renders the same post with a working "…more" control that the permalink lacks. This is the highest-value fallback.
2. **The attachment.** On the post above, the missing list of 63 was **in an attached image all along** — an `800×1491` graphic. The body was genuinely truncated *and* the content was still fully present, just not as text. Always run Step 3 before concluding anything is missing.

Only after both: **capture what is served and say plainly that the body is truncated.** Report the character count and the last words captured. Never present a 203-character fragment as the post.

What comes through reliably regardless: author name, relative date, reaction and comment counts, comment text, attachments, and the link-preview card.

If the full body text is still needed after all that, the reliable route is a human opening the post in their own session and copying it — not more automation.

## Failure modes worth naming

- **A short post that should be long** — either "…see more" was never expanded, or you have hit the permalink truncation above. Distinguish them: check whether a body expander exists at all before blaming the click.
- **Author headline missing** — common on reshares; report it absent rather than substituting the reshared author's.
- **Zero images on a post that clearly has them** — usually lazy-loading. Scroll the post into view, wait, re-collect.
- **A login wall captured as content** — the failure this skill exists to prevent. If the text mentions signing in or joining LinkedIn, treat the capture as failed.
