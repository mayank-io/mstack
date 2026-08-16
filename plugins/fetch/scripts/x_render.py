import os
import re

_FORBIDDEN = re.compile(r'[/\\:"?*<>|]')
_WS = re.compile(r'\s+')

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
        f"author_name: {post['author_name']}",
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
    if post.get("harvest_run"):
        lines.append(f"harvest_run: {post['harvest_run']}")
    lines += ["---", ""]

    lines += [f"# {_derive_title(post)}", ""]

    if post_type == "thread":
        for i, section in enumerate(post.get("sections", []), start=1):
            lines.append(f"## {i}.")
            lines.append("")
            lines.append(section["content"])
            lines += _image_lines(section.get("image_files"))
            lines.append("")
    else:
        lines.append(post["content"])
        lines += _image_lines(post.get("image_files"))
        lines.append("")

    lines.append(f"**Engagement:** {likes} likes · {reposts} reposts · {views} views")
    lines.append(f"**Posted:** {post['date']}")

    return "\n".join(lines) + "\n"
