"""Session governor pacing model (Task 15, design §8.2).

`Pacer` produces the dwell times, scroll fractions, and break decisions that
drive human-plausible pacing for an archive session. All randomness is drawn
from a private `random.Random` instance seeded at construction, so a given
seed always reproduces the same sequence of draws (required for tests and
for replaying a session deterministically).
"""

import random

# scroll_dwell(): lognormal draw normalized into the configured range, then
# clamped. mu=0 puts the underlying lognormal's median at 1.0; sigma=0.45
# controls spread/skew; dividing by 2.6 before scaling keeps the ceiling
# clamp rare (~1-2% of draws) while still preserving right skew (mean >
# median) after clamping. Tuned empirically across multiple seeds.
_SCROLL_MU = 0.0
_SCROLL_SIGMA = 0.45
_SCROLL_DIVISOR = 2.6

# read_dwell(): a length term (sqrt growth, capped so extreme lengths don't
# dominate) plus gaussian noise, clamped to the configured range.
_READ_LENGTH_CAP = 3000
_READ_LENGTH_SCALE = 0.45
_READ_NOISE_SIGMA = 2.5

# scroll_fraction(): uniform draw within this fixed range.
_SCROLL_FRACTION_RANGE = (0.6, 1.4)

# Fallback defaults when a partial config omits a key (design §8.4). Callers
# normally pass a full config; these keep a partial config from raising.
_DEFAULT_SCROLL_DWELL = (2.5, 7.0)
_DEFAULT_READ_DWELL = (8.0, 35.0)
_DEFAULT_MAX_SESSION_MINUTES = 40
_DEFAULT_SESSION_BREAK = (600.0, 1800.0)  # 10-30 min idle break
_DEFAULT_SESSION_ACTIVE = (12.0, 17.0)    # break after 12-17 min of activity

# should_backtrack(): probability of a short re-read scroll-up per tick.
_BACKTRACK_PROB = 1.0 / 12.0


class Pacer:
    """Seeded pacing model for a single archive session.

    Args:
        seed: seeds a private `random.Random` instance. Same seed -> same
            sequence of draws across all methods.
        config: dict with keys `scroll_dwell_range` ([lo, hi] seconds),
            `read_dwell_range` ([lo, hi] seconds), and
            `max_session_minutes` (float/int).
    """

    def __init__(self, seed: int, config: dict):
        self._rng = random.Random(seed)
        self._config = config

    def scroll_dwell(self) -> float:
        """Right-skewed dwell time within config['scroll_dwell_range']."""
        lo, hi = self._config.get("scroll_dwell_range", _DEFAULT_SCROLL_DWELL)
        span = hi - lo
        raw = self._rng.lognormvariate(_SCROLL_MU, _SCROLL_SIGMA)
        scaled = lo + (raw / _SCROLL_DIVISOR) * span
        return min(max(scaled, lo), hi)

    def read_dwell(self, content_len: int) -> float:
        """Dwell time within config['read_dwell_range'], scaled by length."""
        lo, hi = self._config.get("read_dwell_range", _DEFAULT_READ_DWELL)
        capped_len = min(max(content_len, 0), _READ_LENGTH_CAP)
        length_term = (capped_len ** 0.5) * _READ_LENGTH_SCALE
        noise = self._rng.gauss(0, _READ_NOISE_SIGMA)
        raw = lo + length_term + noise
        return min(max(raw, lo), hi)

    def scroll_fraction(self) -> float:
        """Fraction of a viewport scrolled per action, in [0.6, 1.4]."""
        lo, hi = _SCROLL_FRACTION_RANGE
        return self._rng.uniform(lo, hi)

    def should_break(self, minutes_active: float) -> bool:
        """True once minutes_active exceeds config['max_session_minutes']."""
        return minutes_active > self._config.get(
            "max_session_minutes", _DEFAULT_MAX_SESSION_MINUTES)

    def session_break_seconds(self) -> float:
        """A randomized long idle break, within config['session_break_range']
        (default 10-30 min). Called when the active window elapses so the
        session has human-shaped rest gaps, not just per-action jitter (§8.2)."""
        lo, hi = self._config.get("session_break_range", _DEFAULT_SESSION_BREAK)
        return self._rng.uniform(lo, hi)

    def active_limit_minutes(self) -> float:
        """A fresh randomized active-window length (minutes) drawn per cycle
        from config['session_active_range'] (default 12-17 min). Redrawing it
        after every break varies session length instead of a fixed cadence,
        which is itself more human than breaking on the exact same clock."""
        lo, hi = self._config.get("session_active_range", _DEFAULT_SESSION_ACTIVE)
        return self._rng.uniform(lo, hi)

    def should_backtrack(self) -> bool:
        """Occasionally True (~1 in 12) to trigger a short scroll-up + pause,
        mimicking a human re-reading (design §8.2)."""
        return self._rng.random() < _BACKTRACK_PROB


class Budget:
    """Per-day render budget backed by durable state (Task 16, design §8.4).

    Delegates all counting to `state` (an `x_state.ArchiveState`), so the
    budget is enforced in code across process restarts rather than relying
    on in-session discipline: a fresh `Budget` constructed over the same
    state and day sees any prior charges.

    Args:
        state: an `x_state.ArchiveState` instance.
        day: calendar day key (e.g. "2026-08-16") the budget applies to.
        limit: maximum renders allowed for `day`.
    """

    def __init__(self, state, day: str, limit: int):
        self._state = state
        self._day = day
        self._limit = limit

    def remaining(self) -> int:
        """Renders left for the day: limit minus what's already persisted."""
        return self._limit - self._state.rendered_today(self._day)

    def charge(self, n: int = 1) -> None:
        """Persist `n` more renders against the day via the state layer."""
        self._state.bump_rendered(self._day, n)

    def exhausted(self) -> bool:
        """True once remaining() has hit zero or gone negative."""
        return self.remaining() <= 0


def throttle_delay(timestamps, now, max_per_hour, window_s=3600.0):
    """Seconds to sleep to keep the render rate under `max_per_hour`.

    Per-action jitter defeats timing-regularity detection but does nothing
    about raw VOLUME per unit time (design §8.1) — sustained thousands/hour is
    a bot shape no matter how well-spaced each action is. This is the ceiling
    that keeps throughput human-shaped.

    Given the timestamps (seconds) of recent renders and the current time,
    returns 0 if fewer than `max_per_hour` renders fall inside the trailing
    `window_s`; otherwise the seconds until the oldest in-window render ages
    out, at which point one more render is allowed. Pure — the caller supplies
    `now`, so nothing here reads the clock.
    """
    if max_per_hour <= 0:
        return 0.0
    recent = [t for t in timestamps if now - t < window_s]
    if len(recent) < max_per_hour:
        return 0.0
    return max(0.0, window_s - (now - min(recent)))


# detect_abort(): ordered checks against the design §8.3 abort-reason list.
# Order matters — a login-wall URL takes precedence over any page text, and
# challenge/interstitial/rate-limit/locked are checked in this fixed order
# so a page matching multiple markers still resolves deterministically.
# Note: page_text is expected to be visible rendered text; id="challenge is a best-effort
# DOM-fragment fallback marker and should not be relied upon as the sole challenge signal.
_CHALLENGE_MARKERS = ("arkose", "id=\"challenge")
_INTERSTITIAL_MARKER = "Something went wrong. Try reloading."
_RATE_LIMIT_MARKERS = ("rate limit exceeded",)
_LOCKED_MARKERS = ("unusual activity", "your account has been locked")


def detect_abort(page_text: str, url: str) -> str | None:
    """Classify a page as an abort condition, or None if it looks normal.

    Args:
        page_text: rendered page text (or empty string) to scan.
        url: current page URL.

    Returns:
        One of "login_wall", "challenge", "interstitial", "rate_limited",
        "locked", or None if no abort condition is detected.
    """
    if "/i/flow/login" in url:
        return "login_wall"

    lower = page_text.lower()

    if any(marker in lower for marker in _CHALLENGE_MARKERS):
        return "challenge"

    if _INTERSTITIAL_MARKER in page_text:
        return "interstitial"

    if any(marker in lower for marker in _RATE_LIMIT_MARKERS):
        return "rate_limited"

    if any(marker in lower for marker in _LOCKED_MARKERS):
        return "locked"

    return None


# backoff_delays(): exponential backoff with full jitter (design §8.3), used
# when detect_abort() returns "rate_limited" — a throttle, not a hard
# challenge, so retrying after a randomized delay is safe.
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_ATTEMPTS = 3


def backoff_delays(attempts: int, seed: int) -> list[float]:
    """Exponential-with-full-jitter backoff delays, capped at 3 entries.

    Args:
        attempts: number of delays requested (capped at 3).
        seed: seeds a private `random.Random` instance — deterministic,
            never the global `random` module or a time/urandom source.

    Returns:
        A list of up to 3 delays in seconds. Entry i is drawn uniformly
        from [0, base * 2**i), so delays increase in expectation even
        though any single draw may not exceed the previous one.
    """
    rng = random.Random(seed)
    n = min(max(attempts, 0), _BACKOFF_MAX_ATTEMPTS)
    return [rng.uniform(0, _BACKOFF_BASE_SECONDS * (2 ** i)) for i in range(n)]


# is_challenge(): the non-retryable subset of detect_abort()'s reasons
# (design §8.3). "rate_limited" is deliberately excluded — it's a throttle
# that backoff_delays() + retry can recover from. Retrying through any of
# these four escalates a soft limit into a lock, so the harvester must
# checkpoint and hard-stop instead.
_CHALLENGE_REASONS = {"login_wall", "interstitial", "challenge", "locked"}


def is_challenge(abort_reason: str) -> bool:
    """True if `abort_reason` (a detect_abort() return value) is non-retryable."""
    return abort_reason in _CHALLENGE_REASONS
