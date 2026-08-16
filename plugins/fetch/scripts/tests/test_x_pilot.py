"""Proves the safety controls are WIRED into the pilot loop — no live browser.

A fake browser feeds scripted pages; a fake clock records every dwell. The
assertions check the governance actually fires: challenges hard-stop, dwells
run between actions, budget charges per post, the cap holds, and a login wall
is caught at preflight.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_pilot import governed_pilot

CONFIG = {
    "scroll_dwell_range": [2.5, 7.0],
    "read_dwell_range": [8, 35],
    "max_session_minutes": 40,
    "daily_render_budget": 5500,
}


class FakeBrowser:
    """Scriptable stand-in for x_browse. `pages` is a list of (url, text) the
    browser 'shows' on each successive detect_abort probe; `id_batches` is the
    list of status-id lists returned on each collect_status_ids call."""

    def __init__(self, pages, id_batches):
        self._pages = list(pages)
        self._id_batches = list(id_batches)
        self.gotos = []
        self.scrolls = 0

    def _advance_page(self):
        # Hold the last page once the script is exhausted (steady state).
        return self._pages.pop(0) if len(self._pages) > 1 else self._pages[0]

    def page_text(self):
        return self._page[1]

    def current_url(self):
        return self._page[0]

    # detect_abort in the loop calls page_text() then current_url() as a pair;
    # advance the scripted page once per probe via a property.
    @property
    def _page(self):
        if not hasattr(self, "_cur") or self._pending_advance:
            self._cur = self._advance_page()
            self._pending_advance = False
        return self._cur

    def goto(self, url):
        self.gotos.append(url)
        self._pending_advance = True

    def scroll(self):
        self.scrolls += 1
        self._pending_advance = True

    def collect_status_ids(self):
        return self._id_batches.pop(0) if self._id_batches else []


class Clock:
    def __init__(self):
        self.dwells = []

    def __call__(self, seconds):
        self.dwells.append(seconds)


NORMAL = ("https://x.com/vedanjanam", "just some ordinary tweets here")


def _run(pages, id_batches, tmp_path, **kw):
    clock = Clock()
    fb = FakeBrowser(pages, id_batches)
    result = governed_pilot(
        "vedanjanam", str(tmp_path), "2026-08-16", CONFIG,
        browser=fb, sleep=clock, **kw,
    )
    return result, fb, clock


def test_login_wall_aborts_at_preflight(tmp_path):
    pages = [("https://x.com/i/flow/login", "sign in to X")]
    result, fb, clock = _run(pages, [], tmp_path)
    assert result["outcome"] == "aborted"
    assert result["reason"] == "login_wall"
    assert fb.gotos == []          # never navigated to the profile
    assert clock.dwells == []      # never dwelled

def test_challenge_mid_scroll_hard_stops(tmp_path):
    # preflight OK, profile OK, first tick OK, second tick shows a challenge
    pages = [NORMAL, NORMAL, NORMAL,
             ("https://x.com/vedanjanam", "arkose verification required")]
    id_batches = [["100", "101"], ["102"]]
    result, fb, clock = _run(pages, id_batches, tmp_path, max_posts=50)
    assert result["outcome"] == "aborted"
    assert result["reason"] == "challenge"
    assert result["hard_stop"] is True
    # governance ran between actions before the stop: at least the profile
    # read dwell + one scroll dwell
    assert len(clock.dwells) >= 2

def test_rate_limit_throttles_not_hard_stop(tmp_path):
    pages = [NORMAL, NORMAL, NORMAL,
             ("https://x.com/vedanjanam", "Rate limit exceeded. Try again later")]
    result, fb, clock = _run(pages, [["100"]], tmp_path, max_posts=50)
    assert result["outcome"] == "throttled"
    assert result["reason"] == "rate_limited"
    assert result["hard_stop"] is False

def test_dwell_runs_between_every_action(tmp_path):
    # 3 clean ticks then steady normal; cap at 3 posts
    pages = [NORMAL] * 8
    id_batches = [["100"], ["101"], ["102"], ["103"]]
    result, fb, clock = _run(pages, id_batches, tmp_path, max_posts=3)
    # one read dwell (profile) + one scroll dwell per tick; all within ranges
    assert clock.dwells[0] >= 8 and clock.dwells[0] <= 35      # read_dwell
    for d in clock.dwells[1:]:
        assert 2.5 <= d <= 7.0                                  # scroll_dwell
    assert len(clock.dwells) >= 2

def test_budget_charged_per_distinct_post_and_cap_holds(tmp_path):
    pages = [NORMAL] * 12
    # duplicates across ticks must NOT double-charge
    id_batches = [["100", "101"], ["101", "102"], ["102", "103", "104"]]
    result, fb, clock = _run(pages, id_batches, tmp_path, max_posts=3)
    assert result["outcome"] == "ok"
    assert result["hit_cap"] is True
    assert result["budget_charged"] == 3            # capped, deduped
    assert result["collected"] == ["100", "101", "102"]
    assert result["budget_remaining"] == 5500 - 3   # persisted via ArchiveState

def test_budget_persists_to_state(tmp_path):
    from x_state import ArchiveState
    pages = [NORMAL] * 12
    _run(pages, [["100", "101", "102"]], tmp_path, max_posts=3)
    # a fresh state handle sees the charge on disk
    st = ArchiveState(os.path.join(str(tmp_path), "vedanjanam"))
    assert st.rendered_today("2026-08-16") == 3
