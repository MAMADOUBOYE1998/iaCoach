"""One-Euro filter tests. Mirrored by ``web/src/pose/filter.test.ts``."""

from __future__ import annotations

import pytest

from iacoach.filter import OneEuroFilter


def _feed(values: list[float], *, step_ms: float = 1000.0 / 30.0) -> list[float]:
    f = OneEuroFilter()
    return [f.filter(v, i * step_ms) for i, v in enumerate(values)]


class TestOneEuro:
    def test_first_sample_passes_through(self) -> None:
        """No warm-up ramp: the first reading is the best estimate available."""
        assert OneEuroFilter().filter(123.5, 0.0) == pytest.approx(123.5)

    def test_converges_on_a_constant_signal(self) -> None:
        out = _feed([90.0] * 40)
        assert out[-1] == pytest.approx(90.0, abs=1e-6)

    def test_attenuates_jitter_at_rest(self) -> None:
        noisy = [100.0 + (2.0 if i % 2 else -2.0) for i in range(60)]
        out = _feed(noisy)
        tail = out[30:]
        assert max(tail) - min(tail) < 2.0  # input swings 4 degrees peak to peak

    def test_tracks_a_fast_ramp_with_little_lag(self) -> None:
        """The reason this filter exists: a moving average would lag here, and
        the angular-velocity peak it flattens is the fatigue signal."""
        ramp = [40.0 + 4.0 * i for i in range(30)]
        out = _feed(ramp)
        lag = ramp[-1] - out[-1]
        assert lag < 8.0

    def test_lags_less_than_a_five_frame_moving_average(self) -> None:
        ramp = [40.0 + 4.0 * i for i in range(30)]
        one_euro = _feed(ramp)[-1]
        moving_average = sum(ramp[-5:]) / 5.0
        assert abs(ramp[-1] - one_euro) < abs(ramp[-1] - moving_average)

    def test_repeated_timestamp_holds_the_estimate(self) -> None:
        """Duplicate timestamps happen when a frame is re-submitted; dividing by
        a zero dt would produce an infinity that poisons every later sample."""
        f = OneEuroFilter()
        f.filter(100.0, 0.0)
        first = f.filter(120.0, 33.0)
        held = f.filter(999.0, 33.0)
        assert held == pytest.approx(first)

    def test_reset_clears_state(self) -> None:
        f = OneEuroFilter()
        for i in range(20):
            f.filter(100.0, i * 33.0)
        f.reset()
        assert f.filter(10.0, 0.0) == pytest.approx(10.0)
