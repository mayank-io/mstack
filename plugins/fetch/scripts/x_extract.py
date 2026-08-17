"""x-post extraction driver (Python side of the download unit).

Given a Playwright page that is ON a post's conversation page, extract the
whole thread. The DOM logic is the single-source `extraction.js` (shared with
the x-post SKILL); this module only orchestrates (root walk-back, scroll,
Snowflake clustering via the tested x_threads). It has NO knowledge of profile
timelines or iteration — that is the x-account layer's job, which calls this.
"""
import os
import time

from x_snowflake import id_sort_key
from x_threads import cluster

_EXTRACTION_JS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "skills", "x-post", "references", "extraction.js"))
with open(_EXTRACTION_JS_PATH) as _f:
    _EXTRACTION_JS = _f.read()


def _ensure(page):
    """Inject the canonical extraction.js if not already present on this doc."""
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


def find_root(page, focal_id, handle):
    """Shared findRoot() — rootId of the focal post's thread."""
    _ensure(page)
    r = page.evaluate("([f,h]) => window.__xExtract.findRoot(f,h)", [focal_id, handle]) or {}
    return r.get("rootId") or focal_id


def collect_thread_posts(page, handle, root_id, scrolls=14):
    """Collect the genuine thread's posts (full content) from the current
    conversation page. Scrolls from the TOP and unions same-author articles on
    EVERY tick, because the thread posts sit right under the root and virtualize
    out of the DOM as you scroll — collecting only after scrolling loses the
    whole thread. Returns full post dicts, chronological."""
    _ensure(page)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1.0)
    collected = {}   # status_id -> extractArticle() dict (first sighting wins)
    stable = 0
    for _ in range(scrolls):
        _ensure(page)
        for pd in (page.evaluate("h => window.__xExtract.extractAllByAuthor(h)", handle) or []):
            sid = pd.get("statusId")
            if sid and sid not in collected and (pd.get("content") or "").strip():
                collected[sid] = pd
        before = page.evaluate("window.scrollY")
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight*0.85))")
        time.sleep(0.9)
        if page.evaluate("window.scrollY") == before:
            stable += 1
            if stable >= 2:
                break

    recs = [{"status_id": sid, "is_reply_to_other": bool(collected[sid].get("isReplyToOther"))}
            for sid in collected]
    if root_id not in collected:
        recs.append({"status_id": root_id, "is_reply_to_other": False})
    member_ids = [root_id]
    for grp in cluster(recs):
        if root_id in grp:
            member_ids = sorted(grp, key=id_sort_key)
            break
    posts = [_normalize(collected[sid], handle, sid) for sid in member_ids if sid in collected]
    if not posts and root_id in collected:
        posts = [_normalize(collected[root_id], handle, root_id)]
    return posts


def extract_thread_here(page, handle, focal_id):
    """The page is ALREADY ON the post (e.g. opened in a new tab). Walk to the
    root and extract the whole thread. Returns {root_id, is_thread, posts}."""
    _ensure(page)
    root_id = find_root(page, focal_id, handle)
    posts = collect_thread_posts(page, handle, root_id)
    return {"root_id": root_id, "is_thread": len(posts) > 1, "posts": posts}


def extract_thread(page, handle, focal_id):
    """Direct-URL capture (e.g. download:x-post given a single URL): navigate to
    the post, walk to the root, extract the whole thread."""
    page.goto(f"https://x.com/{handle}/status/{focal_id}", timeout=45000)
    page.wait_for_selector("article", timeout=15000)
    time.sleep(1.2)
    root_id = find_root(page, focal_id, handle)
    if root_id != focal_id:
        page.goto(f"https://x.com/{handle}/status/{root_id}", timeout=45000)
        page.wait_for_selector("article", timeout=15000)
        time.sleep(1.2)
    posts = collect_thread_posts(page, handle, root_id)
    return {"root_id": root_id, "is_thread": len(posts) > 1, "posts": posts}
