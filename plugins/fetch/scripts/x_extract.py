"""Python driver around the CANONICAL extraction logic.

This module contains NO extraction JS of its own. The DOM selectors, thread
walk-back, and thread detection live in ONE place —
`skills/x-post/references/extraction.js` — which the `download:x-post` skill
also uses. This module loads that file and calls its functions, so any
iteration on the extraction benefits both x-post and x-account. Navigation,
scrolling, and Snowflake clustering are driver concerns and stay here (the
clustering reuses the shared, tested x_threads module).
"""
import os
import time

from x_snowflake import id_sort_key
from x_threads import cluster

# The single source of truth, resolved relative to this file's plugin.
_EXTRACTION_JS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "skills", "x-post", "references", "extraction.js"))
with open(_EXTRACTION_JS_PATH) as _f:
    _EXTRACTION_JS = _f.read()


def _ensure(page):
    """Make sure window.__xExtract is defined on the current document by
    injecting the canonical extraction.js (idempotent per navigation)."""
    if page.evaluate("typeof window.__xExtract") != "object":
        page.evaluate(_EXTRACTION_JS)


def _normalize(d, handle, status_id):
    d = d or {}
    return {
        "status_id": status_id,
        "handle": d.get("handle") or handle,
        "author_name": d.get("displayName") or handle,
        "content": d.get("content") or "",
        "timestamp": d.get("timestamp") or "",
        "metrics": d.get("metrics") or {"likes": 0, "reposts": 0, "views": 0, "replies": 0},
        "images": d.get("images") or [],
        "expected_images": d.get("expectedImageCount") or 0,
    }


def extract_post(page, handle, status_id, settle=1.2):
    """Navigate to one post and extract it via the shared extractFocal()."""
    page.goto(f"https://x.com/{handle}/status/{status_id}", timeout=45000)
    page.wait_for_selector("article", timeout=15000)
    time.sleep(settle)
    _ensure(page)
    return _normalize(page.evaluate("window.__xExtract.extractFocal()"), handle, status_id)


def find_root(page, focal_id, handle):
    """Shared findRoot() — rootId of the focal post's thread."""
    _ensure(page)
    r = page.evaluate("([f,h]) => window.__xExtract.findRoot(f,h)", [focal_id, handle]) or {}
    return r.get("rootId") or focal_id


def detect_thread_members(page, handle, root_id, scrolls=10):
    """Scroll the root page, run shared detectThreadMembers(), then keep the
    genuine contiguous self-reply chain that contains the root (x_threads)."""
    prev = 0
    for i in range(scrolls):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(1.0)
        cur = page.evaluate("document.querySelectorAll('article').length")
        if cur == prev and i > 1:
            break
        prev = cur
    _ensure(page)
    candidates = page.evaluate("h => window.__xExtract.detectThreadMembers(h)", handle) or []
    recs = [{"status_id": c["statusId"], "is_reply_to_other": bool(c.get("isReplyToOther"))}
            for c in candidates]
    for grp in cluster(recs):
        if root_id in grp:
            return sorted(grp, key=id_sort_key)
    return [root_id]


def extract_thread_here(page, handle, focal_id, scrolls=6):
    """Extract the whole thread from the CONVERSATION PAGE we are already on
    (after a human click-in), via the shared extractAllByAuthor — no per-post
    URL navigation. Returns {root_id, is_thread, posts:[normalized, chrono]}."""
    _ensure(page)
    root_id = find_root(page, focal_id, handle)
    for _ in range(scrolls):
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        time.sleep(0.8)
    _ensure(page)
    allposts = page.evaluate("h => window.__xExtract.extractAllByAuthor(h)", handle) or []
    by_id = {p["statusId"]: p for p in allposts}
    recs = [{"status_id": p["statusId"], "is_reply_to_other": bool(p.get("isReplyToOther"))}
            for p in allposts]
    if root_id not in by_id:
        recs.append({"status_id": root_id, "is_reply_to_other": False})
    member_ids = [root_id]
    for grp in cluster(recs):
        if root_id in grp:
            member_ids = sorted(grp, key=id_sort_key)
            break
    posts = [_normalize(by_id[sid], handle, sid) for sid in member_ids
             if by_id.get(sid) and (by_id[sid].get("content") or "").strip()]
    if not posts and by_id.get(root_id):
        posts = [_normalize(by_id[root_id], handle, root_id)]
    return {"root_id": root_id, "is_thread": len(posts) > 1, "posts": posts}


def find_article(page, status_id):
    """Return the timeline <article> element handle for status_id, or None."""
    for h in page.query_selector_all("article"):
        try:
            sid = page.evaluate("(a) => (window.__xExtract ? window.__xExtract.statusIdOf(a) : '')", h)
        except Exception:
            sid = ""
        if sid == status_id:
            return h
    return None


def open_post_in_new_tab(context, page, status_id, modifier="Meta"):
    """Human-style: Cmd/Ctrl+Click the post so it opens in a NEW TAB. Returns
    the new Playwright page (caller extracts, then closes it), or None. The
    original profile tab keeps its scroll position."""
    art = find_article(page, status_id)
    if not art:
        return None
    art.scroll_into_view_if_needed()
    time.sleep(0.3)
    target = art.query_selector('[data-testid="tweetText"]') or \
        art.query_selector('a[href*="/status/"]') or art
    with context.expect_page() as ev:
        target.click(modifiers=[modifier])
    tab = ev.value
    tab.wait_for_selector("article", timeout=15000)
    return tab


def click_into_post(page, status_id):
    """Human-style: click the timeline article for status_id to open it.
    Returns True on success. No page.goto — a real user clicks."""
    for h in page.query_selector_all("article"):
        try:
            sid = page.evaluate("(a) => (window.__xExtract ? window.__xExtract.statusIdOf(a) : '')", h)
        except Exception:
            sid = ""
        if sid == status_id:
            h.scroll_into_view_if_needed()
            time.sleep(0.4)
            # click the post's text if present, else the article body
            target = h.query_selector('[data-testid="tweetText"]') or h
            target.click()
            return True
    return False


def extract_thread(page, handle, focal_id):
    """Walk to the root, detect members, extract each. Returns
    {root_id, is_thread, posts:[normalized dicts, chronological]}."""
    page.goto(f"https://x.com/{handle}/status/{focal_id}", timeout=45000)
    page.wait_for_selector("article", timeout=15000)
    time.sleep(1.2)
    root_id = find_root(page, focal_id, handle)

    page.goto(f"https://x.com/{handle}/status/{root_id}", timeout=45000)
    page.wait_for_selector("article", timeout=15000)
    time.sleep(1.2)
    members = detect_thread_members(page, handle, root_id)

    posts = [extract_post(page, handle, sid) for sid in members]
    posts = [p for p in posts if (p["content"] or "").strip()]
    if not posts:
        posts = [_normalize(None, handle, root_id)]
    return {"root_id": root_id, "is_thread": len(posts) > 1, "posts": posts}
