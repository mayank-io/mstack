"""Tests for the x-account iterator's tab discipline over the gstack browser.

No browser runs here. A fake page stands in for `_browse.SyncBrowsePage` and
records every tab operation, because the failures that matter are about tabs,
not extraction (x-post's unit tests own extraction):

- a post's tab left open accumulates one tab per post in the user's browser;
- control left on the post tab means the next ID scan reads the post page,
  not the profile timeline, and the harvest silently stalls;
- a wrong or missing tab id closes the user's own tab.
"""

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _browse  # noqa: E402
import xaccount_iterate as it  # noqa: E402  (importing must have no side effects)

PROFILE_TAB = 1


class FakePage:
    """The `SyncBrowsePage` surface the iterator uses, over an in-memory tab set."""

    def __init__(self, ids, logged_in=True, unreachable=()):
        self.ids = list(ids)
        self.logged_in = logged_in
        self.unreachable = set(unreachable)
        self.tabs = {PROFILE_TAB: "about:blank"}
        self.active = PROFILE_TAB
        self.next_id = PROFILE_TAB + 1
        self.opened = []      # status URLs, in order
        self.closed = []      # tab ids, in order
        self.scans_off_profile = 0

    @property
    def url(self):
        return self.tabs[self.active]

    def goto(self, url, **_):
        self.tabs[self.active] = url

    def evaluate(self, js, *args):
        if js == it.LOGGED_IN_JS:
            return self.logged_in
        if js == it.COLLECT_IDS_JS:
            if self.active != PROFILE_TAB:
                self.scans_off_profile += 1
            return json.dumps(self.ids)
        return None  # scrollBy

    def wait_for_selector(self, selector, timeout=15000, **_):
        if self.url in self.unreachable:
            raise _browse.BrowseError(f"selector never appeared: {selector}")

    def active_tab(self):
        return self.active

    def new_tab(self, url):
        tab = self.next_id
        self.next_id += 1
        self.tabs[tab] = url
        self.active = tab
        self.opened.append(url)
        return tab

    def switch_tab(self, tab_id):
        assert tab_id in self.tabs, f"switch to closed tab {tab_id}"
        self.active = tab_id

    def close_tab(self, tab_id):
        assert tab_id != PROFILE_TAB, "closed the profile tab"
        del self.tabs[tab_id]
        self.closed.append(tab_id)


def _post(sid, members=()):
    return {"note": f"/n/{sid}.md", "fname": f"{sid}.md", "status_id": sid,
            "date": "2026-10-10", "is_thread": bool(members),
            "post_count": 1 + len(members), "author_name": "Bob",
            "member_ids": list(members)}


@pytest.fixture
def downloads(monkeypatch):
    """Replace x-post's download unit; record which URL each call saw."""
    seen, results = [], {}

    def fake(page, handle, out_dir, day, download_media=True):
        seen.append(page.url)
        sid = page.url.rsplit("/", 1)[-1]
        r = results.get(sid, _post(sid))
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(it.xpost_download, "download_open_post", fake)
    return seen, results


def harvest(page, tmp_path, maxp=10, cfg=None):
    return it.harvest(page, "bob", str(tmp_path), maxp, "2026-10-10",
                      cfg=cfg or it.CFG, sleep=lambda s: None)


def _assert_tabs_clean(page):
    assert set(page.tabs) == {PROFILE_TAB}, f"tabs left open: {page.tabs}"
    assert page.active == PROFILE_TAB
    assert page.scans_off_profile == 0


# ---------------------------------------------------------------- happy path

def test_each_post_opens_in_its_own_tab_and_is_closed(downloads, tmp_path):
    page = FakePage(["11", "12", "13"])
    written = harvest(page, tmp_path)
    assert written == ["11.md", "12.md", "13.md"]
    assert page.opened == [f"https://x.com/bob/status/{i}" for i in ("11", "12", "13")]
    assert page.closed == [2, 3, 4]
    _assert_tabs_clean(page)


def test_download_runs_on_the_post_tab_not_the_profile(downloads, tmp_path):
    seen, _ = downloads
    harvest(FakePage(["11"]), tmp_path)
    assert seen == ["https://x.com/bob/status/11"]


def test_stops_at_max_posts(downloads, tmp_path):
    page = FakePage(["11", "12", "13"])
    assert harvest(page, tmp_path, maxp=2) == ["11.md", "12.md"]
    assert len(page.opened) == 2
    _assert_tabs_clean(page)


def test_thread_members_are_not_opened_again(downloads, tmp_path):
    _, results = downloads
    results["11"] = _post("11", members=["12", "13"])
    page = FakePage(["11", "12", "13", "14"])
    assert harvest(page, tmp_path) == ["11.md", "14.md"]
    assert page.opened == ["https://x.com/bob/status/11", "https://x.com/bob/status/14"]


def test_manifest_is_written(downloads, tmp_path):
    harvest(FakePage(["11"]), tmp_path)
    manifest = json.loads((tmp_path / "bob" / ".x-archive" / "manifest.json").read_text())
    assert manifest["post_count"] == 1


def test_empty_timeline_ends_without_opening_tabs(downloads, tmp_path):
    page = FakePage([])
    assert harvest(page, tmp_path, maxp=3) == []
    assert page.opened == []
    _assert_tabs_clean(page)


# ---------------------------------------------------------------- failure paths

def test_logged_out_raises_before_any_tab(downloads, tmp_path):
    """A logged-out X renders login walls that read as short posts."""
    page = FakePage(["11"], logged_in=False)
    with pytest.raises(it.NotLoggedIn):
        harvest(page, tmp_path)
    assert page.opened == []


def test_download_error_skips_the_post_and_closes_its_tab(downloads, tmp_path):
    _, results = downloads
    results["12"] = {"error": "no status id in url"}
    page = FakePage(["11", "12", "13"])
    assert harvest(page, tmp_path) == ["11.md", "13.md"]
    assert len(page.closed) == 3
    _assert_tabs_clean(page)


def test_unreachable_post_is_skipped_and_its_tab_closed(downloads, tmp_path):
    page = FakePage(["11", "12"], unreachable={"https://x.com/bob/status/11"})
    assert harvest(page, tmp_path) == ["12.md"]
    _assert_tabs_clean(page)


def test_unexpected_error_still_closes_the_tab_and_propagates(downloads, tmp_path):
    _, results = downloads
    results["11"] = RuntimeError("boom")
    page = FakePage(["11"])
    with pytest.raises(RuntimeError, match="boom"):
        harvest(page, tmp_path)
    _assert_tabs_clean(page)


def test_daily_budget_stops_the_harvest(downloads, tmp_path):
    """Budget was charged but never checked before; the governor did nothing."""
    page = FakePage(["11", "12", "13"])
    cfg = {**it.CFG, "daily_render_budget": 1}
    assert harvest(page, tmp_path, maxp=5, cfg=cfg) == ["11.md"]
    assert len(page.opened) == 1


# ---------------------------------------------------------------- CLI

@pytest.mark.parametrize("argv", [[], ["bob", "out"], ["bob", "out", "3", "x"]])
def test_wrong_arg_count_is_a_usage_error(argv, capsys):
    with pytest.raises(SystemExit) as e:
        it.parse_args(argv)
    assert e.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("maxp", ["three", "0", "-1"])
def test_max_posts_must_be_a_positive_int(maxp):
    with pytest.raises(SystemExit) as e:
        it.parse_args(["bob", "out", maxp])
    assert e.value.code == 2


def test_parse_args_happy():
    assert it.parse_args(["bob", "out", "3"]) == ("bob", "out", 3)


def _fake_session(page):
    @contextmanager
    def session():
        yield page
    return session


def test_main_exits_3_when_logged_out(monkeypatch, tmp_path, capsys, downloads):
    monkeypatch.setattr(it, "sync_browse_page", _fake_session(FakePage([], logged_in=False)))
    assert it.main(["bob", str(tmp_path / "out"), "1"]) == it.EXIT_LOGGED_OUT
    assert "gstack" in capsys.readouterr().err


def test_main_returns_0_and_reports_on_stderr(monkeypatch, tmp_path, capsys, downloads):
    monkeypatch.setattr(it, "sync_browse_page", _fake_session(FakePage(["11"])))
    monkeypatch.setattr(it.time, "sleep", lambda s: None)
    assert it.main(["bob", str(tmp_path / "out"), "1"]) == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert "DONE: 1" in out.err
