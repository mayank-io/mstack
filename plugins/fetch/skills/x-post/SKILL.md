---
name: x-post
description: "Extract content from an X/Twitter post, thread, or article using the gstack browser. Detects threads automatically, walks back to the first post when the shared link lands mid-thread, and downloads images locally. Use when the user says \"read this x post\", \"get content from this tweet\", \"what does this x post say\", \"extract this tweet\", \"get the whole thread\", or shares an x.com/twitter.com URL."
---

# Download X Post

Use the gstack browser to navigate to an X/Twitter post, extract full content (tweets, threads, and X Articles), detect threads automatically, and download images locally.


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

## Input

The user provided: `$ARGUMENTS`

Parse input:
- **First argument**: X/Twitter URL (required)
- **Second argument**: Download directory for images (optional, defaults to current working directory)

## Process

### Step 1: Validate URL

Ensure the URL matches:
- `https://x.com/{username}/status/{id}`
- `https://twitter.com/{username}/status/{id}`

Extract the `{username}` and `{id}` (status ID) from the URL.

### Step 2: Extract Focal Post

Drive the **gstack browser** through the `_browse.py` adapter — never `mcp__playwright__*`. The adapter exposes a Playwright-shaped API (`goto`, `wait_for_selector`, `evaluate`) over `$B`, so the page-context JavaScript below is unchanged from the Playwright version; only the driver differs.

```python
import asyncio, json, sys   # asyncio only for asyncio.run()
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/scripts")
from _browse import browse_page

JS = r'''<the extraction function below>'''

async def main():
    async with browse_page() as page:          # headed, carries the user's session
        await page.goto("THE_URL_HERE")
        await page.wait_for_selector("article", timeout=15000)
        for _ in range(15):                    # poll up to 7.5s for media to load
            if await page.evaluate(IMAGES_READY_JS):
                break
            await page.wait_for_timeout(500)
        print(json.dumps(await page.evaluate(JS)))

asyncio.run(main())
```

⚠️ **`$B js` prints its result rather than returning it**, so the adapter wraps every expression in `JSON.stringify` before evaluating. An expression that already stringifies itself would be double-encoded — return a plain object and let the adapter serialise.

`IMAGES_READY_JS` — poll until media images have a real `src`:

```javascript
() => {
  const article = document.querySelector('article');
  if (!article) return true;
  const imgs = article.querySelectorAll('img[alt="Image"]');
  if (imgs.length === 0) return true;
  return Array.from(imgs).every(img => img.src && img.src.includes('pbs.twimg.com/media'));
}
```

The extraction function itself:

```javascript
() => {
    const article = document.querySelector('article');
    if (!article) return { error: 'No article found' };

    // Author
    const userLinks = article.querySelectorAll('a[role="link"]');
    let handle = '', displayName = '';
    for (const link of userLinks) {
      const href = link.getAttribute('href');
      if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/')) {
        handle = href.slice(1);
        displayName = link.textContent?.split('@')[0]?.trim() || handle;
        break;
      }
    }

    // Content
    const tweetText = article.querySelector('[data-testid="tweetText"]');
    let content = tweetText?.innerText || '';

    // Timestamp
    const timeEl = article.querySelector('time');
    const timestamp = timeEl?.getAttribute('datetime') || '';
    const displayTime = timeEl?.textContent || '';

    // Engagement metrics
    const engagementGroup = article.querySelector('[role="group"][aria-label]');
    const ariaLabel = engagementGroup?.getAttribute('aria-label') || '';
    const metrics = { likes: 0, reposts: 0, replies: 0, views: 0 };
    const likesMatch = ariaLabel.match(/(\d[\d,]*)\s*likes?/i);
    const repostsMatch = ariaLabel.match(/(\d[\d,]*)\s*reposts?/i);
    const repliesMatch = ariaLabel.match(/(\d[\d,]*)\s*repl(?:y|ies)/i);
    const viewsMatch = ariaLabel.match(/(\d[\d,]*)\s*views?/i);
    if (likesMatch) metrics.likes = parseInt(likesMatch[1].replace(/,/g, ''));
    if (repostsMatch) metrics.reposts = parseInt(repostsMatch[1].replace(/,/g, ''));
    if (repliesMatch) metrics.replies = parseInt(repliesMatch[1].replace(/,/g, ''));
    if (viewsMatch) metrics.views = parseInt(viewsMatch[1].replace(/,/g, ''));

    // Image count validation
    const photoLinks = article.querySelectorAll('a[href*="/photo/"]');
    const expectedImageCount = photoLinks.length;

    // Images — always request the ORIGINAL resolution, not 'large'.
    // X serves &name=small/medium/large as downscales; only 'orig' is the
    // full-resolution file, and a downscaled chart or screenshot is often
    // unreadable at the point it matters.
    const images = Array.from(article.querySelectorAll('img'))
      .filter(img => img.src && img.src.includes('pbs.twimg.com/media'))
      .map(img => img.src.replace(/name=\w+/, 'name=orig'));

    return { handle, displayName, content, timestamp, displayTime, metrics, images, expectedImageCount };
}
```

**Replace `THE_URL_HERE` with the actual URL.**

**Image validation:** If `expectedImageCount > 0` but `images.length === 0`, images failed to load. Re-run the extraction once more.

### Step 2.5: Find the Thread Root (Walk Backward to the First Post)

**A shared link is frequently NOT the first post in its thread** — users often copy a middle or final post. Before treating the focal post as the start, check whether earlier posts by the same author exist ABOVE it. If they do, the real thread begins higher up and everything downstream must start from that root.

When a post is a self-reply inside a thread, X renders its ancestor posts ABOVE the focal `<article>` in the conversation (DOM order: ancestors → focal → replies). Detect them:

```javascript
// Python driver (the JS below is the page-context evaluate):
//   await page.goto("FOCAL_URL_HERE")
//   await page.wait_for_selector("article", timeout=15000)
//   await page.wait_for_timeout(1500)
//   roots = await page.evaluate(JS, {"focalId": "...", "handle": "..."})
// Arguments ARE passed through — but only because the adapter applies them.
// Until 2026-08-24 they were silently dropped, and focalId arriving as
// undefined made this walk report "not a thread" for every real thread.
({ focalId, handle }) => {
    const articles = Array.from(document.querySelectorAll('article'));

    const handleOf = (a) => {
      for (const link of a.querySelectorAll('a[role="link"]')) {
        const href = link.getAttribute('href');
        if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/')) return href.slice(1);
      }
      return '';
    };
    // Prefer the timestamp permalink — that anchor points to the article's OWN status id
    const statusIdOf = (a) => {
      const timeAnchor = a.querySelector('time')?.closest('a[href*="/status/"]');
      const m = (timeAnchor?.getAttribute('href') || '').match(/\/status\/(\d+)/);
      if (m) return m[1];
      for (const link of a.querySelectorAll('a[href*="/status/"]')) {
        const mm = link.getAttribute('href').match(/\/status\/(\d+)/);
        if (mm) return mm[1];
      }
      return '';
    };

    // Locate the focal article, then collect same-author posts ABOVE it
    let focalIdx = articles.findIndex(a => statusIdOf(a) === focalId);
    if (focalIdx === -1) focalIdx = 0;

    const ancestors = [];
    for (let i = 0; i < focalIdx; i++) {
      if (handleOf(articles[i]).toLowerCase() === handle.toLowerCase()) {
        const sid = statusIdOf(articles[i]);
        if (sid && sid !== focalId) ancestors.push(sid);
      }
    }

    // Root = earliest (lowest) Snowflake ID among ancestors + focal
    const cluster = [...new Set([...ancestors, focalId])]
      .sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0));

    return { hasEarlier: ancestors.length > 0, rootId: cluster[0], ancestors };
}
```

**Replace** `FOCAL_URL_HERE` in the driver, and pass `focalId` / `handle` as the `evaluate` argument object rather than interpolating them into the JavaScript — an interpolated handle containing a quote would break the expression.

**Interpreting results:**

- **`hasEarlier: false`** — the link IS the first post (or a standalone post). Continue normally.
- **`hasEarlier: true`** — the link is mid-thread. Set the **root post** = `rootId`, navigate to `https://x.com/{handle}/status/{rootId}`, re-run Step 2 extraction on it, and treat `rootId` as the first post for every downstream step.

**Robustness — ancestors can lazy-load.** If `hasEarlier` is `false` but the focal post looks like a continuation (starts mid-sentence or with a connector like "And"/"But", opens with a list marker, or the article shows a "Show this thread" affordance), scroll UP a few times and re-check before concluding it is the first post:

```python
# Python — the wait cannot live in page JS; $B js returns before a promise
# resolves, so an in-page `await sleep()` loses the result silently.
for _ in range(5):
    await page.evaluate("() => window.scrollBy(0, -window.innerHeight)")
    await page.wait_for_timeout(800)
```

### Step 3: Detect X Article (Long-Form)

If `content` is empty or very short (< 50 characters), the post is an X Article. Fall back to accessibility snapshot:

1. Capture the full page structure with `"$B" snapshot` — the gstack accessibility snapshot. Do **not** use `mcp__playwright__browser_snapshot`: a fresh Playwright session is logged out and X Articles are frequently gated.
2. Parse the snapshot for article content:
   - **Title**: Look for text in `generic` elements near the top of the article
   - **Headings**: `heading [level=1]` or `heading [level=2]` elements
   - **Body text**: Sequential `generic` elements containing article paragraphs
   - **Links**: `link` elements with URLs
   - **Images**: `link "Image"` elements (note position for context)
3. Reconstruct the article text from the snapshot elements in order

For X Articles, preserve:
- Section headings (as markdown ## headers)
- Numbered/bulleted lists
- Embedded links
- Note where images appear in the flow (as `[Image: context]` markers)

### Step 4: Thread Detection

**IMPORTANT: Always check for threads — and always start from the FIRST post (the root from Step 2.5), not the originally-shared link.**

On the first post's page, scroll down to load thread posts, then find all articles by the same author. Capture a content snippet and a "replying to another user" flag for each, so the candidates can be filtered down to the genuine thread:

```javascript
// Python driver — scroll down to load thread posts below the fold:
//   previous = 0
//   for i in range(10):
//       await page.evaluate("() => window.scrollBy(0, window.innerHeight)")
//       await page.wait_for_timeout(1000)
//       current = await page.evaluate("() => document.querySelectorAll('article').length")
//       if current == previous and i > 1: break
//       previous = current
//
// X's timeline is VIRTUALISED: articles unmount as they leave the viewport.
// Accumulate into a page-context variable keyed by status id across the loop,
// then read it out once — a single pass at the end loses everything scrolled
// past. The JS below is the page-context evaluate:
(handle) => {
    const articles = document.querySelectorAll('article');
    const posts = [];
    const seen = new Set();

    for (const article of articles) {
      // Check author
      const userLinks = article.querySelectorAll('a[role="link"]');
      let articleHandle = '';
      for (const link of userLinks) {
        const href = link.getAttribute('href');
        if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/')) {
          articleHandle = href.slice(1);
          break;
        }
      }

      if (articleHandle.toLowerCase() !== handle.toLowerCase()) continue;

      // Get status ID from article links
      const allLinks = Array.from(article.querySelectorAll('a[href]'));
      let statusId = '';
      for (const link of allLinks) {
        const match = link.href.match(/\/status\/(\d+)$/);
        if (match) { statusId = match[1]; break; }
      }

      // Signals for thread-membership filtering (see Interpreting results)
      const tweetText = article.querySelector('[data-testid="tweetText"]');
      const snippet = (tweetText?.innerText || '').slice(0, 80);
      const isReplyToOther = /(^|\n)Replying to/.test(article.innerText || '');

      if (statusId && !seen.has(statusId)) {
        seen.add(statusId);
        posts.push({ statusId, snippet, isReplyToOther });
      }
    }

    // Sort by status ID ascending (Snowflake IDs = chronological order)
    posts.sort((a, b) => {
      if (a.statusId.length !== b.statusId.length) return a.statusId.length - b.statusId.length;
      return a.statusId < b.statusId ? -1 : a.statusId > b.statusId ? 1 : 0;
    });

    return posts;
}
```

Pass the author handle as the `evaluate` argument (`await page.evaluate(JS, handle)`), not by string-interpolating it into the JavaScript.

**Interpreting results:**

- **1 post found**: Not a thread. Continue with the first post's data.
- **Multiple posts found**: These are *candidates*, not all thread members. A thread is posted in one sitting, so genuine members form a tight cluster of near-sequential Snowflake IDs with near-identical timestamps. The author's later replies to commenters get swept up here too — **filter them out first**:
  - **Keep** the contiguous self-reply chain that starts at the root: posts whose IDs increment by small amounts with no large gap from the previous kept post (the cluster typically spans seconds to a few minutes).
  - **Drop** any post flagged `isReplyToOther: true`, and any post sitting after a large ID/timestamp gap from the previous thread member — those are the author replying to other users, NOT part of the thread. (This is the most common false positive: e.g. a 7-post thread where IDs jump from `…594659836065` to `…681933271330968` — everything from the jump onward is replies-to-commenters.)
  - Sanity-check with the `snippet`s: real thread posts continue one narrative; dropped ones are short one-liners aimed at someone else ("Thank you!", "Congrats!", or starting with `@handle`).

  For each KEPT post OTHER than the root:
  1. Navigate to `https://x.com/{handle}/status/{statusId}`
  2. Run the Step 2 extraction code to get full content and images
  3. If content is empty/short, apply Step 3 (X Article detection) for that post
  4. Collect all posts in the chronological order returned by the script

After extracting all kept posts, assemble the complete thread data as an array sorted chronologically (root first).

### Step 5: Download Images

Collect all image URLs from all extracted posts (focal + thread). Download each using curl:

```bash
curl -L "<image_url>" -o "<output_dir>/<handle>-<statusId>-<N>.jpg"
```

Where:
- `<output_dir>`: User-specified directory or current working directory
- `<handle>`: Author's handle (lowercase)
- `<statusId>`: The post's status ID
- `<N>`: Image index within that post (1, 2, 3...)

Run downloads in parallel when possible (multiple curl commands in one bash call separated by `&` and a final `wait`).

Report the count and paths of downloaded images.

### Step 6: Present Structured Content

**Single Post:**

```
## @{handle} — {title or first line}

**Date:** {displayTime}
**Engagement:** {likes} likes, {reposts} reposts, {replies} replies, {views} views
**URL:** {original url}

---

{Full post content}

---

**Images:** {count} images downloaded
{list each filename}
```

**Thread:**

```
## @{handle} — {title or first line} (Thread: {n} posts)

**Date:** {displayTime}
**Engagement:** {likes} likes, {reposts} reposts, {replies} replies, {views} views
**URL:** {original url}

---

### Post 1/{n}

{content of first post}

**Images:** {list of downloaded filenames for this post}

---

### Post 2/{n}

{content of second post}

**Images:** {list of downloaded filenames for this post}

---

[... continue for all posts ...]
```

**X Article:**

Same as single post format but with section headings preserved and `[Image: context]` markers replaced with downloaded filenames.

## Tips

- X blocks direct HTTP fetching — a real browser is required, and it must be the gstack one (the user's logged-in session). A logged-out browser returns a login wall that looks like an empty post rather than an error.
- Regular tweets have `[data-testid="tweetText"]`; X Articles do not
- Thread posts are detected by finding multiple `<article>` elements by the same author
- The shared link may be mid-thread — Step 2.5 walks back to the first post via the ancestor articles rendered ABOVE the focal tweet
- Same-author ≠ same-thread: the author's replies to commenters appear by the same handle. Distinguish real thread members by tight ID/timestamp clustering and `isReplyToOther`; large ID gaps mark the end of the thread
- Thread posts in the page view may be truncated — always navigate to individual URLs for full content
- Status IDs are Snowflake-based: ascending = chronological order; threads posted together have near-adjacent IDs
- Images are downloaded at full resolution (`name=large`)
- If the page requires login, extraction may be limited

## Examples

### Example 1: Regular Tweet
Input: `/fetch:x-post https://x.com/elonmusk/status/123456`
Result: Extracts tweet text, metrics, downloads images; presents in conversation

### Example 2: X Article
Input: `/fetch:x-post https://x.com/0xMovez/status/2004570871294239187`
Result: Detects empty tweetText, falls back to snapshot, extracts full article with all sections

### Example 3: Thread
Input: `/fetch:x-post https://x.com/bourboncap/status/2020489596505592084`
Result: Extracts focal post, detects 5 more posts by same author, navigates to each, downloads all images, presents complete 6-post thread

### Example 4: Mid-thread link (walk back to the first post)
Input: `/fetch:x-post https://x.com/ericjackson/status/1997633594659836065`
Result: Step 2.5 finds 6 earlier same-author posts above the focal → resets the root to `…633559859790018` ("…here's the truth 👇"). Step 4 collects candidates, drops the author's later replies-to-commenters after the ID gap, and presents the genuine 7-post thread in order (the originally-shared link turns out to be post 7/7).
