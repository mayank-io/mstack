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
        lo, hi = self._config["scroll_dwell_range"]
        span = hi - lo
        raw = self._rng.lognormvariate(_SCROLL_MU, _SCROLL_SIGMA)
        scaled = lo + (raw / _SCROLL_DIVISOR) * span
        return min(max(scaled, lo), hi)

    def read_dwell(self, content_len: int) -> float:
        """Dwell time within config['read_dwell_range'], scaled by length."""
        lo, hi = self._config["read_dwell_range"]
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
        return minutes_active > self._config["max_session_minutes"]
