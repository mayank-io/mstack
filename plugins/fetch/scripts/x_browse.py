"""Thin adapter over the gstack `browse` CLI.

Drives the ALREADY-OPEN, already-logged-in GStack Chromium session — no new
browser, no separate profile. Every function shells out to the same `browse`
binary the user connected with, so all actions land in the window they can
watch. This is the single seam between the governed loop (x_pilot) and the
live browser; keeping it tiny means the loop can be unit-tested by swapping
this module for a fake.
"""
import os
import subprocess

BROWSE_BIN = os.environ.get(
    "GSTACK_BROWSE_BIN",
    os.path.expanduser("~/.claude/skills/gstack/browse/dist/browse"),
)


def _run(*args, timeout=60):
    """Run one browse subcommand. Returns (stdout, stderr, returncode)."""
    proc = subprocess.run(
        [BROWSE_BIN, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.stdout.strip(), proc.stderr.strip(), proc.returncode


def status_ok() -> bool:
    """True if the browse server is healthy and headed."""
    out, _, rc = _run("status")
    return rc == 0 and "healthy" in out.lower()


def goto(url: str):
    return _run("goto", url)


def current_url() -> str:
    out, _, _ = _run("url")
    return out


def page_text() -> str:
    out, _, _ = _run("text")
    return out


def scroll():
    return _run("scroll")


def js(expr: str) -> str:
    """Evaluate a JS expression in the page and return its stdout."""
    out, _, _ = _run("js", expr)
    return out


# JS that collects the status IDs of every article currently in the DOM,
# using the timestamp permalink (which points at the article's OWN id).
# Virtualization-safe ONLY because the caller runs it every scroll tick and
# unions the results — a single end-of-scroll call would miss recycled nodes.
COLLECT_IDS_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll('article'))"
    ".map(a=>{const t=a.querySelector('time');const l=t&&t.closest('a[href*=\"/status/\"]');"
    "const m=l&&l.getAttribute('href').match(/\\/status\\/(\\d+)/);return m?m[1]:null;})"
    ".filter(Boolean))"
)


def collect_status_ids() -> list:
    """Status IDs of articles currently rendered. Empty list on parse failure."""
    import json
    raw = js(COLLECT_IDS_JS)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return []
