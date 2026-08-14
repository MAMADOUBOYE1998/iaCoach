"""Subject selection.

The failure this exists for is measured, not imagined: clip `084` gave 1175
frames of a coherent, confidently tracked, upright body whose hands never rose
above its shoulders, on footage annotated as pull-ups. Every biomechanical
threshold was innocent — the wrong body was being measured.

So the tests are about identity, not geometry. Does the track stay on the body
it started on, does it refuse rather than substitute when that body is gone, and
does it report enough for someone to tell a *selection* mistake from a
*detection* one.
"""

from __future__ import annotations

from iacoach.frame import LANDMARK, Landmark
from iacoach.tracking import SubjectTracker, TrackerConfig


def person(x: float, y: float = 0.5, *, size: float = 0.2, visible: float = 1.0):
    """A pose whose torso sits at `(x, y)` with `size` between hip and shoulder.

    Only the four torso landmarks matter to the tracker; the rest is padding it
    never reads, exactly as a real pose's swinging limbs are never read.
    """
    points = [Landmark(0.0, 0.0, 0.0, visible) for _ in range(33)]
    for index in (LANDMARK["LEFT_HIP"], LANDMARK["RIGHT_HIP"]):
        points[index] = Landmark(x, y + size / 2.0, 0.0, visible)
    for index in (LANDMARK["LEFT_SHOULDER"], LANDMARK["RIGHT_SHOULDER"]):
        points[index] = Landmark(x, y - size / 2.0, 0.0, visible)
    return points


class TestAcquisition:
    def test_the_largest_torso_is_chosen(self) -> None:
        tracker = SubjectTracker()

        chosen = tracker.select([person(0.2, size=0.1), person(0.7, size=0.3)])

        assert chosen is not None
        assert chosen.index == 1
        assert chosen.reason == "acquisition"

    def test_no_pose_is_not_an_acquisition(self) -> None:
        tracker = SubjectTracker()

        assert tracker.select([]) is None
        assert tracker.acquisitions == 0

    def test_a_pose_with_invisible_landmarks_cannot_be_acquired(self) -> None:
        """Placing a track on landmarks we do not trust would pin it to noise."""
        tracker = SubjectTracker()

        assert tracker.select([person(0.5, visible=0.1)]) is None


class TestContinuity:
    def test_it_keeps_following_the_body_it_started_on(self) -> None:
        """The regression that matters: a bigger body appearing must not win.

        Acquisition prefers the largest torso. If that preference applied every
        frame, a bystander walking towards the camera would take the track mid
        set — which is `084`'s failure mode, and re-deciding per frame is
        exactly what `num_poses=1` does today.
        """
        tracker = SubjectTracker()
        tracker.select([person(0.3, size=0.2)])

        chosen = tracker.select([person(0.32, size=0.2), person(0.8, size=0.5)])

        assert chosen is not None
        assert chosen.index == 0
        assert chosen.reason == "suivi"

    def test_a_body_that_teleports_is_a_different_body(self) -> None:
        tracker = SubjectTracker()
        tracker.select([person(0.2)])

        assert tracker.select([person(0.9)]) is None
        assert tracker.dropped_frames == 1

    def test_a_neighbour_of_the_wrong_size_is_refused(self) -> None:
        """Catches what the centre distance misses.

        Someone standing just behind the athlete has a torso centre a few
        percent away — well inside `max_centre_jump` — and a visibly smaller
        torso. Distance alone would hand them the track.
        """
        tracker = SubjectTracker()
        tracker.select([person(0.5, size=0.3)])

        assert tracker.select([person(0.52, size=0.1)]) is None

    def test_a_dropped_frame_is_dropped_not_substituted(self) -> None:
        """`None`, never the nearest available pose.

        Same rule as everywhere else in the analysis stage: a missing
        measurement is honest, a substituted one is a fabricated rep.
        """
        tracker = SubjectTracker()
        tracker.select([person(0.2)])

        assert tracker.select([person(0.9)]) is None

    def test_the_athlete_is_recovered_after_a_brief_occlusion(self) -> None:
        tracker = SubjectTracker()
        tracker.select([person(0.5)])
        for _ in range(3):
            tracker.select([])

        chosen = tracker.select([person(0.52)])

        assert chosen is not None
        assert tracker.acquisitions == 1, "toujours la même piste, pas une nouvelle"

    def test_a_long_absence_starts_a_new_track(self) -> None:
        """Holding the old position forever would reject the athlete's return.

        The counter is that a new track may be a new person, so the
        re-acquisition is counted rather than silent.
        """
        tracker = SubjectTracker(TrackerConfig(reacquire_after=3))
        tracker.select([person(0.2)])
        for _ in range(3):
            tracker.select([person(0.9)])

        chosen = tracker.select([person(0.9)])

        assert chosen is not None
        assert tracker.acquisitions == 2


class TestWhatItReports:
    """Separates a selection mistake from a detection one.

    On `084` the two need opposite fixes and the rep count shows neither. If
    only one pose was ever offered, no policy here could have changed the
    outcome and the athlete was simply never detected.
    """

    def test_one_pose_throughout_means_selection_was_never_in_play(self) -> None:
        tracker = SubjectTracker()
        for x in (0.5, 0.51, 0.52):
            tracker.select([person(x)])

        assert tracker.max_candidates == 1
        assert tracker.frames_with_choice == 0

    def test_competing_poses_are_counted(self) -> None:
        tracker = SubjectTracker()
        tracker.select([person(0.5), person(0.8, size=0.1)])
        tracker.select([person(0.51), person(0.81, size=0.1)])

        assert tracker.max_candidates == 2
        assert tracker.frames_with_choice == 2
