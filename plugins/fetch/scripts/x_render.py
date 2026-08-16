import re

_FORBIDDEN = re.compile(r'[/\\:"?*<>|]')
_WS = re.compile(r'\s+')

def slugify(text: str, max_len: int = 60) -> str:
    s = _FORBIDDEN.sub("", text)
    s = _WS.sub(" ", s).strip()
    return s[:max_len].strip()

def note_filename(date: str, handle: str, slug: str) -> str:
    return f"{date} @{handle} - {slug}.md"
