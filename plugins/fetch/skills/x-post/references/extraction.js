/*
 * CANONICAL X post/thread extraction — SINGLE SOURCE OF TRUTH.
 *
 * Both the `fetch:x-post` skill AND the `x-account` bulk harvester load and
 * call THIS file. Do not copy these functions elsewhere: iterate here once and
 * every consumer benefits. (Design Approach C — shared extraction reference.)
 *
 * Loaded by injecting this file's contents into the page, then calling e.g.
 *   __xExtract.extractFocal()
 *   __xExtract.findRoot(focalId, handle)
 *   __xExtract.detectThreadMembers(handle)
 *
 * All three operate on document.querySelectorAll('article') in the current DOM;
 * the caller is responsible for navigation, waits, and scrolling.
 */
(function () {
  function handleOf(a) {
    for (const link of a.querySelectorAll('a[role="link"]')) {
      const href = link.getAttribute('href');
      if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/')) return href.slice(1);
    }
    return '';
  }

  // The timestamp permalink points at the article's OWN status id; fall back to
  // the first status link in DOM order (header permalink precedes quote cards).
  function statusIdOf(a) {
    const t = a.querySelector('time');
    const timeAnchor = t && t.closest('a[href*="/status/"]');
    let m = ((timeAnchor && timeAnchor.getAttribute('href')) || '').match(/\/status\/(\d+)/);
    if (m) return m[1];
    const links = Array.from(a.querySelectorAll('a[href*="/status/"]'));
    for (const link of links) {
      const mm = link.getAttribute('href').match(/\/status\/(\d+)/);
      if (mm) return mm[1];
    }
    return '';
  }

  function parseMetrics(ariaLabel) {
    const metrics = { likes: 0, reposts: 0, replies: 0, views: 0 };
    const m = (pat) => { const x = ariaLabel.match(pat); return x ? parseInt(x[1].replace(/,/g, '')) : 0; };
    metrics.likes = m(/(\d[\d,]*)\s*likes?/i);
    metrics.reposts = m(/(\d[\d,]*)\s*reposts?/i);
    metrics.replies = m(/(\d[\d,]*)\s*repl(?:y|ies)/i);
    metrics.views = m(/(\d[\d,]*)\s*views?/i);
    return metrics;
  }

  // Duration of a video, in seconds, from the play button's aria-label.
  //
  // The label — "Play Video. 53 minutes 35 seconds long" — is the ONLY place X
  // renders a duration in the DOM. There is no data attribute and no visible
  // text carrying it, so losing this label means losing the one signal that
  // says whether a post is a 12-second clip or a 53-minute lecture.
  function parseVideoDuration(ariaLabel) {
    if (!ariaLabel) return null;
    const unit = (pat) => { const m = ariaLabel.match(pat); return m ? parseInt(m[1], 10) : 0; };
    const hours = unit(/(\d+)\s*hours?/i);
    const minutes = unit(/(\d+)\s*minutes?/i);
    const seconds = unit(/(\d+)\s*seconds?/i);
    if (!hours && !minutes && !seconds) return null;
    return hours * 3600 + minutes * 60 + seconds;
  }

  // Video presence and duration for one <article>.
  //
  // A video post whose capture holds only the caption is not a capture: the
  // caption is the hook and the video is the content. Detection lives here so
  // the driver can decide to transcribe; transcription itself cannot run in
  // the extractor (a 53-minute source outlives any page-script budget).
  function extractVideo(article) {
    const player = article.querySelector('[data-testid="videoPlayer"], [data-testid="videoComponent"]');
    const playBtn = article.querySelector('[aria-label*="Play Video" i], [aria-label*="Play Tweet video" i]');
    const videoEl = article.querySelector('video');
    if (!player && !playBtn && !videoEl) return null;

    // The duration label is NOT always in the DOM. On a cold load the player
    // renders <video aria-label="Embedded video"> with no duration anywhere;
    // the "Play Video. 53 minutes 35 seconds long" name is computed later.
    // Absent duration therefore means unknown, never short.
    const label = (playBtn && playBtn.getAttribute('aria-label')) || '';
    const seconds = parseVideoDuration(label);

    // A GIF is rendered with the same machinery but carries no duration and is
    // silent. Transcribing one wastes minutes and yields nothing.
    const isGif = /\bGIF\b/i.test(label) ||
                  !!article.querySelector('[data-testid="placementTracking"] [aria-label*="GIF" i]');

    // The poster lives on ext_tw_video_thumb / amplify_video_thumb, NOT on the
    // /media path the image extractor filters for, so it is never picked up as
    // a normal image and has to be read off the <video> element.
    const poster = (videoEl && videoEl.getAttribute('poster')) || '';

    // The poster path carries the MEDIA id, which is a Snowflake like the
    // status id and so timestamps when the video was uploaded. A post whose
    // media predates it by days is showing someone else's upload — the one
    // re-upload signal that is visible without leaving the page.
    const m = poster.match(/(?:amplify_video_thumb|ext_tw_video_thumb)\/(\d+)\//);
    const mediaId = m ? m[1] : '';

    return { present: true, isGif, durationLabel: label, seconds, poster, mediaId };
  }

  // Has the media in this article finished mounting?
  //
  // X renders the tweetPhoto container first and hydrates the player into it a
  // beat later, so extracting the instant `article` appears reports a video
  // post as having no video at all — the same lazy-mount trap imagesReady()
  // guards for images, and just as silent: the note looks like a short text
  // post and nothing errors.
  function mediaReady(article) {
    const a = article || document.querySelector('article');
    if (!a) return false;
    const holders = a.querySelectorAll('[data-testid="tweetPhoto"]');
    if (!holders.length) return true;   // nothing to wait for
    return Array.from(holders).every((h) =>
      h.querySelector('[data-testid="videoPlayer"], [data-testid="videoComponent"], video') ||
      Array.from(h.querySelectorAll('img')).some((i) => i.src && i.src.includes('pbs.twimg.com')));
  }

  // Extract one <article> node's full data (author, text, time, metrics, images).
  function extractArticle(article) {
    let handle = '';
    for (const link of article.querySelectorAll('a[role="link"]')) {
      const href = link.getAttribute('href');
      if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/')) { handle = href.slice(1); break; }
    }
    // Display name: the first author link is often the avatar (empty text),
    // so prefer the User-Name testid's first line; then any non-empty author
    // link that isn't the @handle; finally fall back to the handle.
    let displayName = '';
    const un = article.querySelector('[data-testid="User-Name"]');
    if (un) { const first = (un.innerText || '').split('\n')[0].trim(); if (first && first[0] !== '@') displayName = first; }
    if (!displayName) {
      for (const link of article.querySelectorAll('a[role="link"]')) {
        const href = link.getAttribute('href');
        const txt = (link.textContent || '').trim();
        if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/') && txt && txt[0] !== '@') {
          displayName = txt.split('@')[0].trim(); break;
        }
      }
    }
    if (!displayName) displayName = handle;

    const tweetText = article.querySelector('[data-testid="tweetText"]');
    const content = (tweetText && tweetText.innerText) || '';

    const timeEl = article.querySelector('time');
    const timestamp = (timeEl && timeEl.getAttribute('datetime')) || '';

    const g = article.querySelector('[role="group"][aria-label]');
    const metrics = parseMetrics((g && g.getAttribute('aria-label')) || '');

    // Always request the ORIGINAL resolution, never 'large'. X serves
    // &name=small/medium/large as downscales; only 'orig' is the full-resolution
    // file, and a downscaled chart or screenshot is often unreadable at exactly
    // the point it matters.
    const photoLinks = article.querySelectorAll('a[href*="/photo/"]');
    const images = Array.from(article.querySelectorAll('img'))
      .filter((img) => img.src && img.src.includes('pbs.twimg.com/media'))
      .map((img) => img.src.replace(/name=\w+/, 'name=orig'));

    const video = extractVideo(article);

    return { statusId: statusIdOf(article), handle, displayName, content, timestamp, metrics,
             expectedImageCount: photoLinks.length, images, video };
  }

  // Step 2 — extract the focal (first) article on the current page.
  function extractFocal() {
    const article = document.querySelector('article');
    if (!article) return { error: 'No article found' };
    return extractArticle(article);
  }

  // Extract EVERY same-author article on the current conversation page, with
  // full content — used by click-into-post navigation so a whole thread is
  // captured from one page (no per-post URL navigation, which looks robotic).
  function extractAllByAuthor(handle) {
    const out = []; const seen = new Set();
    for (const article of document.querySelectorAll('article')) {
      if (handleOf(article).toLowerCase() !== handle.toLowerCase()) continue;
      const d = extractArticle(article);
      const isReplyToOther = /(^|\n)Replying to/.test(article.innerText || '');
      if (d.statusId && !seen.has(d.statusId)) { seen.add(d.statusId); out.push({ ...d, isReplyToOther }); }
    }
    out.sort((a, b) => a.statusId.length - b.statusId.length ||
      (a.statusId < b.statusId ? -1 : a.statusId > b.statusId ? 1 : 0));
    return out;
  }

  // Step 2.5 — walk backward to the thread root (ancestors render ABOVE focal).
  function findRoot(focalId, handle) {
    const articles = Array.from(document.querySelectorAll('article'));
    let focalIdx = articles.findIndex((a) => statusIdOf(a) === focalId);
    if (focalIdx === -1) focalIdx = 0;
    const ancestors = [];
    for (let i = 0; i < focalIdx; i++) {
      if (handleOf(articles[i]).toLowerCase() === handle.toLowerCase()) {
        const sid = statusIdOf(articles[i]);
        if (sid && sid !== focalId) ancestors.push(sid);
      }
    }
    const cluster = [...new Set([...ancestors, focalId])]
      .sort((a, b) => a.length - b.length || (a < b ? -1 : a > b ? 1 : 0));
    return { hasEarlier: ancestors.length > 0, rootId: cluster[0], ancestors };
  }

  // Step 4 — same-author candidate posts on the root page, with the
  // thread-membership signals (snippet + replying-to-other). Filtering to the
  // genuine contiguous chain is done by the caller (Snowflake clustering).
  function detectThreadMembers(handle) {
    const articles = document.querySelectorAll('article');
    const posts = []; const seen = new Set();
    for (const article of articles) {
      if (handleOf(article).toLowerCase() !== handle.toLowerCase()) continue;
      const statusId = statusIdOf(article);
      const tweetText = article.querySelector('[data-testid="tweetText"]');
      const snippet = ((tweetText && tweetText.innerText) || '').slice(0, 80);
      const isReplyToOther = /(^|\n)Replying to/.test(article.innerText || '');
      if (statusId && !seen.has(statusId)) { seen.add(statusId); posts.push({ statusId, snippet, isReplyToOther }); }
    }
    posts.sort((a, b) => a.statusId.length - b.statusId.length ||
      (a.statusId < b.statusId ? -1 : a.statusId > b.statusId ? 1 : 0));
    return posts;
  }

  // Media-load gate. X mounts <img alt="Image"> before the pbs.twimg.com src
  // is set, so extracting the instant `article` appears returns zero images for
  // a post that has four. Poll this from the DRIVER (synchronously, between
  // waits) rather than awaiting inside the page: `$B js` returns before a
  // promise resolves, so an in-page sleep loses the result silently.
  function imagesReady() {
    const article = document.querySelector('article');
    if (!article) return true;
    const imgs = article.querySelectorAll('img[alt="Image"]');
    if (imgs.length === 0) return true;
    return Array.from(imgs).every((img) => img.src && img.src.includes('pbs.twimg.com/media'));
  }

  // X Articles (long-form). A regular tweet has [data-testid="tweetText"]; an
  // Article does not, so extractArticle() returns content:'' for a 40k-character
  // essay — emptiness is the DETECTION SIGNAL, not a result.
  //
  // Read from the DOM, not from an accessibility snapshot: the snapshot of one
  // measured article was 53,899 bytes and flattened the heading/body
  // relationship the caller needs to rebuild sections.
  //
  // `body` arrives as ONE block and the headings are ALSO inside it — the
  // heading list is an index, not content to concatenate. Appending headings to
  // the body duplicates every one; rendering only the headings loses the
  // article. Split the body on its own headings, in document order.
  function extractLongform() {
    const root = document.querySelector('[data-testid=twitterArticleRichTextView]');
    if (!root) return { error: 'not an article' };
    const body = root.querySelector('[data-testid=longformRichTextComponent]');
    return {
      body: body ? body.innerText : '',
      headings: Array.from(root.querySelectorAll('h1,h2,h3'))
        .map((h) => ({ level: h.tagName.toLowerCase(), text: h.innerText.trim() }))
        .filter((h) => h.text),
      links: Array.from(root.querySelectorAll('a[href^="http"]'))
        .map((a) => ({ text: (a.innerText || '').trim(), href: a.href })),
      images: Array.from(root.querySelectorAll('img'))
        .map((i) => i.src).filter((s) => s && s.includes('pbs.twimg.com/media'))
        .map((s) => s.replace(/name=\w+/, 'name=orig'))
    };
  }

  window.__xExtract = { extractFocal, extractArticle, extractAllByAuthor,
                        findRoot, detectThreadMembers, extractLongform,
                        imagesReady, statusIdOf, handleOf,
                        extractVideo, parseVideoDuration, mediaReady };
})();
