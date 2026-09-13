"""Tests for the x-post DOWNLOAD unit's CLI seam and its extraction.js hand-off.

These do NOT drive a real browser. They pin the three places where the unit can
go silently wrong — each one produces a capture that *looks* fine and is empty:

1. A URL that is not a status URL. Navigating to a profile and extracting
   "the post" yields whatever tweet happens to be pinned at the top.
2. The extraction.js injection. The file is a bare IIFE statement; the gstack
   adapter wraps what it is given in `JSON.stringify((...))`, and a statement
   in that position is a syntax error. The injection then fails, no extraction
   functions exist on the page, and every post comes back empty.
3. Arguments to a page function. An arrow written `h => ...` is not recognised
   as a function literal by the adapter, so the handle is never applied — and
   an author filter matching nobody returns zero posts, not an error.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _browse  # noqa: E402
import x_extract  # noqa: E402
import xpost_download  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
EXTRACTION_JS = SCRIPTS.parent / "skills" / "x-post" / "references" / "extraction.js"


class Spy(_browse.BrowsePage):
    """Captures the expression instead of shelling out to $B."""

    def __init__(self, reply="null"):
        self.sent = None
        self.reply = reply

    def _run(self, *args, **kwargs):
        self.sent = args[1] if len(args) > 1 else None
        return self.reply


# ------------------------------------------------------------------ URL parse

@pytest.mark.parametrize("url,expected", [
    ("https://x.com/elonmusk/status/123", ("elonmusk", "123")),
    ("https://twitter.com/elonmusk/status/123", ("elonmusk", "123")),
    ("https://www.x.com/a_b/status/9?s=20&t=x", ("a_b", "9")),
    ("  https://x.com/a/status/1  ", ("a", "1")),
])
def test_status_urls_parse(url, expected):
    assert xpost_download.parse_status_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://x.com/elonmusk",
    "https://x.com/elonmusk/with_replies",
    "https://example.com/elonmusk/status/123",
    "https://x.com/elonmusk/status/notanumber",
    "1234567890",
    "",
    None,
])
def test_non_status_urls_are_refused(url):
    assert xpost_download.parse_status_url(url) == (None, None)


def test_download_url_refuses_a_non_status_url_without_navigating():
    """The refusal must happen BEFORE the page moves — a profile page extracts
    the pinned tweet, which reads as a successful capture of the wrong post."""
    class Unusable:
        def __getattr__(self, name):
            raise AssertionError(f"page.{name} was touched for a non-status URL")

    result = xpost_download.download_url(Unusable(), "https://x.com/someone", "/tmp", "2026-01-01")
    assert "error" in result and "not an X status URL" in result["error"]


# ------------------------------------------------------------------- CLI seam

def test_cli_without_arguments_reports_usage():
    assert xpost_download.main([]) == 2


def test_cli_emits_output_file_as_the_last_stdout_line(monkeypatch, capsys, tmp_path):
    """Callers chain on the final stdout line; anything else there breaks them."""
    monkeypatch.setattr(_browse, "sync_browse_page", _FakeSession)
    monkeypatch.setattr(xpost_download, "download_url", lambda *a, **k: {
        "note": "posts/2026-01-01 @bob - hello.md", "fname": "x.md",
        "status_id": "1", "root_id": "1", "is_thread": True,
        "post_count": 3, "media": 2, "author_name": "Bob", "date": "2026-01-01",
        "member_ids": ["1"],
    })

    rc = xpost_download.main(["https://x.com/bob/status/1", str(tmp_path)])
    out = capsys.readouterr().out.strip().splitlines()

    assert rc == 0
    assert out[-1] == f"OUTPUT_FILE:{os.path.join(str(tmp_path), 'bob', 'posts', '2026-01-01 @bob - hello.md')}"


def test_cli_emits_no_output_file_marker_on_failure(monkeypatch, capsys):
    """A marker on a failed capture sends the caller to summarise nothing."""
    monkeypatch.setattr(_browse, "sync_browse_page", _FakeSession)
    monkeypatch.setattr(xpost_download, "download_url", lambda *a, **k: {"error": "no content"})

    rc = xpost_download.main(["https://x.com/bob/status/1"])
    captured = capsys.readouterr()

    assert rc == 1
    assert "OUTPUT_FILE" not in captured.out
    assert "no content" in captured.err


class _FakeSession:
    """Stands in for `_browse.sync_browse_page()` — no daemon, no browser."""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return object()

    def __exit__(self, *exc):
        return False


# ------------------------------------------------- extraction.js hand-off

def test_injection_is_a_function_literal_the_adapter_can_invoke():
    """Raw extraction.js is a bare IIFE statement. Wrapped in the adapter's
    `JSON.stringify((...))` that is a syntax error, and the injection silently
    produces a page with no `window.__xExtract` at all."""
    assert x_extract._INJECT_JS.startswith("() => {")
    spy = Spy()
    spy.evaluate_sync(x_extract._INJECT_JS)
    assert spy.sent.startswith("JSON.stringify(((() => {")


def test_injection_carries_the_whole_canonical_file():
    """The skill and the scripts must share ONE extractor, not a copy."""
    assert EXTRACTION_JS.read_text() in x_extract._INJECT_JS


def test_author_filter_argument_is_actually_applied():
    """`h => ...` is not recognised as a function literal, so the handle would
    be dropped and the author filter would match nobody — zero posts, no error."""
    spy = Spy(reply="[]")
    spy.evaluate_sync("(h) => window.__xExtract.extractAllByAuthor(h)", "bourboncap")
    assert "bourboncap" in spy.sent


def test_unparenthesised_arrow_with_arguments_is_rejected_not_silently_dropped():
    with pytest.raises(_browse.BrowseError):
        Spy().evaluate_sync("h => window.__xExtract.extractAllByAuthor(h)", "bob")


def test_extraction_requests_original_resolution_media():
    """`name=large` is a downscale; a downscaled chart or screenshot is
    unreadable at exactly the point it matters."""
    js = EXTRACTION_JS.read_text()
    assert "'name=orig'" in js
    assert "'name=large'" not in js
