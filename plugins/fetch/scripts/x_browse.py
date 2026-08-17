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


def status_mode() -> str:
    """The browse server's mode string, lowercased (e.g. 'headed', 'launched',
    'headless'). Empty string if it can't be read."""
    out, _, _ = _run("status")
    for line in out.splitlines():
        if line.lower().startswith("mode:"):
            return line.split(":", 1)[1].strip().lower()
    return ""


# A software WebGL renderer means no real GPU == headless. The GStack status
# "Mode" string is NOT reliable (observed reporting 'headed' while the actual
# process was chrome-headless-shell), so the GPU is the source of truth.
_SOFTWARE_RENDERERS = ("swiftshader", "llvmpipe", "software renderer", "mesa offscreen")

_WEBGL_RENDERER_JS = (
    "(function(){try{const gl=document.createElement('canvas').getContext('webgl');"
    "const d=gl&&gl.getExtension('WEBGL_debug_renderer_info');"
    "return d?gl.getParameter(d.UNMASKED_RENDERER_WEBGL):'';}catch(e){return '';}})()"
)


def _is_software_renderer(renderer: str) -> bool:
    r = (renderer or "").lower()
    return any(s in r for s in _SOFTWARE_RENDERERS)


def webgl_renderer() -> str:
    """The page's unmasked WebGL renderer string (real GPU vs software)."""
    return js(_WEBGL_RENDERER_JS)


def is_headed() -> bool:
    """True only if the browser is a real, visible headed window on a real GPU.

    Enforced invariant: never drive X headless (headless is far more
    fingerprintable). Checked before every run because the browse server
    silently drifts, and — critically — because its status 'Mode: headed'
    can lie while chrome-headless-shell is what's actually running. The GPU
    is the tiebreaker: a software renderer (SwiftShader/llvmpipe) == headless.
    Conservative: unreadable GPU also fails (refuse when uncertain).
    """
    if status_mode() != "headed":
        return False
    renderer = webgl_renderer()
    return bool(renderer) and not _is_software_renderer(renderer)


def status_ok() -> bool:
    """True if the browse server is healthy AND headed."""
    out, _, rc = _run("status")
    return rc == 0 and "healthy" in out.lower() and is_headed()


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


def viewport_height() -> int:
    """Current viewport height in px (fallback 900 if the page won't answer)."""
    out = js("window.innerHeight")
    try:
        return int(float(out))
    except (ValueError, TypeError):
        return 900


def scroll_by(pixels: int):
    """Scroll a specific pixel distance (signed; negative = up). Lets the loop
    vary scroll distance per action instead of a fixed page jump."""
    return _run("js", f"window.scrollBy(0, {int(pixels)})")


def js(expr: str) -> str:
    """Evaluate a JS expression in the page and return its stdout."""
    out, _, _ = _run("js", expr)
    return out


# JS that collects the status IDs of every article currently in the DOM.
# The article's OWN id is the timestamp permalink when present; X does not
# always render a <time> element (observed 2026-08: zero <time> on a profile
# timeline), so it falls back to the FIRST status link in DOM order — the
# header permalink precedes any embedded quote/reply card, which carries a
# different handle's id. Virtualization-safe ONLY because the caller runs it
# every scroll tick and unions the results.
COLLECT_IDS_JS = (
    "JSON.stringify(Array.from(document.querySelectorAll('article'))"
    ".map(a=>{const links=Array.from(a.querySelectorAll('a[href*=\"/status/\"]'));"
    "let l=links.find(x=>x.querySelector('time'))||links[0];"
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
