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

    def mode(self) -> str:
        """`headed` (attached to the user's real Chrome) or `launched`
        (gstack's own browser, fresh profile, logged out of everything)."""
        for line in self._run("status", timeout=60).splitlines():
            if line.lower().startswith("mode:"):
                return line.split(":", 1)[1].strip()
        return "unknown"

    def connect(self, require_headed: bool = True) -> None:
        """Attach to the gstack daemon in HEADED mode, starting one if needed.

        Two failure modes this guards, both of which silently produce
        logged-out captures:

        1. `browse connect` refuses when a daemon is already running ("A
           healthy daemon is already running… Connecting headed would kill
           it"). An existing daemon is what we want, so that refusal is
           success — treating it as fatal failed every fetch skill at step one.

        2. **The daemon can be in `launched` mode.** gstack then runs its own
           Chromium against a fresh profile that is logged into nothing. Every
           gated source — X, LinkedIn, members-only YouTube — returns a login
           wall or an authwall that reads as a short page. `connect` does not
           say which mode you got, and nothing downstream checks.

        Verified repeatedly on 2026-08-24: a daemon that dies and restarts
        comes back `launched`, and the next capture silently hits an authwall.
        Checking the mode is the only reliable guard — the caller cannot tell
        from the content, which is the whole problem.
        """
        try:
            self._run("connect", timeout=180)
            self._owns_daemon = True
        except BrowseError as e:
            if "already running" in str(e):
                self._owns_daemon = False  # someone else's — leave it alone
            else:
                raise

        if not require_headed:
            return

        current = self.mode()
        if current == "headed":
            return

        # Wrong mode. Replacing it is safe: a `launched` daemon holds a fresh
        # profile with no logins, so there is nothing to lose — which is
        # precisely why it must be replaced.
        self._run("connect", "--force-restart", timeout=180)
        self._owns_daemon = True

        current = self.mode()
        if current != "headed":
            raise BrowseError(
                f"gstack is in '{current}' mode, not 'headed', even after a "
                f"forced restart. A launched-mode daemon uses a fresh profile "
                f"with no logins, so every gated page returns a login wall that "
                f"reads as a short page rather than an error.\n\n"
                f"Cause: gstack attaches to a Chromium running with remote "
                f"debugging. If GStack Browser is not open, there is nothing to "
                f"attach to and it silently falls back to launched.\n\n"
                f"Fix: ask the user to run /open-gstack-browser (or "
                f"/connect-chrome), then retry.\n\n"
                f"Refusing to continue — a logged-out capture is worse than "
                f"none, because it looks fine."
            )

    def close(self) -> None:
        """Leave the daemon running. This is deliberately a no-op.

        The daemon is a shared, long-lived user resource holding logged-in
        sessions — it is not this object's to tear down. Three separate ways
        that went wrong before this became a no-op:

        - Disconnecting a daemon we merely attached to closed the user's
          browser and dropped their tabs, cookies and logins mid-session.
        - Disconnecting one we had just force-restarted into `headed` mode
          destroyed the very session we established to fix a `launched`
          daemon — and the next `status` call spawned a fresh `launched` one,
          so the fix silently undid itself between calls.
        - Six skills instructed `"$B" disconnect  # when done` in prose,
          reproducing the first case by hand.

        `connect` is cheap and idempotent, so there is no cost to leaving it
        up. Pass `explicit=True` only when the user asked to close the browser.
        """
        return

    def disconnect_explicitly(self) -> None:
        """Actually tear the daemon down. Only when the user asked for it."""
        try:
            self._run("disconnect", timeout=60)
        except Exception:
            pass

    # -- session state ----------------------------------------------------

    def cookies(self) -> list[dict]:
        """The live session's cookies, in Playwright's BrowserContext.cookies() shape.

        Playwright hangs these off the context; gstack exposes them as
        `$B cookies`. Needed because tools that cannot share the browser
        session — yt-dlp fetching member-only audio, above all — have to be
        handed a cookie jar on disk, and the only jar worth handing them is the
        headed daemon's, since that is the one that is actually logged in.

        Parsed off the whole of stdout rather than through `_parse`: `$B
        cookies` pretty-prints a multi-line JSON array, so a last-line parse
        sees a bare `]` and returns nothing, which reads as "no cookies" — the
        same silent-empty failure mode this module exists to prevent.
        """
        out = self._run("cookies", timeout=60)
        lines = out.splitlines()
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            # `[browse] ...` progress chatter also starts with `[`.
            if stripped.startswith("[") and not stripped.startswith("[browse"):
                try:
                    data = json.loads("\n".join(lines[i:]))
                except (ValueError, TypeError):
                    return []
                return data if isinstance(data, list) else []
        return []

    # -- Playwright-shaped surface ---------------------------------------

    async def goto(self, url: str, wait_until: str = None, **_):
        self._run("goto", url, timeout=180)
        if wait_until == "networkidle":
            try:
                self._run("wait", "--networkidle", timeout=120)
            except BrowseError:
                pass  # best-effort, same as Playwright's soft timeout

    async def wait_for_selector(self, selector: str, timeout: int = 15000, **_):
        """Wait for a selector, matching Playwright's semantics.

        `$B wait` refuses a selector that matches more than one element
        ("Selector matched multiple elements"). Playwright waits for the FIRST
        match and does not care how many there are — and callers rely on that:
        `wait_for_selector("article")` is how every X capture starts, and an X
        status page always has several.

        Multiple matches mean the selector is present, which is the entire
        question being asked. Treating it as failure — and reporting it as
        "selector never appeared", the opposite of what happened — sent callers
        looking for a page-load problem that did not exist.
        """
        try:
            self._run("wait", selector, timeout=max(5, int(timeout / 1000) + 5))
        except BrowseError as e:
            if "matched multiple elements" in str(e):
                return  # present, several times over — that is a pass
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
