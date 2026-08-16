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


def test_budget_charges_and_persists(tmp_path):
    from x_session import Budget
    from x_state import ArchiveState
    st = ArchiveState(str(tmp_path))
    b = Budget(st, "2026-08-16", limit=5500)
    b.charge(10)
    assert b.remaining() == 5490
    # a fresh Budget over the same state sees the persisted charge
    assert Budget(ArchiveState(str(tmp_path)), "2026-08-16", 5500).remaining() == 5490

def test_budget_exhausted_at_limit(tmp_path):
    from x_session import Budget
    from x_state import ArchiveState
    b = Budget(ArchiveState(str(tmp_path)), "2026-08-16", limit=5)
    b.charge(5)
    assert b.exhausted() is True

def test_detect_abort_login_wall():
    from x_session import detect_abort
    assert detect_abort("", "https://x.com/i/flow/login") == "login_wall"

def test_detect_abort_rate_limit():
    from x_session import detect_abort
    assert detect_abort("Rate limit exceeded", "https://x.com/vedanjanam") == "rate_limited"

def test_detect_abort_challenge():
    from x_session import detect_abort
    assert detect_abort("Something went wrong. Try reloading.", "https://x.com/x") == "interstitial"

def test_detect_abort_none_on_normal_page():
    from x_session import detect_abort
    assert detect_abort("Just some tweets here", "https://x.com/vedanjanam") is None

def test_detect_abort_ignores_captcha_in_normal_tweet():
    from x_session import detect_abort
    # bare "captcha" in normal tweet should NOT trigger abort
    assert detect_abort("this captcha is impossible lol", "https://x.com/vedanjanam") is None

def test_detect_abort_ignores_third_party_suspension_talk():
    from x_session import detect_abort
    # third-person "account suspended" in normal tweet should NOT trigger abort
    assert detect_abort("his account was suspended last week, wild", "https://x.com/vedanjanam") is None

def test_detect_abort_still_catches_real_lock():
    from x_session import detect_abort
    # first/second-person locked phrase SHOULD trigger abort
    assert detect_abort("your account has been locked", "https://x.com/vedanjanam") == "locked"


def test_backoff_capped_at_three():
    from x_session import backoff_delays
    assert len(backoff_delays(attempts=3, seed=1)) == 3

def test_backoff_is_increasing_in_expectation():
    from x_session import backoff_delays
    d = backoff_delays(attempts=3, seed=1)
    assert d[0] <= d[2]  # exponential base grows

def test_challenge_reasons_are_not_retryable():
    from x_session import is_challenge
    assert is_challenge("login_wall") is True
    assert is_challenge("interstitial") is True
    assert is_challenge("rate_limited") is False  # a throttle, backoff is fine
