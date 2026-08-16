"""Governed pilot loop — the safety controls WIRED into a live browse loop.

This is the piece that was missing: Pacer, Budget, detect_abort and
is_challenge exist as tested pure functions, but nothing called them. This
loop calls them, in order, against the live GStack session:

  - a randomized Pacer dwell runs between EVERY browser action,
  - detect_abort runs after EVERY page load / scroll,
  - is_challenge turns a challenge into an immediate hard stop (never retry),
  - Budget charges one render per newly-seen post and stops at the cap,
  - a small max_posts cap bounds the whole pilot regardless of budget.

The loop is deliberately a PILOT: it enumerates IDs from the timeline with
governance, but does not extract/render notes. Its job is to prove the
governor holds against live X before any real harvest scales up. It talks to
the browser only through the `browser` adapter (default: x_browse), so the
whole control flow is unit-testable with a fake browser and a fake clock.
"""
import os

from x_session import Pacer, Budget, detect_abort, is_challenge
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
    sleep=None,
):
    """Run a governed enumeration pilot against the open browser session.

    Args:
        handle: X handle to scroll (no @).
        target_dir: corpus root; state lives under <target_dir>/<handle>/.x-archive.
        day: 'YYYY-MM-DD' string for the budget counter (passed in — the pure
            layer never reads the clock).
        config: dict with scroll_dwell_range, read_dwell_range,
            max_session_minutes, daily_render_budget.
        max_posts: hard cap on distinct posts this pilot will count.
        max_ticks: safety cap on scroll iterations (defaults to max_posts * 4).
        seed: seeds the Pacer for a replayable session.
        browser: the browse adapter (defaults to x_browse); injected for tests.
        sleep: sleep function (defaults to time.sleep); injected for tests.

    Returns a dict describing the outcome: collected IDs, ticks, budget
    charged, and the abort reason + stage if it stopped early.
    """
    if browser is None:
        import x_browse as browser
    if sleep is None:
        import time
        sleep = time.sleep
    if max_ticks is None:
        max_ticks = max_posts * 4

    pacer = Pacer(seed, config)
    state = ArchiveState(os.path.join(target_dir, handle))
    budget = Budget(state, day, config["daily_render_budget"])

    def _abort_now(stage):
        reason = detect_abort(browser.page_text(), browser.current_url())
        if reason is None:
            return None
        return {"stage": stage, "reason": reason, "hard_stop": is_challenge(reason)}

    # Preflight: are we actually on a usable, logged-in session?
    ab = _abort_now("preflight")
    if ab:
        return {"outcome": "aborted", **ab, "collected": []}

    browser.goto(f"https://x.com/{handle}")
    sleep(pacer.read_dwell(500))
    ab = _abort_now("profile_load")
    if ab and ab["hard_stop"]:
        return {"outcome": "aborted", **ab, "collected": []}

    seen = set()
    ticks = 0
    while len(seen) < max_posts and ticks < max_ticks and not budget.exhausted():
        for sid in browser.collect_status_ids():
            if sid not in seen and len(seen) < max_posts:
                seen.add(sid)
                budget.charge(1)  # a rendered post consumes read budget

        browser.scroll()
        sleep(pacer.scroll_dwell())
        ticks += 1

        ab = _abort_now(f"scroll_tick_{ticks}")
        if ab:
            if ab["hard_stop"]:
                return {
                    "outcome": "aborted",
                    **ab,
                    "collected": sorted(seen),
                    "ticks": ticks,
                    "budget_charged": len(seen),
                }
            # Non-challenge (rate_limited): a pilot stops cleanly rather than
            # push a real account. A full run would back off and resume.
            return {
                "outcome": "throttled",
                **ab,
                "collected": sorted(seen),
                "ticks": ticks,
                "budget_charged": len(seen),
            }

    return {
        "outcome": "ok",
        "collected": sorted(seen),
        "ticks": ticks,
        "budget_charged": len(seen),
        "budget_remaining": budget.remaining(),
        "hit_cap": len(seen) >= max_posts,
    }
