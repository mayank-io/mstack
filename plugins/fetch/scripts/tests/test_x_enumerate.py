import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from x_enumerate import should_stop_incremental, next_window

A = "1997633559859790018"
B = "1997633594659836065"   # after A
C = "2020489596505592084"   # much later
PIN = "1000000000000000000" # oldest, pinned to top

def test_no_stop_on_single_known_id():
    # first node known but only one — must NOT stop (could be a lone repost)
    assert should_stop_incremental([C], {C}, pinned_id=None) is False

def test_stop_on_two_consecutive_known():
    assert should_stop_incremental([C, B], {C, B}, pinned_id=None) is True

def test_pinned_known_post_does_not_trigger_stop():
    # timeline leads with a pinned, already-known post, then NEW posts
    assert should_stop_incremental([PIN, C], {PIN}, pinned_id=PIN) is False

def test_pinned_excluded_but_two_real_known_still_stops():
    assert should_stop_incremental([PIN, C, B], {PIN, C, B}, pinned_id=PIN) is True

def test_window_halves_on_overflow():
    span, _ = next_window(prev_start="2026-01-01", prev_result_count=100, overflow_at=100)
    assert span == 15  # 30 -> 15

def test_window_widens_when_sparse():
    span, _ = next_window(prev_start="2026-01-01", prev_result_count=2, overflow_at=100)
    assert span == 60  # 30 -> 60
