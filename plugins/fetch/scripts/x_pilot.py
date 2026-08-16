"""Governed harvest/pilot loop — ALL safety controls wired into a live loop.

The Phase-1 controls existed as tested pure functions but nothing called
them. This loop calls every one, against the live GStack session, in order:

  Per-action jitter
  - Pacer.scroll_dwell()  between every scroll
  - Pacer.read_dwell()    on profile load
  - Pacer.scroll_fraction() -> variable scroll DISTANCE (not a fixed jump)
  - Pacer.should_backtrack() -> occasional short scroll-up + pause (re-read)

  Volume / time shape (the signals per-action jitter does NOT cover, §8.1)
  - throttle_delay()      caps renders/hour so raw volume stays human-shaped
  - Pacer.should_break()  -> Pacer.session_break_seconds() long idle every
                             max_session_minutes of activity

  Stop / recover
  - detect_abort()        after every page load / scroll
  - is_challenge()        -> immediate hard stop, never retried
  - backoff_delays()      on rate_limited: jittered retries, then stop
  - Budget                one render per distinct post, persisted, + hard cap
  - login-wall preflight  refuses to start on an unusable session

Talks to the browser only through the injected `browser` adapter and the
injected `clock`/`sleep`, so the whole control flow is unit-testable with a
fake browser and a fake clock — no live X.
"""
import os

from x_session import (
    Pacer, Budget, detect_abort, is_challenge, backoff_delays, throttle_delay,
)
from x_state import ArchiveState


def governed_pilot(
    handle,
    target_dir,
    day,
    config,
    *,
    max_posts=12,
    max_ticks=None,
    seed=1,
    browser=None,
    clock=None,
    sleep=None,
):
    """Run a fully-governed enumeration loop against the open browser session.

    config keys used: scroll_dwell_range, read_dwell_range, max_session_minutes,
    session_break_range, daily_render_budget, max_posts_per_hour.

    Returns a dict describing the outcome, the governors that fired
    (breaks taken, throttle waits, backoffs, backtracks), and the collected IDs.
    """
    if browser is None:
        import x_browse as browser
    if clock is None:
        import time
        clock = time.monotonic
    if sleep is None:
        import time
        sleep = time.sleep
    if max_ticks is None:
        max_ticks = max_posts * 6

    pacer = Pacer(seed, config)
    state = ArchiveState(os.path.join(target_dir, handle))
    budget = Budget(state, day, config.get("daily_render_budget", 5500))
    max_per_hour = config.get("max_posts_per_hour", 500)

    render_ts = []            # clock() timestamp per rendered post (rate ceiling)
    events = {"breaks": 0, "throttle_waits": 0, "backoffs": 0, "backtracks": 0}
    last_break_at = clock()

    def _probe(stage):
        reason = detect_abort(browser.page_text(), browser.current_url())
        if reason is None:
            return None
        return {"stage": stage, "reason": reason, "hard_stop": is_challenge(reason)}

    def _result(outcome, seen, ticks, extra=None):
        r = {
            "outcome": outcome,
            "collected": sorted(seen),
            "ticks": ticks,
            "budget_charged": len(seen),
            "budget_remaining": budget.remaining(),
            "events": events,
        }
        if extra:
            r.update(extra)
        return r

    # Preflight: usable, logged-in session?
    ab = _probe("preflight")
    if ab:
        return _result("aborted", set(), 0, ab)

    browser.goto(f"https://x.com/{handle}")
    sleep(pacer.read_dwell(500))
    ab = _probe("profile_load")
    if ab and ab["hard_stop"]:
        return _result("aborted", set(), 0, ab)

    seen = set()
    ticks = 0
    while len(seen) < max_posts and ticks < max_ticks and not budget.exhausted():
        # 1. collect + charge budget for new posts; record render time
        for sid in browser.collect_status_ids():
            if sid not in seen and len(seen) < max_posts:
                seen.add(sid)
                budget.charge(1)
                render_ts.append(clock())

        # 2. volume ceiling: sleep if we'd exceed renders/hour
        wait = throttle_delay(render_ts, clock(), max_per_hour)
        if wait > 0:
            events["throttle_waits"] += 1
            sleep(wait)

        # 3. variable-distance scroll (+ occasional backtrack re-read)
        vh = browser.viewport_height()
        browser.scroll_by(int(pacer.scroll_fraction() * vh))
        if pacer.should_backtrack():
            events["backtracks"] += 1
            browser.scroll_by(-int(0.3 * vh))
            sleep(pacer.scroll_dwell())
        sleep(pacer.scroll_dwell())
        ticks += 1

        # 4. abort check with backoff-and-recover on throttle
        ab = _probe(f"scroll_tick_{ticks}")
        if ab:
            if ab["hard_stop"]:
                return _result("aborted", seen, ticks, ab)
            # rate_limited: jittered backoff, then re-check; give up after retries
            recovered = False
            for delay in backoff_delays(3, seed + ticks):
                events["backoffs"] += 1
                sleep(delay)
                ab2 = _probe(f"backoff_{ticks}")
                if ab2 is None:
                    recovered = True
                    break
                if ab2["hard_stop"]:
                    return _result("aborted", seen, ticks, ab2)
            if not recovered:
                return _result("throttled", seen, ticks, ab)

        # 5. session break: long idle every max_session_minutes of activity
        minutes_active = (clock() - last_break_at) / 60.0
        if pacer.should_break(minutes_active):
            events["breaks"] += 1
            sleep(pacer.session_break_seconds())
            last_break_at = clock()

    return _result("ok", seen, ticks, {"hit_cap": len(seen) >= max_posts})
