/*
 * CANONICAL LinkedIn ARTICLE (linkedin.com/pulse/...) extraction — SINGLE SOURCE OF TRUTH.
 *
 * Loaded by `scripts/linkedin_article_download.py` (injected into the page) and
 * by `scripts/tests/test_linkedin_article.py` (run under jsdom against a saved
 * copy of a live article). Do not copy these functions elsewhere.
 *
 *   __liArticle.extract()  -> {title, author_name, author_headline, author_url,
 *                              published_label, cover, blocks, metrics, links}
 *   __liArticle.imagesPending() -> count of article images with no usable src yet
 *
 * Articles are NOT posts. None of the post-mode anchors exist on a Pulse page:
 * there is no hidden "Feed post" heading, no "...more" expander, no activity id
 * in the URL. The article lives in <article>, the body is a run of
 * `reader-*` blocks, and images sit BETWEEN paragraphs, so the body is returned
 * as ordered blocks rather than as one string.
 *
 * Text is read with textContent, never innerText: innerText is layout-dependent
 * and jsdom does not implement it, so a function using it would pass in the
 * browser and return "" under test.
 */
(function () {
  const ATTACHMENT = /\/(article-cover_image|article-inline_image)-/;
  const FILE_HOST = /\.(md|json|ya?ml|py|js|ts|txt|sh)$/i;

  function clean(s) {
    return (s || '').replace(/ /g, ' ').replace(/[ \t\r\n]+/g, ' ').trim();
  }

  // LinkedIn wraps external links as /safety/go/?url=<target>. The wrapper is
  // not the link; bare filenames ("CLAUDE.md") get auto-linked as hosts.
  function unwrapLink(href) {
    let u = href || '';
    try {
      const p = new URL(u, 'https://www.linkedin.com');
      if (p.pathname.startsWith('/safety/go')) u = p.searchParams.get('url') || '';
      else u = p.href;
      if (!u) return '';
      const host = new URL(u).hostname;
      if (FILE_HOST.test(host)) return '';
    } catch (e) {
      return '';
    }
    return u;
  }

  // The widest srcset candidate, else src. Signed URLs (e=/t=) cannot be
  // rewritten to a larger rendition, so srcset is the only way up.
  function bestSrc(img) {
    const ss = img.getAttribute('srcset') || '';
    if (ss) {
      const cands = ss.split(',').map((s) => s.trim().split(/\s+/))
        .filter((p) => p[0])
        .map((p) => ({ u: p[0], w: parseInt((p[1] || '0').replace(/\D/g, ''), 10) || 0 }));
      if (cands.length) return cands.sort((a, b) => b.w - a.w)[0].u;
    }
    return img.getAttribute('src') || img.getAttribute('data-delayed-url') || '';
  }

  // Inline markdown for one block: bold, italic, links, line breaks. Returns
  // the text and the external links seen, so links stay scoped to the body.
  function inline(node, links) {
    let out = '';
    node.childNodes.forEach((c) => {
      if (c.nodeType === 3) { out += c.nodeValue; return; }
      if (c.nodeType !== 1) return;
      const tag = c.tagName.toLowerCase();
      if (tag === 'br') { out += '\n'; return; }
      const inner = inline(c, links);
      // Emphasis markers wrap the trimmed text; edge whitespace moves OUTSIDE
      // them. LinkedIn puts the separating space inside <strong> ("workflow: "),
      // and `**workflow: **Doubleclick` both fails to render and fuses the words.
      const wrap = (m) => {
        const t = inner.trim();
        if (!t) return inner;
        return inner.match(/^\s*/)[0] + m + t + m + inner.match(/\s*$/)[0];
      };
      if (tag === 'strong' || tag === 'b') out += wrap('**');
      else if (tag === 'em' || tag === 'i') out += wrap('*');
      else if (tag === 'code') out += '`' + inner + '`';
      else if (tag === 'a') {
        const u = unwrapLink(c.getAttribute('href'));
        if (u && !/linkedin\.com\//.test(u)) { links.add(u); out += `[${inner.trim() || u}](${u})`; }
        else out += inner;
      } else out += inner;
    });
    return out;
  }

  function tidy(md) {
    return md.replace(/ /g, ' ')
      .split('\n').map((l) => l.replace(/[ \t]+/g, ' ').trim()).join('\n')
      .replace(/\n{3,}/g, '\n\n').trim();
  }

  function root() {
    return document.querySelector('article');
  }

  function inHeader(el) {
    return !!el.closest('header, .reader-author-info__content, .artdeco-entity-lockup');
  }

  function blocksOf(a, links) {
    const blocks = [];
    const sel = 'h2, h3, h4, p, ul, ol, blockquote, pre, figure';
    a.querySelectorAll(sel).forEach((el) => {
      if (inHeader(el)) return;
      // nested matches (a <p> inside a <blockquote> or <li>) belong to their parent block
      const parent = el.parentElement && el.parentElement.closest(sel);
      if (parent && a.contains(parent) && !inHeader(parent)) return;
      const tag = el.tagName.toLowerCase();
      if (tag === 'figure') {
        const img = el.querySelector('img');
        const src = img ? bestSrc(img) : '';
        if (!src || !ATTACHMENT.test(src) || /article-cover_image/.test(src)) return;
        blocks.push({ type: 'image', src, alt: clean(img.getAttribute('alt')),
                      caption: clean((el.querySelector('figcaption') || {}).textContent) });
      } else if (tag === 'ul' || tag === 'ol') {
        const items = Array.from(el.children).filter((li) => li.tagName === 'LI')
          .map((li) => tidy(inline(li, links))).filter(Boolean);
        if (items.length) blocks.push({ type: 'list', ordered: tag === 'ol', items });
      } else if (tag === 'pre') {
        blocks.push({ type: 'code', text: el.textContent.replace(/\n+$/, '') });
      } else {
        const text = tidy(inline(el, links));
        if (!text) return;
        if (tag === 'p') blocks.push({ type: 'paragraph', text });
        else if (tag === 'blockquote') blocks.push({ type: 'quote', text });
        else blocks.push({ type: 'heading', level: parseInt(tag[1], 10), text });
      }
    });
    return blocks;
  }

  // Counts live outside <article>, in the social bar after it. Read the
  // aria-labels ("37 reactions", "4 comments on X's post"), not the visible
  // text, which renders as a bare "37" with no unit.
  function metricsOf() {
    const bar = document.querySelector('.social-details-social-counts');
    if (!bar) return { reactions: null, comments: null, reposts: null };
    const num = (re) => {
      for (const el of bar.querySelectorAll('[aria-label]')) {
        const m = (el.getAttribute('aria-label') || '').replace(/,/g, '').match(re);
        if (m) return parseInt(m[1], 10);
      }
      return null;
    };
    return { reactions: num(/^(\d+)\s+reactions?/i),
             comments: num(/^(\d+)\s+comments?/i),
             reposts: num(/^(\d+)\s+reposts?/i) };
  }

  function extract() {
    const a = root();
    if (!a) return { error: 'no <article> on page' };
    const links = new Set();
    const coverImg = a.querySelector('img.reader-cover-image__img, figure img[src*="article-cover_image"]');
    const author = a.querySelector('.reader-author-info__content');
    const authorLink = author && author.querySelector('a[href*="/in/"], a[href*="/company/"]');
    const nameEl = author && author.querySelector('h2, h3');
    const headlineEl = author && author.querySelector('.lt-line-clamp, .reader-author-info__author-lockup--flex + *');
    const timeEl = a.querySelector('time');
    const titleEl = a.querySelector('h1');
    return {
      title: clean(titleEl && titleEl.textContent),
      author_name: clean(nameEl && nameEl.textContent),
      author_headline: clean(headlineEl && headlineEl.textContent),
      author_url: authorLink ? new URL(authorLink.getAttribute('href'), 'https://www.linkedin.com').href.replace(/\/$/, '') : '',
      published_label: clean(timeEl && timeEl.textContent),
      cover: coverImg ? bestSrc(coverImg) : '',
      blocks: blocksOf(a, links),
      metrics: metricsOf(),
      links: Array.from(links),
    };
  }

  function imagesPending() {
    const a = root();
    if (!a) return 0;
    return Array.from(a.querySelectorAll('figure img')).filter((i) => !ATTACHMENT.test(bestSrc(i))
      && !/profile-displayphoto/.test(bestSrc(i))).length;
  }

  window.__liArticle = { extract, imagesPending, unwrapLink, bestSrc };
})();
