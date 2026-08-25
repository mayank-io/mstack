#!/usr/bin/env python3
"""
Scribd Document Extractor
Downloads all page images from a Scribd document via its embed view.

Rendering goes through _browse.browse_page(), which drives the gstack browser in
HEADED mode — the one attached to the user's real Chrome, holding their logins.
Do not swap this for Playwright or any freshly launched browser: a logged-out
profile gets Scribd's paywall/login view, which renders as a short, valid-looking
page, so a gated capture is indistinguishable from a short document.

Usage: python3 scribd_extractor.py <scribd_url> [output_dir]
Example: python3 scribd_extractor.py "https://www.scribd.com/document/123456789/Sample-Document-Title" ./output
"""

import asyncio
import re
import sys
import os
import httpx
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browse import browse_page


def to_embed_url(url: str) -> str:
    """Convert any Scribd URL to its embed URL."""
    match = re.search(r"scribd\.com/(?:document|doc|embeds)/(\d+)", url)
    if not match:
        print(f"Error: could not extract document ID from URL: {url}", flush=True)
        sys.exit(1)
    doc_id = match.group(1)
    return f"https://www.scribd.com/embeds/{doc_id}/content"


async def get_total_pages(page) -> int:
    """Extract total page count from the embed toolbar."""
    count = await page.evaluate("""
        () => {
            // Look for "/ NNN" text in the toolbar
            const els = document.querySelectorAll('.toolbar *');
            for (const el of els) {
                const text = el.textContent.trim();
                const m = text.match(/\\/\\s*(\\d+)/);
                if (m) return parseInt(m[1]);
            }
            // Fallback: look anywhere in the page for page count patterns
            const body = document.body.innerText;
            const m = body.match(/of\\s+(\\d+)/i) || body.match(/\\/\\s*(\\d+)/);
            if (m) return parseInt(m[1]);
            return 0;
        }
    """)
    # `or 0`: an unparseable/empty result must degrade to the "unknown count"
    # branch the caller already handles, not blow up on `None > 0` later.
    return count or 0


def extract_page_num(url: str) -> int:
    """Extract page number from a Scribd image URL like .../images/42-hash.jpg"""
    m = re.search(r"/images/(\d+)-", url)
    return int(m.group(1)) if m else 0


async def collect_image_urls(page):
    """Collect all loaded page image URLs, sorted by page number."""
    return await page.evaluate("""
        () => {
            const imgs = document.querySelectorAll('img.absimg');
            return Array.from(imgs)
                .map(img => img.src)
                .filter(src => src && src.includes('/images/'))
                .sort((a, b) => {
                    const na = parseInt((a.match(/\\/images\\/(\\d+)-/) || [])[1] || '0');
                    const nb = parseInt((b.match(/\\/images\\/(\\d+)-/) || [])[1] || '0');
                    return na - nb;
                });
        }
    """)


async def extract_scribd_images(url: str, output_dir: str = "./scribd_output"):
    embed_url = to_embed_url(url)
    os.makedirs(output_dir, exist_ok=True)

    # gstack browser — never headless (see _browse.py)
    async with browse_page() as page:
        print(f"Navigating to {embed_url}", flush=True)
        await page.goto(embed_url, wait_until="networkidle")
        await page.wait_for_selector(".document_scroller", timeout=15000)

        total_pages = await get_total_pages(page)
        if total_pages == 0:
            print("Warning: could not detect total page count, will collect what we can", flush=True)

        print(f"Total pages: {total_pages}", flush=True)

        # Scroll through the document to trigger lazy loading
        print("Scrolling to trigger lazy loading...", flush=True)
        scroll_height = await page.evaluate(
            "document.querySelector('.document_scroller').scrollHeight"
        )
        steps = 60
        for i in range(1, steps + 1):
            pos = int((i / steps) * scroll_height)
            await page.evaluate(
                f"document.querySelector('.document_scroller').scrollTop = {pos}"
            )
            await asyncio.sleep(0.2)

        # Jump to the end
        await page.evaluate(
            "document.querySelector('.document_scroller').scrollTop = "
            "document.querySelector('.document_scroller').scrollHeight"
        )
        await asyncio.sleep(2)

        urls = await collect_image_urls(page)
        print(f"Found {len(urls)} pages after initial scroll", flush=True)

        # Targeted scroll for missing pages
        if total_pages > 0:
            page_height = scroll_height / total_pages
            loaded_nums = {extract_page_num(u) for u in urls} - {0}

            missing = [pg for pg in range(1, total_pages + 1) if pg not in loaded_nums]

            if missing:
                print(f"Scrolling to {len(missing)} missing pages...", flush=True)
                for pg in missing:
                    pos = int((pg - 1) * page_height)
                    await page.evaluate(
                        f"document.querySelector('.document_scroller').scrollTop = {pos}"
                    )
                    await asyncio.sleep(0.15)
                await asyncio.sleep(3)

                # Re-read scroll height in case it changed
                scroll_height = await page.evaluate(
                    "document.querySelector('.document_scroller').scrollHeight"
                )
                page_height = scroll_height / total_pages

                # Second targeted pass for still-missing pages
                urls = await collect_image_urls(page)
                loaded_nums = {extract_page_num(u) for u in urls} - {0}

                still_missing = [pg for pg in range(1, total_pages + 1) if pg not in loaded_nums]
                if still_missing:
                    print(f"Second pass for {len(still_missing)} still-missing pages...", flush=True)
                    for pg in still_missing:
                        pos = int((pg - 1) * page_height)
                        await page.evaluate(
                            f"document.querySelector('.document_scroller').scrollTop = {pos}"
                        )
                        await asyncio.sleep(0.3)
                    await asyncio.sleep(3)
                    urls = await collect_image_urls(page)

                print(f"Found {len(urls)} pages after targeted scroll", flush=True)

        # Final missing page report
        if total_pages > 0:
            loaded_nums = {extract_page_num(u) for u in urls} - {0}
            still_missing = [pg for pg in range(1, total_pages + 1) if pg not in loaded_nums]
            if still_missing:
                print(f"Warning: could not load pages {still_missing}", flush=True)


    # Download all images
    print(f"Downloading {len(urls)} images to {output_dir}...", flush=True)
    async with httpx.AsyncClient(timeout=30) as client:
        for img_url in urls:
            page_num = extract_page_num(img_url)
            filename = os.path.join(output_dir, f"page_{page_num:04d}.jpg")
            if os.path.exists(filename):
                continue
            try:
                r = await client.get(img_url)
                r.raise_for_status()
                with open(filename, "wb") as f:
                    f.write(r.content)
                downloaded_so_far = len([f for f in os.listdir(output_dir) if f.endswith(".jpg")])
                print(f"  Saved page {page_num} ({downloaded_so_far}/{len(urls)})", flush=True)
            except Exception as e:
                print(f"  Failed page {page_num}: {e}", flush=True)

    downloaded = len([f for f in os.listdir(output_dir) if f.endswith(".jpg")])
    print(f"Done. {downloaded} images saved to {output_dir}/", flush=True)

    # Never report success on an empty capture. Every page can fail — the
    # embed 404s, the document is gated — and the loop above swallows each
    # failure to keep going. Emitting OUTPUT_DIR then tells the caller to go
    # build a note out of an empty directory.
    if downloaded == 0:
        print(f"ERROR: no pages were downloaded from {url}. See the per-page "
              f"failures above. No OUTPUT_DIR marker is emitted, because a "
              f"caller chaining on it would summarise an empty directory.",
              file=sys.stderr)
        sys.exit(3)
    if downloaded < len(urls):
        print(f"WARNING: {len(urls) - downloaded} of {len(urls)} pages failed. "
              f"The capture is INCOMPLETE — say so rather than presenting it "
              f"as the whole document.", file=sys.stderr)

    # contract: final stdout line is machine-parseable
    print(f"OUTPUT_DIR:{output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scribd_extractor.py <scribd_url> [output_dir]")
        sys.exit(1)
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./scribd_output"
    asyncio.run(extract_scribd_images(url, output_dir))
