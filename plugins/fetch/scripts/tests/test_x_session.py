import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_session import Pacer

CFG = {"scroll_dwell_range": [2.5, 7.0], "read_dwell_range": [8, 35],
       "max_session_minutes": 40}

def test_scroll_dwell_within_range():
    pacer = Pacer(seed=1, config=CFG)
    vals = [pacer.scroll_dwell() for _ in range(1000)]
    assert all(2.5 <= v <= 7.0 for v in vals)

def test_scroll_dwell_is_right_skewed():
    pacer = Pacer(seed=1, config=CFG)
    vals = [pacer.scroll_dwell() for _ in range(2000)]
    mean = sum(vals) / len(vals)
    median = sorted(vals)[len(vals)//2]
    assert mean > median  # right skew: tail pulls mean above median

def test_read_dwell_scales_with_length():
    pacer = Pacer(seed=1, config=CFG)
    short = sum(pacer.read_dwell(50) for _ in range(500)) / 500
    long = sum(pacer.read_dwell(2000) for _ in range(500)) / 500
    assert long > short
    assert all(8 <= pacer.read_dwell(n) <= 35 for n in (0, 100, 5000))

def test_should_break_past_session_limit():
    pacer = Pacer(seed=1, config=CFG)
    assert pacer.should_break(41) is True
    assert pacer.should_break(10) is False

def test_seeded_pacer_is_deterministic():
    a = [Pacer(seed=7, config=CFG).scroll_dwell() for _ in range(5)]
    b = [Pacer(seed=7, config=CFG).scroll_dwell() for _ in range(5)]
    assert a == b
