"""x-post DOWNLOAD unit — the single reusable capability.

Given a page that is ON a post (e.g. a URL opened directly, or a post opened in
a new tab by the x-account iterator), capture the whole post/thread to a
Markdown note (+ images). This is THE download logic; the x-account iterator
does not reimplement any of it — it opens a tab and calls
download_open_post(). Uses the shared extraction (x_extract -> extraction.js)
and the shared renderer (x_render) and media downloader.

Two ways in:

* **As a library** — `download_open_post(page, handle, out_dir, day)`, given a
  page already on the post. This is what the x-account iterator calls.
* **As a CLI** — `python3 xpost_download.py <url> [out_dir]`, which opens the
  gstack browser (headed, carrying the user's logins) via
  `_browse.sync_browse_page()`, walks back to the thread root, and captures.
  This is what the `fetch:x-post` skill runs.

The CLI never launches its own browser. A freshly launched one is logged out,
and X then returns a login wall that reads as a *short post* rather than an
error — a capture that looks fine and is empty.
"""
import datetime
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import x_extract
from x_render import render_note, slugify, note_filename
from x_media import media_filename

_STATUS_URL = re.compile(
    r"^https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)")


def status_id_from_url(url):
    m = re.search(r"/status/(\d+)", url or "")
    return m.group(1) if m else None


def _download_media(urls, att_dir, handle, sid):
    files = []
    for i, u in enumerate(urls[:4], 1):
        fn = media_filename(handle, sid, i)
        fp = os.path.join(att_dir, fn)
        subprocess.run(["curl", "-L", "-s", "-o", fp, u], timeout=30, check=False)
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            files.append(fn)
    return files


def download_open_post(page, handle, out_dir, day, download_media=True):
    """Capture the post/thread the page is currently on. Writes one .md note
    (thread -> numbered sections) plus images, and returns a summary dict."""
    focal = status_id_from_url(page.url)
    if not focal:
        return {"error": "no status id in url", "url": page.url}

    th = x_extract.extract_thread_here(page, handle, focal)
    if not th["posts"]:
        return {"error": "no content", "status_id": focal}

    root = th["posts"][0]
    posts_dir = os.path.join(out_dir, handle, "posts")
    att_dir = os.path.join(out_dir, handle, "attachments")
    os.makedirs(posts_dir, exist_ok=True)
    os.makedirs(att_dir, exist_ok=True)

    sections, media = [], 0
    for pst in th["posts"]:
        imgs = _download_media(pst["images"], att_dir, handle, pst["status_id"]) if download_media else []
        media += len(imgs)
        sections.append({"content": pst["content"], "image_files": imgs})

    date = (root["timestamp"] or "")[:10] or day
    post = {
        "status_id": root["status_id"], "handle": handle, "author_name": root["author_name"],
        "date": date, "date_captured": day,
        "post_type": "thread" if th["is_thread"] else "post",
        "thread_length": len(th["posts"]), "metrics": root["metrics"], "media": media,
        "content": root["content"], "image_files": sections[0]["image_files"], "sections": sections,
        "video": root.get("video"),
    }
    # Announce video on stderr only. `OUTPUT_FILE:` must remain the sole
    # machine-parseable line on stdout; a second marker there would break every
    # caller that reads the last stdout line.
    video = root.get("video") or {}
    if video.get("present") and not video.get("isGif"):
        print(f"VIDEO_DETECTED:https://x.com/{handle}/status/{root['status_id']}"
              f"\t{video.get('seconds') or ''}", file=sys.stderr)

    slug = slugify(root["content"] or root["status_id"]) or root["status_id"]
    fname = note_filename(date, handle, slug)
    with open(os.path.join(posts_dir, fname), "w") as f:
        f.write(render_note(post))

    return {
        "note": f"posts/{fname}", "fname": fname, "status_id": root["status_id"],
        "root_id": th["root_id"], "is_thread": th["is_thread"],
        "post_count": len(th["posts"]), "media": media,
        "author_name": root["author_name"], "date": date,
        "member_ids": [p["status_id"] for p in th["posts"]],
    }


def parse_status_url(url):
    """`(handle, status_id)` for an X/Twitter status URL, or `(None, None)`.

    Only `x.com` / `twitter.com` `/{handle}/status/{id}` URLs are accepted;
    anything else (a profile, a search, a bare id) returns `(None, None)` so
    the caller can refuse instead of navigating somewhere meaningless.
    """
    m = _STATUS_URL.match((url or "").strip())
    return (m.group(1), m.group(2)) if m else (None, None)


def download_url(page, url, out_dir, day):
    """Capture the post at `url`, walking back to the thread root first.

    A shared link is frequently NOT the first post of its thread — people copy
    a middle or final post. `x_extract.find_root` reads the ancestor articles
    X renders ABOVE the focal one; when they exist, the capture restarts from
    the root so the note is the whole thread in order rather than its tail.
    """
    handle, focal_id = parse_status_url(url)
    if not handle:
        return {"error": f"not an X status URL: {url!r}"}

    page.goto(url)
    page.wait_for_selector("article", timeout=15000)
    page.wait_for_timeout(1200)

    root_id = x_extract.find_root(page, focal_id, handle)
    if root_id != focal_id:
        print(f"mid-thread link: root is {root_id}", file=sys.stderr)
        page.goto(f"https://x.com/{handle}/status/{root_id}")
        page.wait_for_selector("article", timeout=15000)
        page.wait_for_timeout(1200)

    return download_open_post(page, handle, out_dir, day)


def main(argv):
    if not argv:
        print("usage: xpost_download.py <x-status-url> [out_dir]", file=sys.stderr)
        return 2

    url = argv[0]
    out_dir = os.path.abspath(argv[1]) if len(argv) > 1 else os.getcwd()
    day = datetime.date.today().isoformat()

    from _browse import sync_browse_page   # imported here so --help needs no browser

    with sync_browse_page() as page:
        result = download_url(page, url, out_dir, day)

    # No OUTPUT_FILE marker on failure. Emitting one anyway would send the
    # caller off to summarise a note that was never written, or an empty one.
    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1

    handle, _ = parse_status_url(url)
    note_path = os.path.join(out_dir, handle, result["note"])
    kind = "thread" if result["is_thread"] else "post"
    print(f"captured {kind}: {result['post_count']} post(s), "
          f"{result['media']} image(s) -> {note_path}", file=sys.stderr)
    print(f"OUTPUT_FILE:{note_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
