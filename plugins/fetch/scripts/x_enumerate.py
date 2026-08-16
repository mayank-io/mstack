"""Enumeration loop — Strategy S + T with pinned-post handling.

Pure, offline decision helpers only (design §7.1 W2). The async browser
driver is implemented in the browser-integration phase; see the stub at
the bottom of this module.
"""

DEFAULT_SPAN_DAYS = 30


def should_stop_incremental(seen_ids, known, pinned_id=None):
    """Stop only after two consecutive known IDs, ignoring the pinned post.
    Prevents the pinned-post trap (design §7.1 W2)."""
    real = [i for i in seen_ids if i != pinned_id]
    run = 0
    for sid in real:
        if sid in known:
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


def next_window(prev_start, prev_result_count, overflow_at, span_days=DEFAULT_SPAN_DAYS):
    """Adapt the enumeration window: halve span on overflow, widen when sparse."""
    if prev_result_count >= overflow_at:
        return max(1, span_days // 2), prev_result_count
    if prev_result_count < overflow_at // 10:
        return span_days * 2, prev_result_count
    return span_days, prev_result_count


async def enumerate_account(page, handle, state, strategy):
    """Live browser enumeration driver — implemented in the browser-integration phase.
    Uses should_stop_incremental() and next_window() above."""
    raise NotImplementedError("enumerate_account is implemented in the browser-integration phase")
