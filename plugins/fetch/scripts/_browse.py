#!/usr/bin/env python3
"""Adapter that drives the gstack browser (`$B`) behind a minimal Playwright-like API.

Why: the gstack browser holds the user's logged-in sessions. A fresh headless
Playwright instance is logged out and silently returns login walls or truncated
content that looks like a successful capture. gstack exposes no CDP socket to
attach to, so we drive its CLI instead.

Only the surface these scripts actually used is implemented: goto,
wait_for_selector, evaluate. Signatures match Playwright's so call sites barely
change.
"""

import json
import os
import shutil
import subprocess
import sys

_CANDIDATES = [
    os.path.expanduser("~/.claude/skills/gstack/browse/dist/browse"),
    os.path.join(os.getcwd(), ".claude/skills/gstack/browse/dist/browse"),
]


def _resolve_browse() -> str:
    for c in _CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    found = shutil.which("browse")
    if found:
        return found
    raise RuntimeError(
        "gstack browser not found. Expected an executable at "
        "~/.claude/skills/gstack/browse/dist/browse.\n"
        "Refusing to fall back to a headless browser: it would be logged out and "
        "would return a login wall that looks like a successful capture."
    )


class BrowseError(RuntimeError):
    pass


class BrowsePage:
    """A Playwright-ish `page`, backed by the gstack browse CLI."""

    def __init__(self, quiet: bool = False):
        self._b = _resolve_browse()
        self._quiet = quiet

    # -- plumbing ---------------------------------------------------------

    def _run(self, *args: str, timeout: int = 180) -> str:
        proc = subprocess.run(
            [self._b, *args], capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode != 0:
            raise BrowseError(
                f"`browse {' '.join(args[:1])}` failed: "
                f"{(proc.stderr or proc.stdout).strip()[:400]}"
            )
        return proc.stdout

    @staticmethod
    def _parse(out: str):
        """Take the last non-empty stdout line and JSON-decode it if possible."""
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if not lines:
            return None
        last = lines[-1].strip()
        try:
            return json.loads(last)
        except (ValueError, TypeError):
            return last

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> None:
        self._run("connect", timeout=180)

    def close(self) -> None:
        try:
            self._run("disconnect", timeout=60)
        except Exception:
            pass

    # -- Playwright-shaped surface ---------------------------------------

    async def goto(self, url: str, wait_until: str = None, **_):
        self._run("goto", url, timeout=180)
        if wait_until == "networkidle":
            try:
                self._run("wait", "--networkidle", timeout=120)
            except BrowseError:
                pass  # best-effort, same as Playwright's soft timeout

    async def wait_for_selector(self, selector: str, timeout: int = 15000, **_):
        try:
            self._run("wait", selector, timeout=max(5, int(timeout / 1000) + 5))
        except BrowseError as e:
            raise BrowseError(f"selector never appeared: {selector} ({e})")

    async def evaluate(self, expression: str, *_args):
        """Evaluate JS and return a Python value, like Playwright's page.evaluate.

        `$B js` PRINTS its result, so objects and arrays would arrive as
        "[object Object]" unless serialised. Everything is wrapped in
        JSON.stringify and decoded here, which restores Playwright semantics.
        """
        expr = expression.strip()
        # an arrow-function literal must be invoked, not returned
        if expr.startswith("()") or (expr.startswith("(") and "=>" in expr.split("\n")[0]):
            expr = f"({expr})()"
        if "JSON.stringify" not in expr.split("\n")[0]:
            expr = f"JSON.stringify(({expr}))"
        raw = self._parse(self._run("js", expr, timeout=120))
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return raw
        return raw


class browse_page:
    """`async with browse_page() as page:` — mirrors the async_playwright() block."""

    def __init__(self, quiet: bool = False):
        self._page = BrowsePage(quiet=quiet)

    async def __aenter__(self) -> BrowsePage:
        self._page.connect()
        return self._page

    async def __aexit__(self, *exc):
        self._page.close()
        return False
