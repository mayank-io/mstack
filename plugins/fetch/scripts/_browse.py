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

import asyncio
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
        """Attach to the gstack daemon, starting one only if none is running.

        The user's normal state is a headed daemon already open holding their
        logins. `browse connect` refuses in that case ("A healthy daemon is
        already running… Connecting headed would kill it"), which would fail
        every fetch skill at step one. An existing daemon is exactly what we
        want, so that refusal is success.
        """
        try:
            self._run("connect", timeout=180)
            self._owns_daemon = True
        except BrowseError as e:
            if "already running" in str(e):
                self._owns_daemon = False  # someone else's — leave it alone
            else:
                raise

    def close(self) -> None:
        """Disconnect ONLY a daemon this object started.

        Disconnecting one we merely attached to would close the user's browser
        and drop their tabs, cookies and logins mid-session — destroying the
        very thing that makes gstack worth using.
        """
        if not getattr(self, "_owns_daemon", False):
            return
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

    async def wait_for_timeout(self, ms: int):
        """Playwright's page.waitForTimeout, in ms. Present so callers written
        in Playwright idiom do not have to be rewritten."""
        await asyncio.sleep(ms / 1000)

    async def evaluate(self, expression: str, *args):
        """Evaluate JS and return a Python value, like Playwright's page.evaluate.

        Two differences from a raw `$B js` call, both restoring Playwright
        semantics:

        1. `$B js` PRINTS its result, so objects and arrays would arrive as
           "[object Object]" unless serialised. Everything is wrapped in
           JSON.stringify and decoded here.
        2. `$B js` takes an expression, not a function plus arguments. Args are
           JSON-encoded and applied to the function literal. Silently dropping
           them — as this did until 2026-08-24 — is worse than failing: a
           thread-root walk passing `focalId` would see `undefined` and report
           "not a thread" for a real thread, with no error anywhere.
        """
        expr = expression.strip()
        head = expr.split("\n")[0]
        is_async = expr.startswith("async")
        body = expr[len("async"):].strip() if is_async else expr
        is_fn = body.startswith("()") or (body.startswith("(") and "=>" in body.split("\n")[0])

        if args:
            if not is_fn:
                raise BrowseError(
                    "evaluate() got arguments but the expression is not a function "
                    "literal; arguments can only be applied to a function"
                )
            packed = json.dumps(list(args))
            call = f"({expr})(...JSON.parse({json.dumps(packed)}))"
        elif is_fn:
            # a function literal must be invoked, not returned
            call = f"({expr})()"
        else:
            call = expr

        if is_async or "await " in expr:
            # `$B js` does NOT await promises — verified live 2026-08-24 against
            # gstack: an async IIFE with a real 300ms await prints nothing, and
            # JSON.stringify of the pending promise gives "{}". Either way the
            # caller gets an empty result that reads as success.
            #
            # There is no expression-level fix; the CLI returns before the
            # promise resolves. Hoist the waiting into Python instead:
            #
            #     for _ in range(15):
            #         if await page.evaluate("() => document.readyState === 'complete'"):
            #             break
            #         await page.wait_for_timeout(500)
            #
            # Failing here is the point. Returning None silently turned
            # "the scroll never ran" into "the page has no images".
            raise BrowseError(
                "evaluate() cannot run async JavaScript: `$B js` returns before a "
                "promise resolves, so the result is silently lost. Restructure as "
                "synchronous evaluate() calls with await page.wait_for_timeout(ms) "
                "between them, driving the loop from Python."
            )

        expr = call if "JSON.stringify" in head else f"JSON.stringify(({call}))"
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
