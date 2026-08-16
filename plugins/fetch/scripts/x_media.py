"""Governed media download (Task 13, design §10.1, §15.4).

`download_all` fetches post images through an `asyncio.Semaphore` cap so
media traffic is throttled rather than bursty (design §8.2 W5) — a burst of
simultaneous image requests is not human-plausible traffic. Session-level
pacing (dwell times, breaks) lives in `x_session.py`; this module only owns
the concurrency cap, the `name=large` upgrade, and the on-disk filename.
"""

import asyncio
import os
import re

_NAME_PARAM = re.compile(r"name=\w+")


def media_filename(handle: str, status_id: str, index: int) -> str:
    """Filename for the Nth image of a post (design §10.2, §15.4).

    `"<handle-lowercased>-<status_id>-<index>.jpg"`.
    """
    return f"{handle.lower()}-{status_id}-{index}.jpg"


def _upgrade_to_large(url: str) -> str:
    """Force the `name=` query param to `large` for full-resolution media.

    Mirrors the existing x-post extraction logic
    (`img.src.replace(/name=\\w+/, 'name=large')`, design §15.4). URLs
    without a `name=` param are returned unchanged.
    """
    if _NAME_PARAM.search(url):
        return _NAME_PARAM.sub("name=large", url)
    return url


async def _download_one(url: str, dest_path: str, semaphore: asyncio.Semaphore) -> bool:
    """Fetch one image via curl under the semaphore. True on success."""
    async with semaphore:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-L", "-s", "-o", dest_path, url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        returncode = await proc.wait()
    return returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 0


async def download_all(urls_by_post: dict, out_dir: str, max_concurrency: int = 2) -> dict:
    """Download every image for every post, capped at `max_concurrency` concurrent fetches.

    Args:
        urls_by_post: `{status_id: {"handle": str, "urls": [image_url, ...]}}`.
        out_dir: directory images are written into (created if missing).
        max_concurrency: hard cap on simultaneous downloads (design §8.2 W5).

    Returns:
        `{status_id: [filename, ...]}` — only successfully downloaded files.
        A failed download is dropped silently; the caller reports partial
        media (see module docstring — no retry/backoff here).
    """
    os.makedirs(out_dir, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrency)

    jobs = []  # (status_id, index, filename, coroutine)
    for status_id, post in urls_by_post.items():
        handle = post["handle"]
        for index, url in enumerate(post["urls"], start=1):
            filename = media_filename(handle, status_id, index)
            dest_path = os.path.join(out_dir, filename)
            large_url = _upgrade_to_large(url)
            jobs.append((status_id, filename, _download_one(large_url, dest_path, semaphore)))

    results = await asyncio.gather(*(job[2] for job in jobs))

    downloaded: dict = {}
    for (status_id, filename, _), ok in zip(jobs, results):
        if ok:
            downloaded.setdefault(status_id, []).append(filename)
    return downloaded
