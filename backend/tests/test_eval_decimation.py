"""Replaying a clip as a slower device sees it.

The thresholds that still need recalibrating — `kip_tolerance_ms` at 0.80 m/s,
`trunk_tolerance_deg` at 30° — are fitted against velocities, and a velocity is
whatever the sampling rate lets you see. The phone runs at ~21 fps against 30 fps
footage. Fitting those numbers on footage replayed at full rate would fit them to
a signal the app never receives.
"""

from __future__ import annotations

import pytest

from vision.eval.evaluate import FrameDecimator


def kept(source_fps: float, target_fps: float | None, seconds: float = 1.0) -> list[int]:
    """Source frame indices that survive, over `seconds` of footage."""
    decimator = FrameDecimator(source_fps, target_fps)
    count = round(source_fps * seconds)
    return [i for i in range(count) if decimator.keep(i * 1000.0 / source_fps)]


class TestDecimation:
    def test_no_target_keeps_everything(self) -> None:
        assert kept(30.0, None) == list(range(30))

    def test_halving_the_rate_keeps_every_other_frame(self) -> None:
        assert kept(60.0, 30.0) == list(range(0, 60, 2))

    def test_the_phones_real_rate_against_real_footage(self) -> None:
        """30 fps filmed, ~21 fps live — the case this exists for, and it was wrong.

        The ratio is not an integer, so the kept frames cannot be every n-th one.
        What has to hold is the *rate*: about 21 survivors per second of footage.

        The first version anchored the next deadline on the frame that happened
        to survive rather than on a fixed schedule. Each keep pushed the deadline
        a third of an interval too far, the error accumulated, and 21 fps was
        delivered as **15** — every other frame. Nothing downstream would have
        said so: the clip still plays, the count still comes out, and the
        threshold gets fitted to a rate nobody asked for.
        """
        survivors = kept(30.0, 21.0, seconds=4.0)

        assert 20 <= len(survivors) / 4.0 <= 22

    def test_asking_for_more_than_the_source_has_is_a_no_op(self) -> None:
        """Frames cannot be invented, and refusing would be worse than ignoring.

        A session filmed at mixed rates would otherwise fail on its slowest clip
        instead of reporting what it could measure.
        """
        assert kept(30.0, 60.0) == list(range(30))
        assert kept(30.0, 30.0) == list(range(30))

    def test_survivors_keep_their_filming_timestamps(self) -> None:
        """Renumbering them would slow the movement down, not sample it coarsely.

        This is the whole difference between "the same set seen by a slower
        device" and "a different, slower set". A rep taking 2 s must still take
        2 s after decimation, or every velocity in the clip is divided by the
        decimation factor and `kip_tolerance_ms` gets fitted to fiction.
        """
        decimator = FrameDecimator(60.0, 20.0)
        stamps = [t for t in (i * 1000.0 / 60.0 for i in range(120)) if decimator.keep(t)]

        assert stamps[0] == pytest.approx(0.0)
        # 2 s of footage in, still 2 s in — the last survivor sits at the end of
        # the clip, not at a third of it.
        assert stamps[-1] == pytest.approx(2000.0, abs=1000.0 / 20.0)
        assert stamps == sorted(stamps)

    def test_a_still_athlete_is_not_made_to_look_fast(self) -> None:
        """Regression guard on the counter that drives the timestamp.

        The first version derived `t_ms` from the count of *submitted* frames
        rather than the count read from the file. Under decimation that compresses
        the clip: 2 s of footage would be handed to the counter as 0.7 s, every
        velocity would triple, and a dead hang could clear `kip_tolerance_ms`.
        """
        decimator = FrameDecimator(60.0, 20.0)
        submitted = 0
        for i in range(60):
            if decimator.keep(i * 1000.0 / 60.0):
                submitted += 1

        assert submitted < 60
        # One second of footage yields ~20 frames, not 20 frames' worth of time.
        assert 19 <= submitted <= 21
