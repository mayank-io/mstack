"""Proves EVERY safety control is wired into the governed loop — no live X.

A fake browser feeds scripted abort-probe pages and id batches; a fake clock
advances on every sleep so time-based governors (session breaks, the rate
ceiling) are deterministically testable. Each test asserts a specific governor
actually fires.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_pilot import governed_pilot

CFG = {
    "scroll_dwell_range": [2.5, 7.0],
    "read_dwell_range": [8, 35],
    "max_session_minutes": 40,
    "session_break_range": [600, 1800],
    "daily_render_budget": 5500,
    "max_posts_per_hour": 500,
}

NORMAL = ("https://x.com/vedanjanam", "just ordinary tweets here")


class FakeClock:
    """clock() returns current time; sleep() records the dwell and advances."""
    def __init__(self):
        self.t = 0.0
        self.dwells = []
    def now(self):
        return self.t
    def sleep(self, seconds):
        self.dwells.append(seconds)
        self.t += seconds


class FakeBrowser:
    """probe_pages: (url, text) returned on successive detect_abort probes
    (one probe == one page_text()+current_url() pair). Holds the last page
    once the script is exhausted. id_batches: status ids per collect call."""
    def __init__(self, probe_pages, id_batches):
        self._pages = list(probe_pages)
        self._id_batches = list(id_batches)
        self._last = NORMAL
        self.gotos = []
        self.scroll_calls = []
    def page_text(self):
        if self._pages:
            self._last = self._pages.pop(0)
        return self._last[1]
    def current_url(self):
        return self._last[0]
    def goto(self, url):
        self.gotos.append(url)
    def viewport_height(self):
        return 900
    def scroll_by(self, pixels):
        self.scroll_calls.append(pixels)
    def collect_status_ids(self):
        return self._id_batches.pop(0) if self._id_batches else []


def _run(probe_pages, id_batches, tmp_path, **kw):
    clk = FakeClock()
    fb = FakeBrowser(probe_pages, id_batches)
    result = governed_pilot(
        "vedanjanam", str(tmp_path), "2026-08-16", CFG,
        browser=fb, clock=clk.now, sleep=clk.sleep, **kw,
    )
    return result, fb, clk


def test_login_wall_aborts_at_preflight(tmp_path):
    result, fb, clk = _run([("https://x.com/i/flow/login", "sign in")], [], tmp_path)
    assert result["outcome"] == "aborted" and result["reason"] == "login_wall"
    assert fb.gotos == [] and clk.dwells == []

def test_challenge_mid_scroll_hard_stops(tmp_path):
    pages = [NORMAL, NORMAL, ("https://x.com/vedanjanam", "arkose check required")]
    result, fb, clk = _run(pages, [["100"], ["101"]], tmp_path, max_posts=50, max_ticks=5)
    assert result["outcome"] == "aborted" and result["reason"] == "challenge"
    assert result["hard_stop"] is True
    assert len(clk.dwells) >= 2                       # governed before stopping

def test_rate_limit_backs_off_then_recovers(tmp_path):
    # tick1 shows rate_limited, backoff re-probe shows normal -> continue to cap
    pages = [NORMAL, NORMAL, ("https://x.com/vedanjanam", "Rate limit exceeded"),
             NORMAL, NORMAL, NORMAL, NORMAL]
    result, fb, clk = _run(pages, [["100"], ["101"], ["102"]], tmp_path, max_posts=2, max_ticks=5)
    assert result["events"]["backoffs"] >= 1          # backoff fired
    assert result["outcome"] in ("ok", "throttled")
    if result["outcome"] == "ok":
        assert result["hit_cap"] is True              # recovered and finished

def test_rate_limit_gives_up_after_retries(tmp_path):
    # rate_limited persists through all backoff probes -> throttled
    pages = [NORMAL, NORMAL] + [("https://x.com/vedanjanam", "Rate limit exceeded")] * 6
    result, fb, clk = _run(pages, [["100"]], tmp_path, max_posts=50, max_ticks=5)
    assert result["outcome"] == "throttled" and result["reason"] == "rate_limited"
    assert result["events"]["backoffs"] >= 3          # tried 3 backoffs

def test_session_break_fires_after_time_cap(tmp_path):
    # tiny session cap: one read_dwell (~17s) already exceeds it -> break on tick 1
    cfg = dict(CFG, max_session_minutes=0.2)
    clk = FakeClock(); fb = FakeBrowser([NORMAL] * 8, [["1"], ["2"]])
    result = governed_pilot("vedanjanam", str(tmp_path), "2026-08-16", cfg,
                            browser=fb, clock=clk.now, sleep=clk.sleep,
                            max_posts=50, max_ticks=2)
    assert result["events"]["breaks"] >= 1
    # a break-sized idle (600-1800s) actually happened
    assert any(600 <= d <= 1800 for d in clk.dwells)

def test_rate_ceiling_throttles(tmp_path):
    # ceiling of 2/hr; 4 posts arrive within seconds -> throttle wait fires
    cfg = dict(CFG, max_posts_per_hour=2)
    clk = FakeClock(); fb = FakeBrowser([NORMAL] * 10, [["1"], ["2"], ["3"], ["4"]])
    result = governed_pilot("vedanjanam", str(tmp_path), "2026-08-16", cfg,
                            browser=fb, clock=clk.now, sleep=clk.sleep,
                            max_posts=10, max_ticks=5)
    assert result["events"]["throttle_waits"] >= 1

def test_variable_scroll_distance_used(tmp_path):
    result, fb, clk = _run([NORMAL] * 12, [["1"], ["2"], ["3"]], tmp_path,
                           max_posts=3, max_ticks=6)
    forward = [px for px in fb.scroll_calls if px > 0]
    assert forward, "expected forward scrolls"
    assert all(540 <= px <= 1260 for px in forward)   # 0.6..1.4 * 900
    assert len(set(forward)) > 1                       # genuinely varied, not fixed

def test_budget_charged_deduped_capped_and_persisted(tmp_path):
    from x_state import ArchiveState
    id_batches = [["100", "101"], ["101", "102"], ["102", "103", "104"]]
    result, fb, clk = _run([NORMAL] * 12, id_batches, tmp_path, max_posts=3, max_ticks=6)
    assert result["outcome"] == "ok" and result["hit_cap"] is True
    assert result["collected"] == ["100", "101", "102"]
    assert result["budget_charged"] == 3
    st = ArchiveState(os.path.join(str(tmp_path), "vedanjanam"))
    assert st.rendered_today("2026-08-16") == 3        # persisted to disk

def test_backtrack_occurs_over_many_ticks(tmp_path):
    # enough ticks that the ~1/12 backtrack probability should fire at least once
    result, fb, clk = _run([NORMAL] * 60, [[str(i)] for i in range(60)], tmp_path,
                           max_posts=40, max_ticks=50)
    # a backtrack is a negative scroll_by; assert at least one happened
    assert result["events"]["backtracks"] >= 1
    assert any(px < 0 for px in fb.scroll_calls)
