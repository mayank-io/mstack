import os
import re

_FORBIDDEN = re.compile(r'[/\\:"?*<>|]')
_WS = re.compile(r'\s+')


def _yaml_quote(s: str) -> str:
    """Render s as a YAML-safe double-quoted scalar (escapes backslashes and quotes)."""
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'


def _fmt_count(n: int) -> str:
    """Format a count with thousands separators and K/M abbreviation.
    Rules:
    - Always use thousands separators (e.g., 1,240).
    - Abbreviate to K (thousands) / M (millions) when n >= 10_000.
    - Use one decimal place for K/M values (e.g., 88.4K, 1.2M).
    Examples: 312 -> "312", 1240 -> "1,240", 88400 -> "88.4K", 1234567 -> "1.2M".
    """
    if n < 1_000:
        return str(n)
    if n < 10_000:
        return f"{n:,}"
    if n < 1_000_000:
        return f"{n / 1_000:.1f}K"
    return f"{n / 1_000_000:.1f}M"

def slugify(text: str, max_len: int = 60) -> str:
    s = _FORBIDDEN.sub("", text)
    s = _WS.sub(" ", s).strip()
    return s[:max_len].strip()

def note_filename(date: str, handle: str, slug: str) -> str:
    return f"{date} @{handle} - {slug}.md"


def _derive_title(post: dict) -> str:
    """Deterministic title: explicit post['title'] wins; otherwise derive
    from the post body (or the first thread section) via slugify(), same
    sanitization used for filenames. No K-abbreviation or NLP summarization.
    """
    if post.get("title"):
        return post["title"]
    if post.get("post_type") == "thread":
        sections = post.get("sections") or []
        basis = sections[0]["content"] if sections else ""
    else:
        basis = post.get("content", "")
    return slugify(basis, max_len=80) or "Untitled"


def _image_lines(image_files) -> list:
    """Render `![description](attachments/<file>)` for each image file.
    Description = filename stem (no alt text is supplied by the source
    data, so we derive something readable and deterministic rather than
    leaving alt text empty).
    """
    return [
        f"![{os.path.splitext(name)[0]}](attachments/{name})"
        for name in (image_files or [])
    ]


def _fmt_duration(seconds) -> str:
    """H:MM:SS or M:SS, matching the transcript timestamp format."""
    seconds = int(seconds)
    h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _video_lines(video) -> list:
    """Frontmatter keys for a video post.

    `media:` is already an integer image count, so the kind of media goes in
    `media_type:` — which is also what the existing video clippings use.

    A duration that could not be read is OMITTED rather than written as 0. A
    real zero-second video and an unread duration are different facts, and 0
    reads as "too short to bother transcribing" — exactly the wrong conclusion
    for the 53-minute lecture this was built for.
    """
    if not video or not video.get("present"):
        return []
    lines = ["media_type: gif" if video.get("isGif") else "media_type: video"]
    seconds = video.get("seconds")
    if seconds:
        lines.append(f"video_seconds: {int(seconds)}")
        lines.append(f"video_duration: {_fmt_duration(seconds)}")
    media_id = video.get("mediaId")
    if media_id:
        # A Snowflake, so it timestamps the upload. Recorded whether or not it
        # looks suspicious: the comparison is only possible if the id is kept.
        lines.append(f'video_media_id: "{media_id}"')
        uploaded = video.get("mediaUploaded")
        if uploaded:
            lines.append(f"video_uploaded: {uploaded}")
    if not video.get("isGif"):
        # Set by the transcription step, not here. Present-and-none is the
        # signal that a transcript is owed; absent would be indistinguishable
        # from a text post.
        lines.append("transcript: pending")
    return lines


def render_note(post: dict) -> str:
    """Render the full Markdown note (YAML frontmatter + body) for a single
    X post or thread. Emits zero vault syntax (no wikilinks, no daily-note
    links) — that belongs to the later vault layer (Task 20).
    """
    handle = post["handle"]
    status_id = post["status_id"]
    post_type = post["post_type"]
    metrics = post.get("metrics", {})
    likes = metrics.get("likes", 0)
    reposts = metrics.get("reposts", 0)
    views = metrics.get("views", 0)
    media = post.get("media", 0)

    lines = [
        "---",
        "tags:",
        "  - clippings",
        "  - x-post",
        f"source: https://x.com/{handle}/status/{status_id}",
        f'author: "@{handle}"',
        f"author_name: {_yaml_quote(post['author_name'])}",
        f"date: {post['date']}",
        f"date_captured: {post['date_captured']}",
        f'status_id: "{status_id}"',
        f"post_type: {post_type}",
    ]
    if post_type == "thread":
        lines.append(f"thread_length: {post['thread_length']}")
    lines += [
        f"likes: {likes}",
        f"reposts: {reposts}",
        f"views: {views}",
        f"media: {media}",
    ]
    lines += _video_lines(post.get("video"))
    if post.get("harvest_run"):
        lines.append(f"harvest_run: {post['harvest_run']}")
    lines += ["---", ""]

    lines += [f"# {_derive_title(post)}", ""]

    if post_type == "thread":
        sections = post.get("sections", [])
        n = len(sections)
        for i, section in enumerate(sections, start=1):
            # inline n/N marker (how threads read on X); no empty ## headers
            lines.append(f"**{i}/{n}** {section['content']}".rstrip())
            lines += _image_lines(section.get("image_files"))
            lines.append("")
    else:
        lines.append(post["content"])
        lines += _image_lines(post.get("image_files"))
        lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"**Engagement:** {_fmt_count(likes)} likes · {_fmt_count(reposts)} reposts · {_fmt_count(views)} views")
    lines.append(f"**Posted:** {post['date']}")

    return "\n".join(lines) + "\n"
