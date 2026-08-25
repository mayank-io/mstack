#!/usr/bin/env python3
"""
Notion Site Downloader
Downloads all pages from a public Notion site as Markdown files.

Rendering goes through _browse.browse_page(), which drives the gstack browser in
HEADED mode — the one attached to the user's real Chrome, holding their logins.
Do not swap this for Playwright or any freshly launched browser: a logged-out
profile returns a Notion login wall that renders as a short, valid-looking page,
so an authwalled capture is indistinguishable from a thin one.
"""

import asyncio
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _browse import browse_page
import httpx


class NotionDownloader:
    def __init__(self, base_url: str, output_dir: str, test_mode: bool = False):
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.attachments_dir = self.output_dir / "attachments"
        self.test_mode = test_mode

        # Track visited pages and their clean names
        self.visited_urls: set[str] = set()
        self.page_map: dict[str, dict] = {}  # url -> {title, filename, notion_id}
        self.page_order: list[str] = []  # ordered list of URLs

        # Parse base domain
        parsed = urlparse(base_url)
        self.base_domain = parsed.netloc

    def normalize_url(self, url: str) -> str:
        """Normalize URL by removing query params and fragments."""
        parsed = urlparse(url)
        # Keep only path, normalize it
        path = parsed.path.rstrip('/')
        if not path:
            path = '/'
        return f"{parsed.scheme}://{parsed.netloc}{path}"

    def is_internal_link(self, url: str) -> bool:
        """Check if URL is internal to the Notion site."""
        parsed = urlparse(url)
        # Relative URLs
        if not parsed.netloc:
            return True
        # Same domain
        return parsed.netloc == self.base_domain

    def extract_notion_id(self, url: str) -> str | None:
        """Extract Notion page ID from URL."""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        if not path:
            return None
        # Notion IDs are the last segment after the last hyphen
        match = re.search(r'-([a-f0-9]{32})$', path)
        if match:
            return match.group(1)
        # Or the path might just be the ID
        if re.match(r'^[a-f0-9]{32}$', path):
            return path
        return None

    def clean_filename(self, title: str, index: int) -> str:
        """Create a clean filename from title."""
        # Remove emoji and special characters
        clean = re.sub(r'[^\w\s-]', '', title)
        # Replace spaces with hyphens
        clean = re.sub(r'\s+', '-', clean.strip())
        # Truncate if too long
        if len(clean) > 50:
            clean = clean[:50]
        return f"{index:02d}-{clean}"

    async def download_image(self, img_url: str, page_url: str) -> str | None:
        """Download an image and return local path."""
        try:
            # Handle relative URLs
            if not img_url.startswith('http'):
                img_url = urljoin(page_url, img_url)

            # Skip data URLs
            if img_url.startswith('data:'):
                return None

            # Create attachments directory
            self.attachments_dir.mkdir(parents=True, exist_ok=True)

            # Generate filename from URL hash
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:12]
            ext = Path(urlparse(img_url).path).suffix or '.png'
            filename = f"img-{url_hash}{ext}"
            filepath = self.attachments_dir / filename

            # Download if not exists
            if not filepath.exists():
                async with httpx.AsyncClient() as client:
                    response = await client.get(img_url, follow_redirects=True)
                    if response.status_code == 200:
                        filepath.write_bytes(response.content)
                        print(f"  Downloaded: {filename}")
                    else:
                        print(f"  Failed to download image: {img_url}")
                        return None

            return f"attachments/{filename}"
        except Exception as e:
            print(f"  Error downloading image: {e}")
            return None

    async def extract_content(self, page, url: str) -> dict:
        """Extract page content as markdown using JavaScript for cleaner extraction."""
        # Wait for main content to load
        try:
            await page.wait_for_selector('main', timeout=10000)
        except Exception:
            pass

        await asyncio.sleep(2)  # Allow dynamic content to load

        # Extract title (h1 preferred, document.title as fallback)
        meta = await page.evaluate(
            "JSON.stringify({t: document.title || '', "
            "h1: (document.querySelector('h1') || {}).innerText || ''})"
        )
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        meta = meta or {}
        title = (meta.get('t') or '').replace(' | Notion', '').strip()
        if meta.get('h1'):
            title = meta['h1'].strip()

        # Use JavaScript to extract structured content from Notion blocks
        content = await page.evaluate('''() => {
            const results = [];
            const seen = new Set();

            // Find the main content area
            const main = document.querySelector('main') ||
                        document.querySelector('[class*="notion-page-content"]') ||
                        document.body;

            // Get all block elements with data-block-id (Notion's content blocks)
            const blocks = main.querySelectorAll('[data-block-id]');

            blocks.forEach(block => {
                const blockId = block.getAttribute('data-block-id');
                if (seen.has(blockId)) return;
                seen.add(blockId);

                // Skip if this block is nested inside another block we've processed
                const parent = block.parentElement?.closest('[data-block-id]');
                if (parent && seen.has(parent.getAttribute('data-block-id'))) {
                    // Only skip if parent has same text
                    if (parent.innerText.includes(block.innerText)) return;
                }

                const text = block.innerText?.trim();
                if (!text || text.length < 2) return;

                // Detect block type from classes
                const classes = block.className.toLowerCase();

                let type = 'paragraph';
                if (classes.includes('header') || classes.includes('heading')) {
                    if (classes.includes('sub_sub') || classes.includes('h3')) type = 'h3';
                    else if (classes.includes('sub') || classes.includes('h2')) type = 'h2';
                    else type = 'h1';
                } else if (classes.includes('callout')) {
                    type = 'callout';
                } else if (classes.includes('bulleted') || classes.includes('list')) {
                    type = 'list';
                } else if (classes.includes('numbered')) {
                    type = 'numbered';
                } else if (classes.includes('toggle')) {
                    type = 'toggle';
                } else if (classes.includes('divider')) {
                    type = 'divider';
                }

                results.push({ type, text, blockId });
            });

            return results;
        }''')

        # Convert to markdown
        content_parts = []
        seen_texts = set()

        for block in (content or []):
            text = block['text']

            # Deduplicate by normalized text
            normalized = ' '.join(text.split())[:100]  # First 100 chars
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)

            block_type = block['type']

            if block_type == 'h1':
                content_parts.append(f"\n## {text}\n")
            elif block_type == 'h2':
                content_parts.append(f"\n### {text}\n")
            elif block_type == 'h3':
                content_parts.append(f"\n#### {text}\n")
            elif block_type == 'callout':
                # Format callout as blockquote
                lines = text.split('\n')
                content_parts.append('\n> ' + '\n> '.join(lines) + '\n')
            elif block_type == 'list':
                for line in text.split('\n'):
                    if line.strip():
                        content_parts.append(f"- {line.strip()}")
            elif block_type == 'numbered':
                for i, line in enumerate(text.split('\n'), 1):
                    if line.strip():
                        content_parts.append(f"{i}. {line.strip()}")
            elif block_type == 'divider':
                content_parts.append("\n---\n")
            else:
                # Regular paragraph - skip very short or duplicate-looking content
                if len(text) > 10:
                    content_parts.append(text)

        # Fallback if JS extraction fails
        if not content_parts:
            try:
                body_text = await page.evaluate(
                    "(document.querySelector('main') || document.body).innerText")
                content_parts = [body_text]
            except Exception:
                content_parts = ["(Content could not be extracted)"]

        # Extract internal links
        internal_links = []
        links = await page.evaluate(
            "JSON.stringify([...document.querySelectorAll('a[href]')]"
            ".map(a => a.getAttribute('href')).filter(Boolean))"
        )
        if isinstance(links, str):
            try:
                links = json.loads(links)
            except ValueError:
                links = []
        for href in (links or []):
            try:
                if href and self.is_internal_link(href):
                    full_url = urljoin(url, href)
                    normalized = self.normalize_url(full_url)
                    if normalized != self.normalize_url(url):
                        internal_links.append(normalized)
            except Exception:
                continue

        # Extract images
        images = []
        img_srcs = await page.evaluate(
            "JSON.stringify([...document.querySelectorAll('img')]"
            ".map(i => i.getAttribute('src')).filter(Boolean))"
        )
        if isinstance(img_srcs, str):
            try:
                img_srcs = json.loads(img_srcs)
            except ValueError:
                img_srcs = []
        for src in (img_srcs or []):
            try:
                if src and not src.startswith('data:') and 'notion-static' not in src:
                    local_path = await self.download_image(src, url)
                    if local_path:
                        images.append({'src': src, 'local': local_path})
            except Exception:
                continue

        return {
            'title': title,
            'content': '\n\n'.join(content_parts),
            'internal_links': list(set(internal_links)),
            'images': images
        }

    async def crawl_page(self, page, url: str, index: int) -> list[str]:
        """Crawl a single page and return discovered links."""
        normalized_url = self.normalize_url(url)

        if normalized_url in self.visited_urls:
            return []

        print(f"[{index}] Crawling: {url}")
        self.visited_urls.add(normalized_url)

        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)

            # Wait for Notion content to render
            try:
                await page.wait_for_selector('main', timeout=15000)
            except Exception:
                await asyncio.sleep(3)

            # Additional wait for dynamic content
            await asyncio.sleep(3)

            # Extract content
            data = await self.extract_content(page, url)

            # Generate clean filename
            filename = self.clean_filename(data['title'], index)
            notion_id = self.extract_notion_id(url)

            self.page_map[normalized_url] = {
                'title': data['title'],
                'filename': filename,
                'notion_id': notion_id,
                'content': data['content'],
                'images': data['images']
            }
            self.page_order.append(normalized_url)

            print(f"  Title: {data['title']}")
            print(f"  Found {len(data['internal_links'])} internal links")

            return data['internal_links']

        except Exception as e:
            print(f"  Error crawling {url}: {e}")
            return []

    def rewrite_links(self, content: str, source_url: str) -> str:
        """Rewrite Notion links to local wikilinks."""
        result = content

        for url, info in self.page_map.items():
            notion_id = info.get('notion_id')
            if notion_id:
                # Replace various URL patterns
                patterns = [
                    rf'\[([^\]]+)\]\([^)]*{notion_id}[^)]*\)',  # Markdown links
                    rf'https?://[^\s]*{notion_id}[^\s]*',  # Raw URLs
                ]
                for pattern in patterns:
                    result = re.sub(pattern, f'[[{info["filename"]}]]', result)

        return result

    def save_page(self, url: str):
        """Save a crawled page as markdown."""
        info = self.page_map[url]
        filename = info['filename'] + '.md'
        filepath = self.output_dir / filename

        # Build markdown content
        md_content = f"# {info['title']}\n\n"

        # Rewrite links in content
        content = self.rewrite_links(info['content'], url)
        md_content += content

        # Add images
        if info['images']:
            md_content += "\n\n---\n\n## Images\n\n"
            for img in info['images']:
                md_content += f"![]({img['local']})\n"

        filepath.write_text(md_content)
        print(f"Saved: {filename}")

    def create_index(self):
        """Create index file with table of contents."""
        index_content = "# Index\n\n"
        index_content += f"Downloaded from: {self.base_url}\n\n"
        index_content += "## Table of Contents\n\n"

        for url in self.page_order:
            info = self.page_map[url]
            index_content += f"- [[{info['filename']}|{info['title']}]]\n"

        index_path = self.output_dir / "00-Index.md"
        index_path.write_text(index_content)
        print(f"Saved: 00-Index.md")

    async def run(self):
        """Run the downloader."""
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        print(f"Starting download from: {self.base_url}")
        print(f"Output directory: {self.output_dir}")
        if self.test_mode:
            print("TEST MODE: Only downloading first page")
        print()

        # gstack browser — never headless (see _browse.py)
        async with browse_page() as page:

            # Start crawling from base URL
            to_visit = [self.base_url]
            index = 0

            while to_visit:
                url = to_visit.pop(0)
                normalized = self.normalize_url(url)

                if normalized in self.visited_urls:
                    continue

                index += 1
                new_links = await self.crawl_page(page, url, index)

                # Add new links to queue
                for link in new_links:
                    if self.normalize_url(link) not in self.visited_urls:
                        to_visit.append(link)

                # In test mode, stop after first page
                if self.test_mode:
                    break


        print(f"\nCrawled {len(self.page_map)} pages")

        # Save all pages
        print("\nSaving pages...")
        for url in self.page_order:
            self.save_page(url)

        # Create index
        self.create_index()

        # Save page map for reference
        map_path = self.output_dir / "_page_map.json"
        map_data = {url: {k: v for k, v in info.items() if k != 'content'}
                   for url, info in self.page_map.items()}
        map_path.write_text(json.dumps(map_data, indent=2))

        print(f"\nDone! {len(self.page_map)} pages saved to {self.output_dir}")

        # Never report success on an empty crawl. A Notion site that refuses to
        # render, or a URL that is not actually a public site, yields zero
        # pages — and OUTPUT_DIR would send the caller to summarise nothing.
        if not self.page_map:
            print("ERROR: no pages were captured. The URL may not be a public "
                  "Notion site, or rendering failed. No OUTPUT_DIR marker is "
                  "emitted, because a caller chaining on it would summarise an "
                  "empty directory.", file=sys.stderr)
            sys.exit(3)

        # A page that is mostly headings with empty bodies is the classic
        # Notion failure — collapsed toggles the crawler never expanded. It
        # looks like a valid short page, so it has to be surfaced numerically.
        thin = [u for u, i in self.page_map.items()
                if len((i.get('content') or '')) < 400]
        if thin:
            print(f"WARNING: {len(thin)} of {len(self.page_map)} pages are under "
                  f"400 bytes. That is the signature of unexpanded toggle blocks, "
                  f"not of short pages. Re-extract them with toggles expanded and "
                  f"compare byte counts before accepting this capture.",
                  file=sys.stderr)

        # contract: final stdout line is machine-parseable
        print(f"OUTPUT_DIR:{self.output_dir}")


async def main():
    parser = argparse.ArgumentParser(description='Download a Notion site as Markdown')
    parser.add_argument('url', help='Base URL of the Notion site')
    parser.add_argument('output_dir', nargs='?', default=None,
                        help='Output directory (default: a fresh temp directory)')
    parser.add_argument('--test', action='store_true', help='Test mode: download only first page')

    args = parser.parse_args()

    # contract: output_dir optional -> temp dir; created if missing
    output_dir = args.output_dir or tempfile.mkdtemp(prefix='notion_')
    os.makedirs(output_dir, exist_ok=True)

    downloader = NotionDownloader(
        base_url=args.url,
        output_dir=output_dir,
        test_mode=args.test
    )

    await downloader.run()


if __name__ == '__main__':
    asyncio.run(main())
