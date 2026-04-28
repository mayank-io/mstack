---
name: x-post
description: "Extract content from an X/Twitter post, thread, or article using Playwright. Detects threads automatically and downloads images locally. Use when the user says \"read this x post\", \"get content from this tweet\", \"what does this x post say\", \"extract this tweet\", or shares an x.com/twitter.com URL."
---

# Download X Post

Use Playwright to navigate to an X/Twitter post, extract full content (tweets, threads, and X Articles), detect threads automatically, and download images locally.

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

### Step 2: Extract Focal Post with Playwright

Use `mcp__playwright__browser_run_code` to navigate and extract. This code includes an image-wait polling loop (up to 7.5s) to ensure media images have loaded:

```javascript
async (page) => {
  await page.goto('THE_URL_HERE');
  await page.waitForSelector('article', { timeout: 15000 });

  // Poll until media images have loaded src (up to 7.5s)
  for (let i = 0; i < 15; i++) {
    const hasImages = await page.evaluate(() => {
      const article = document.querySelector('article');
      if (!article) return true;
      const imgs = article.querySelectorAll('img[alt="Image"]');
      if (imgs.length === 0) return true;
      return Array.from(imgs).every(img => img.src && img.src.includes('pbs.twimg.com/media'));
    });
    if (hasImages) break;
    await page.waitForTimeout(500);
  }

  return await page.evaluate(() => {
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

    // Images
    const images = Array.from(article.querySelectorAll('img'))
      .filter(img => img.src && img.src.includes('pbs.twimg.com/media'))
      .map(img => img.src.replace(/name=\w+/, 'name=large'));

    return { handle, displayName, content, timestamp, displayTime, metrics, images, expectedImageCount };
  });
}
```

**Replace `THE_URL_HERE` with the actual URL.**

**Image validation:** If `expectedImageCount > 0` but `images.length === 0`, images failed to load. Re-run the extraction once more.

### Step 3: Detect X Article (Long-Form)

If `content` is empty or very short (< 50 characters), the post is an X Article. Fall back to accessibility snapshot:

1. Use `mcp__playwright__browser_snapshot` to capture the full page structure
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

**IMPORTANT: Always check for threads after extracting the focal post.**

While still on the page from Step 2, scroll down to load thread posts, then find all articles by the same author:

```javascript
async (page) => {
  // Scroll down to load thread posts below the fold
  let previousCount = 0;
  for (let i = 0; i < 10; i++) {
    await page.evaluate(() => window.scrollBy(0, window.innerHeight));
    await page.waitForTimeout(1000);
    const currentCount = await page.evaluate(() => document.querySelectorAll('article').length);
    if (currentCount === previousCount && i > 1) break;
    previousCount = currentCount;
  }

  const focalHandle = 'FOCAL_HANDLE_HERE';

  return await page.evaluate((handle) => {
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

      if (statusId && !seen.has(statusId)) {
        seen.add(statusId);
        posts.push({ statusId });
      }
    }

    // Sort by status ID ascending (Snowflake IDs = chronological order)
    posts.sort((a, b) => {
      if (a.statusId.length !== b.statusId.length) return a.statusId.length - b.statusId.length;
      return a.statusId < b.statusId ? -1 : a.statusId > b.statusId ? 1 : 0;
    });

    return posts;
  }, focalHandle);
}
```

**Replace `FOCAL_HANDLE_HERE` with the `handle` value from Step 2.**

**Interpreting results:**

- **1 post found**: Not a thread. Continue with the focal post data from Step 2.
- **Multiple posts found**: This is a thread. For each thread post OTHER than the focal post:
  1. Navigate to `https://x.com/{handle}/status/{statusId}`
  2. Run the Step 2 extraction code to get full content and images
  3. If content is empty/short, apply Step 3 (X Article detection) for that post
  4. Collect all posts in the chronological order returned by the script

After extracting all thread posts, assemble the complete thread data as an array of posts sorted chronologically.

### Step 5: Download Images

Collect all image URLs from all extracted posts (focal + thread). Download each using curl:

```bash
curl -L "<image_url>" -o "<download_dir>/<handle>-<statusId>-<N>.jpg"
```

Where:
- `<download_dir>`: User-specified directory or current working directory
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

- X blocks direct HTTP fetching — Playwright is required
- Regular tweets have `[data-testid="tweetText"]`; X Articles do not
- Thread posts are detected by finding multiple `<article>` elements by the same author
- Thread posts in the page view may be truncated — always navigate to individual URLs for full content
- Status IDs are Snowflake-based: ascending = chronological order
- Images are downloaded at full resolution (`name=large`)
- If the page requires login, extraction may be limited

## Examples

### Example 1: Regular Tweet
Input: `/download:x-post https://x.com/elonmusk/status/123456`
Result: Extracts tweet text, metrics, downloads images; presents in conversation

### Example 2: X Article
Input: `/download:x-post https://x.com/0xMovez/status/2004570871294239187`
Result: Detects empty tweetText, falls back to snapshot, extracts full article with all sections

### Example 3: Thread
Input: `/download:x-post https://x.com/bourboncap/status/2020489596505592084`
Result: Extracts focal post, detects 5 more posts by same author, navigates to each, downloads all images, presents complete 6-post thread
