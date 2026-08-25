"""Source-level invariants: every browser-driving fetch script goes through _browse.

These are static checks over the script sources, not live browser runs. They
exist because the failure they guard is invisible at runtime:

A browser that is not the gstack daemon in HEADED mode is logged into nothing.
Every gated source then returns a login wall or an authwall that renders as a
*short page*, not as an error. `browse_page()` is the only entry point that
checks `browse status` and force-restarts a `launched` daemon, so a script that
constructs `BrowsePage()` directly, or launches its own Playwright, produces a
capture that looks fine and is empty. Nothing downstream can tell.

The four invariants below are exactly what an auditor would grep for, pinned so
the audit does not have to be repeated by hand.
"""

import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]

# Scripts whose browser work must be routed through _browse.browse_page().
ROUTED = [
    "notion_public_site_downloader.py",
    "scribd_extractor.py",
    # Added 2026-08-24. Tier 2 used to launch its own Playwright Chromium on a
    # throwaway profile at ~/.claude/youtube-chrome-profile — headed, but
    # signed into nothing until someone sat through a one-off interactive
    # login, and silently signed out again whenever those cookies expired. A
    # members-only video then renders a watch page with no "Show transcript"
    # button, which is indistinguishable from a video that has no captions.
    "youtube_transcript_extractor.py",
]


def _tree(name: str) -> ast.Module:
    return ast.parse((SCRIPTS / name).read_text(), filename=name)


def _src(name: str) -> str:
    return (SCRIPTS / name).read_text()


@pytest.mark.parametrize("name", ROUTED)
def test_browser_work_enters_through_browse_page(name):
    """`browse_page()` is where the headed check lives — nothing else has it."""
    assert "browse_page" in _src(name), (
        f"{name} does not call browse_page(); it cannot be enforcing headed mode"
    )


@pytest.mark.parametrize("name", ROUTED)
def test_no_script_launches_its_own_browser(name):
    """A self-launched browser has a fresh profile and is logged out."""
    src = _src(name)
    for banned in ("async_playwright", "chromium.launch", "playwright.async_api",
                   "playwright.sync_api", "headless="):
        assert banned not in src, (
            f"{name} contains {banned!r}: a freshly launched browser is logged "
            f"out, and every gated page then returns a login wall that reads as "
            f"a short page. Route through _browse.browse_page() instead."
        )


@pytest.mark.parametrize("name", ROUTED)
def test_no_script_constructs_BrowsePage_directly(name):
    """Direct construction skips connect()'s mode check — the whole guard."""
    assert "BrowsePage(" not in _src(name), (
        f"{name} constructs BrowsePage directly, bypassing browse_page()'s "
        f"headed-mode enforcement"
    )


@pytest.mark.parametrize("name", ROUTED)
def test_no_script_tears_down_the_daemon(name):
    """The daemon is a shared user resource holding their logged-in sessions."""
    assert "disconnect" not in _src(name), (
        f"{name} disconnects the gstack daemon, closing the user's browser and "
        f"dropping the logins the next capture depends on"
    )


def _evaluate_js_literals(name: str):
    """Yield the JS source of every `<something>.evaluate("...")` first argument."""
    for node in ast.walk(_tree(name)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "evaluate"):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        try:
            js = ast.literal_eval(arg)
        except (ValueError, SyntaxError):
            continue  # not a literal; nothing to inspect
        if isinstance(js, str):
            yield node.lineno, js


@pytest.mark.parametrize("name", ROUTED)
def test_no_async_page_javascript(name):
    """`$B js` returns before a promise resolves, so an in-page await is lost.

    _browse.evaluate() raises on these by design. Catching it here names the
    line instead of failing mid-crawl. The fix is always the same: keep the page
    JS synchronous and drive the waiting from Python with wait_for_timeout().
    """
    for lineno, js in _evaluate_js_literals(name):
        stripped = js.strip()
        assert not stripped.startswith("async"), (
            f"{name}:{lineno} passes an async function to evaluate(); "
            f"`$B js` does not await it and the result is silently lost"
        )
        assert "await " not in js, (
            f"{name}:{lineno} passes JS containing `await` to evaluate(); "
            f"`$B js` returns before the promise resolves. Restructure as "
            f"synchronous evaluate() calls with await page.wait_for_timeout(ms) "
            f"between them."
        )


def test_the_js_literal_scanner_actually_finds_something():
    """Guard against the scan above passing because it inspected nothing."""
    found = list(_evaluate_js_literals("scribd_extractor.py"))
    assert len(found) >= 4, f"expected several evaluate() literals, got {found}"


def test_chart_to_ascii_does_no_browser_work():
    """Pinned so a future edit does not quietly add an unguarded browser path."""
    src = _src("chart_to_ascii.py")
    for banned in ("playwright", "chromium", "browse_page", "BrowsePage",
                   "headless", "webdriver", "selenium"):
        assert banned not in src, (
            f"chart_to_ascii.py now references {banned!r}. It was audited as "
            f"doing no browser work; any new browser path must go through "
            f"_browse.browse_page()."
        )


def test_scripts_that_do_no_browser_work_stay_that_way():
    """whisper_transcriber and verify_caption_window reach YouTube through
    yt-dlp, never a browser. Pinned so a future edit does not add an unguarded
    browser path — and so the member-only cookie jar keeps arriving via
    --cookies from the headed session rather than being re-fetched here."""
    for name in ("whisper_transcriber.py", "verify_caption_window.py"):
        src = _src(name)
        for banned in ("playwright", "chromium", "browse_page", "BrowsePage",
                       "webdriver", "selenium"):
            assert banned not in src, (
                f"{name} now references {banned!r}. It was audited as doing no "
                f"browser work; any new browser path must go through "
                f"_browse.browse_page()."
            )
