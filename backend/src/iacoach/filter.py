"""One-Euro filter.

Mirrors ``web/src/pose/filter.ts`` exactly — both implementations are checked
against the same fixtures.

Why not a moving average: a 5-frame mean at 30 fps adds ~80 ms of lag and
flattens the angular-velocity peaks, which are the fatigue signal we most want
to keep. The One-Euro filter adapts its cutoff to the signal's own speed, so it
smooths a still limb hard and a fast one barely at all — low jitter at rest, low
lag in movement, which is the trade a rep counter actually needs.

Reference: Casiez, Roussel & Vogel, "1e Filter" (CHI 2012).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Tuned for joint angles in degrees at 25-60 fps. Identical values live in the
# TypeScript mirror; changing one without the other breaks conformance.
DEFAULT_MIN_CUTOFF = 1.0
DEFAULT_BETA = 0.05
DEFAULT_DERIVATIVE_CUTOFF = 1.0


def _alpha(cutoff_hz: float, dt_s: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt_s)


@dataclass
class OneEuroFilter:
    """Stateful, single-channel. One instance per filtered signal."""

    min_cutoff: float = DEFAULT_MIN_CUTOFF
    beta: float = DEFAULT_BETA
    derivative_cutoff: float = DEFAULT_DERIVATIVE_CUTOFF

    _x_hat: float | None = None
    _dx_hat: float = 0.0
    _t_prev_ms: float | None = None

    def reset(self) -> None:
        self._x_hat = None
        self._dx_hat = 0.0
        self._t_prev_ms = None

    def filter(self, value: float, t_ms: float) -> float:
        if self._x_hat is None or self._t_prev_ms is None:
            self._x_hat = value
            self._dx_hat = 0.0
            self._t_prev_ms = t_ms
            return value

        dt_s = (t_ms - self._t_prev_ms) / 1000.0
        if dt_s <= 0.0:
            # Duplicate or out-of-order timestamp: hold the last estimate rather
            # than dividing by zero or letting a stale sample move the output.
            return self._x_hat

        dx = (value - self._x_hat) / dt_s
        self._dx_hat = (
            _alpha(self.derivative_cutoff, dt_s) * dx
            + (1.0 - _alpha(self.derivative_cutoff, dt_s)) * self._dx_hat
        )

        cutoff = self.min_cutoff + self.beta * abs(self._dx_hat)
        a = _alpha(cutoff, dt_s)
        self._x_hat = a * value + (1.0 - a) * self._x_hat
        self._t_prev_ms = t_ms
        return self._x_hat


__all__ = [
    "DEFAULT_BETA",
    "DEFAULT_DERIVATIVE_CUTOFF",
    "DEFAULT_MIN_CUTOFF",
    "OneEuroFilter",
]
