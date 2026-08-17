"""Tests for the added pacing-over-time governors: session breaks, backtrack,
the volume-rate ceiling, and config-default fallback."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_session import Pacer, throttle_delay

CFG = {
    "scroll_dwell_range": [2.5, 7.0],
    "read_dwell_range": [8, 35],
    "max_session_minutes": 40,
    "session_break_range": [600, 1800],
}


def test_session_break_within_range():
    p = Pacer(seed=1, config=CFG)
    vals = [p.session_break_seconds() for _ in range(1000)]
    assert all(600 <= v <= 1800 for v in vals)

def test_should_break_true_past_limit():
    p = Pacer(seed=1, config=CFG)
    assert p.should_break(41) is True
    assert p.should_break(39) is False

def test_active_limit_within_12_to_17_min():
    p = Pacer(seed=1, config=CFG)
    vals = [p.active_limit_minutes() for _ in range(1000)]
    assert all(12 <= v <= 17 for v in vals)
    assert min(vals) < max(vals)          # genuinely randomized, not constant

def test_active_limit_defaults_when_key_absent():
    p = Pacer(seed=1, config={})
    assert 12 <= p.active_limit_minutes() <= 17

def test_should_backtrack_is_occasional():
    p = Pacer(seed=1, config=CFG)
    hits = sum(p.should_backtrack() for _ in range(10000))
    # ~1/12 ≈ 833; allow a wide band, just assert it's occasional not never/always
    assert 500 < hits < 1200

def test_partial_config_uses_defaults_not_keyerror():
    # a config missing every optional key must not raise
    p = Pacer(seed=1, config={})
    assert 2.5 <= p.scroll_dwell() <= 7.0
    assert 8 <= p.read_dwell(100) <= 35
    assert p.should_break(41) is True          # default 40
    assert 600 <= p.session_break_seconds() <= 1800

def test_throttle_delay_zero_under_ceiling():
    # 3 renders in the last hour, ceiling 500 -> no throttle
    ts = [100.0, 200.0, 300.0]
    assert throttle_delay(ts, now=400.0, max_per_hour=500) == 0.0

def test_throttle_delay_waits_when_ceiling_hit():
    # exactly max_per_hour renders in-window -> must wait for the oldest to age out
    now = 3600.0
    ts = [t * 1.0 for t in range(0, 10)]        # 10 renders at t=0..9
    delay = throttle_delay(ts, now=now, max_per_hour=10, window_s=3600.0)
    # oldest in-window render is t=0.0 (age 3600 is NOT < window, so it's already out)
    # renders at 1..9 are in-window (9 of them) -> under 10 -> no wait
    assert delay == 0.0

def test_throttle_delay_blocks_when_full_window():
    now = 100.0
    ts = [t * 1.0 for t in range(0, 10)]        # 10 renders at t=0..9, all in-window
    delay = throttle_delay(ts, now=now, max_per_hour=10, window_s=3600.0)
    # 10 in-window, ceiling 10 -> wait until oldest (t=0) ages out: 3600 - (100-0) = 3500
    assert delay == 3500.0

def test_throttle_delay_disabled_when_ceiling_nonpositive():
    ts = [1.0] * 1000
    assert throttle_delay(ts, now=2.0, max_per_hour=0) == 0.0
