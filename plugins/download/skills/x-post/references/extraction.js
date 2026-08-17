/*
 * CANONICAL X post/thread extraction — SINGLE SOURCE OF TRUTH.
 *
 * Both the `download:x-post` skill AND the `x-account` bulk harvester load and
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

  // Step 2 — extract the focal (first) article on the current page.
  function extractFocal() {
    const article = document.querySelector('article');
    if (!article) return { error: 'No article found' };

    let handle = '', displayName = '';
    for (const link of article.querySelectorAll('a[role="link"]')) {
      const href = link.getAttribute('href');
      if (href && href.match(/^\/[^\/]+$/) && !href.includes('/status/')) {
        handle = href.slice(1);
        displayName = (link.textContent && link.textContent.split('@')[0].trim()) || handle;
        break;
      }
    }

    const tweetText = article.querySelector('[data-testid="tweetText"]');
    const content = (tweetText && tweetText.innerText) || '';

    const timeEl = article.querySelector('time');
    const timestamp = (timeEl && timeEl.getAttribute('datetime')) || '';

    const g = article.querySelector('[role="group"][aria-label]');
    const metrics = parseMetrics((g && g.getAttribute('aria-label')) || '');

    const photoLinks = article.querySelectorAll('a[href*="/photo/"]');
    const images = Array.from(article.querySelectorAll('img'))
      .filter((img) => img.src && img.src.includes('pbs.twimg.com/media'))
      .map((img) => img.src.replace(/name=\w+/, 'name=large'));

    return { handle, displayName, content, timestamp, metrics,
             expectedImageCount: photoLinks.length, images };
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

  window.__xExtract = { extractFocal, findRoot, detectThreadMembers, statusIdOf, handleOf };
})();
