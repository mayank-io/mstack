"""LinkedIn ARTICLE download unit — `linkedin.com/pulse/<slug>`.

Articles are not posts, and every post-mode technique in the `fetch:linkedin-post`
skill either finds nothing on them or finds the wrong thing:

* there is no hidden "Feed post" heading to scope to, so the post-mode link
  harvest returns "post card not found";
* there is no "...more" expander, because the full body is rendered;
* there is no activity id in the URL (`-6vsuc` is a slug suffix), so the
  `id >> 22` date decode would produce a confident wrong date;
* the post-mode image filter REJECTS `article-cover_image` as sidebar furniture
  and does not know `article-inline_image` at all, so every image in the body
  would be dropped.

The DOM logic is `skills/linkedin-post/references/article_extraction.js`, tested
under jsdom against a saved copy of a live article. This file owns navigation,
waiting, validation, downloading and writing.

    python3 linkedin_article_download.py <pulse-url> [out_dir]

Writes `article.json`, `article.md` (plain Markdown, no vault syntax) and the
images into `out_dir` (a temp directory when omitted). The final stdout line is
`OUTPUT_DIR:<abs path>`; on failure the script exits non-zero with no marker.

The CLI never launches its own browser: it goes through `_browse.sync_browse_page()`,
which refuses anything but the user's headed, logged-in gstack session.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_EXTRACTION_JS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "skills", "linkedin-post", "references",
    "article_extraction.js"))

_PULSE_URL = re.compile(
    r"^(?:https?://)?(?:[a-z]{2,3}\.|www\.)?linkedin\.com/pulse/([A-Za-z0-9%_.~-]+?)/?(?:[?#].*)?$")

_CDN_UPLOAD_MS = re.compile(r"/0/(\d{13})(?:[?#]|$)")

# A body shorter than this is a login wall, an authwall, or a capture of the
# wrong page. The shortest real article we have seen is ~6,000 characters.
MIN_BODY_CHARS = 300

# Two days of slack between the printed date and the image upload time: an
# author can upload images while drafting and publish the next day.
MAX_DATE_SKEW_DAYS = 2


def parse_pulse_url(url):
    """Return the canonical article URL and its slug, or raise ValueError.

    Anything that is not a Pulse article is refused before the browser moves:
    a post permalink belongs to post mode, and a profile or feed URL would
    extract whatever article-shaped thing happened to be on the page.
    """
    m = _PULSE_URL.match((url or "").strip())
    if not m:
        raise ValueError(f"not a LinkedIn article URL (linkedin.com/pulse/<slug>): {url!r}")
    slug = m.group(1)
    return f"https://www.linkedin.com/pulse/{slug}/", slug


def parse_published_label(label):
    """'October 2, 2026' / 'Oct 2, 2026' -> '2026-10-02'. None when unparseable.

    Never guess: a relative label ("2w") or an empty one returns None, and the
    caller records the date as unknown rather than inventing one.
    """
    label = (label or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(label, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def cdn_upload_time(url):
    """Upload time embedded in a media.licdn.com path (`/0/<epoch_ms>?...`), UTC."""
    m = _CDN_UPLOAD_MS.search(url or "")
    if not m:
        return None
    return datetime.datetime.fromtimestamp(int(m.group(1)) / 1000, datetime.timezone.utc)


def image_role(url):
    """'cover', 'inline', or None for anything that is not article content."""
    if "/article-cover_image-" in (url or ""):
        return "cover"
    if "/article-inline_image-" in (url or ""):
        return "inline"
    return None


def body_chars(blocks):
    return sum(len(b.get("text", "")) + sum(len(i) for i in b.get("items", []))
               for b in blocks)


def validate(data):
    """Problems that make the capture unusable. Empty list means usable."""
    if not isinstance(data, dict):
        return ["extractor returned nothing"]
    if data.get("error"):
        return [data["error"]]
    problems = []
    if not data.get("title"):
        problems.append("no article title (<h1>) found")
    n = body_chars(data.get("blocks", []))
    if n < MIN_BODY_CHARS:
        problems.append(f"body is {n} characters (< {MIN_BODY_CHARS}); "
                        f"likely a login wall or the wrong page")
    return problems


def date_check(published, image_urls):
    """Corroborate the printed date against image upload times.

    Returns (earliest_upload_iso_or_None, warning_or_None).
    """
    times = [t for t in (cdn_upload_time(u) for u in image_urls) if t]
    if not times:
        return None, None
    first = min(times)
    if published:
        skew = abs((datetime.date.fromisoformat(published) - first.date()).days)
        if skew > MAX_DATE_SKEW_DAYS:
            return first.isoformat(), (f"printed date {published} is {skew} days from the "
                                       f"earliest image upload {first.date()}; the label "
                                       f"may reflect an edit or a republish")
    return first.isoformat(), None


def image_filename(slug, role, n):
    base = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:60]
    return f"linkedin-{base}-cover.jpg" if role == "cover" else f"linkedin-{base}-{n}.jpg"


def render_markdown(data, image_files):
    """Plain Markdown of the article, in document order. No vault syntax: the
    note-writer owns wikilinks, frontmatter and daily notes.

    `image_files` maps a source URL to its downloaded filename; an image that
    failed to download is rendered as its source URL so its position survives.
    """
    out = [f"# {data['title']}", ""]
    byline = " · ".join(x for x in (data.get("author_name"), data.get("author_headline"),
                                    data.get("published_label")) if x)
    if byline:
        out += [f"*{byline}*", ""]
    if data.get("cover"):
        out += [f"![cover]({image_files.get(data['cover'], data['cover'])})", ""]
    for b in data.get("blocks", []):
        t = b["type"]
        if t == "heading":
            # the title is the document's only `#`; article h2 -> ##, h3 -> ###
            out.append("#" * max(2, b["level"]) + " " + b["text"])
        elif t == "paragraph":
            out.append(b["text"])
        elif t == "quote":
            out.append("\n".join("> " + line for line in b["text"].split("\n")))
        elif t == "code":
            out.append("```\n" + b["text"] + "\n```")
        elif t == "list":
            out.append("\n".join((f"{i}. " if b["ordered"] else "- ") + item
                                 for i, item in enumerate(b["items"], 1)))
        elif t == "image":
            alt = b.get("alt") or "image"
            out.append(f"![{alt}]({image_files.get(b['src'], b['src'])})")
            if b.get("caption"):
                out.append(f"*{b['caption']}*")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _download(url, path):
    subprocess.run(["curl", "-fsL", "--max-time", "60", "-o", path, url],
                   check=False, timeout=90)
    return os.path.exists(path) and os.path.getsize(path) > 0


def _inject(page):
    src = open(_EXTRACTION_JS_PATH, encoding="utf-8").read()
    kind = page.evaluate("() => {\n" + src + "\nreturn typeof window.__liArticle;\n}")
    if kind != "object":
        raise RuntimeError(f"article_extraction.js did not install (typeof = {kind!r})")


def capture(page, url, out_dir) -> dict:
    canonical, slug = parse_pulse_url(url)
    page.goto(canonical)
    page.wait_for_selector("article", timeout=20000)
    _inject(page)

    # Inline images are lazy: their src arrives as they scroll into view.
    # Step through the page, then poll until none are pending.
    for _ in range(12):
        at_end = page.evaluate(
            "() => { window.scrollBy(0, window.innerHeight);"
            " return window.innerHeight + window.scrollY >= document.body.scrollHeight - 4; }")
        page.wait_for_timeout(400)
        if at_end:
            break
    for _ in range(15):
        if page.evaluate("() => window.__liArticle.imagesPending()") == 0:
            break
        page.wait_for_timeout(500)

    data = page.evaluate("() => window.__liArticle.extract()")
    problems = validate(data)
    if problems:
        return {"error": "; ".join(problems)}

    os.makedirs(out_dir, exist_ok=True)
    published = parse_published_label(data.get("published_label"))
    image_urls = ([data["cover"]] if data.get("cover") else []) + \
                 [b["src"] for b in data["blocks"] if b["type"] == "image"]
    uploaded, warning = date_check(published, image_urls)

    files, failed, n = {}, [], 0
    for u in image_urls:
        role = image_role(u)
        if role == "inline":
            n += 1
        fn = image_filename(slug, role, n)
        if _download(u, os.path.join(out_dir, fn)):
            files[u] = fn
        else:
            failed.append(u)

    record = {
        "type": "article",
        "source": canonical,
        "slug": slug,
        **{k: data.get(k) for k in ("title", "author_name", "author_headline",
                                    "author_url", "published_label", "metrics", "links")},
        "published": published,
        "earliest_image_upload_utc": uploaded,
        "date_warning": warning,
        "body_chars": body_chars(data["blocks"]),
        "blocks": data["blocks"],
        "cover": data.get("cover") or None,
        "images": [{"url": u, "role": image_role(u), "file": files.get(u)} for u in image_urls],
        "images_failed": failed,
        "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    with open(os.path.join(out_dir, "article.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out_dir, "article.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(data, files))
    return record


def main(argv):
    if not argv:
        print("usage: linkedin_article_download.py <linkedin.com/pulse/... url> [out_dir]",
              file=sys.stderr)
        return 2
    try:
        parse_pulse_url(argv[0])
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(argv[1]) if len(argv) > 1 else tempfile.mkdtemp(prefix="li-article-")

    from _browse import sync_browse_page   # imported here so usage errors need no browser

    with sync_browse_page() as page:
        result = capture(page, argv[0], out_dir)

    # No OUTPUT_DIR marker on failure: a caller chaining on it would write a
    # note from a login wall.
    if result.get("error"):
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1
    if result["date_warning"]:
        print(f"WARNING: {result['date_warning']}", file=sys.stderr)
    for u in result["images_failed"]:
        print(f"WARNING: image download failed: {u}", file=sys.stderr)
    got = sum(1 for i in result["images"] if i["file"])
    print(f"captured article: {result['body_chars']} body chars, {len(result['blocks'])} blocks, "
          f"{got}/{len(result['images'])} image(s) -> {out_dir}", file=sys.stderr)
    print(f"OUTPUT_DIR:{out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
