"""x-post DOWNLOAD unit — the single reusable capability.

Given a Playwright page that is ON a post (e.g. a URL opened directly, or a
post opened in a new tab by the x-account iterator), capture the whole
post/thread to a Markdown note (+ images). This is THE download logic; the
x-account plugin does not reimplement any of it — it opens a tab and calls
download_open_post(). Uses the shared extraction (x_extract -> extraction.js)
and the shared renderer (x_render) and media downloader.
"""
import os
import re
import subprocess

import x_extract
from x_render import render_note, slugify, note_filename
from x_media import media_filename


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
    }
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
