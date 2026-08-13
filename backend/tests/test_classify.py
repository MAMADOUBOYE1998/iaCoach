"""Exercise classification.

The postures below are **synthetic**: limb lengths and joint angles assembled by
hand, not captured. They lock the geometry the rules read and they lock the
refusals, which is what this stage is for. They say nothing about accuracy on
real footage — that measurement is the QUVA specificity run recorded in
`docs/BENCHMARKS.md`, and it only has negatives.
"""

from __future__ import annotations

import math

import pytest

from iacoach.classify import (
    UNCLASSIFIABLE,
    ExerciseClassifier,
    classify_window,
    frame_features,
    window_features,
)
from iacoach.contracts import Exercise
from iacoach.frame import Landmark

# The synthetic postures live in the fixture generator, which is their single
# source of truth: these unit tests exercise the rules, the conformance fixtures
# lock the numbers, and both must describe the same bodies.
from iacoach.scripts.make_classify_fixtures import (
    FOREARM,
    HIP_HALF,
    SHIN,
    SHOULDER_HALF,
    THIGH,
    TORSO,
    UPPER_ARM,
    _mirror,
    _skeleton,
    hanging_pose,
    l_sit_pose,
    push_up_pose,
    rowing_pose,
    squat_pose,
)


def cycle(pose, low: float, high: float, count: int = 60):
    """`count` frames sweeping a joint angle back and forth."""
    frames = []
    for i in range(count):
        phase = 2.0 * math.pi * i / 30.0
        angle = (low + high) / 2.0 + (high - low) / 2.0 * math.cos(phase)
        frames.append((pose(angle), i * 1000.0 / 30.0))
    return frames


def summarise(frames) -> object:
    features = [f for world, t in frames if (f := frame_features(world, world, t)) is not None]
    assert len(features) == len(frames), "aucune frame ne doit être rejetée ici"
    return window_features(features)


class TestPostureFeatures:
    def test_a_hang_puts_the_hands_well_above_the_shoulders(self) -> None:
        pose = hanging_pose(175.0, arms_up=True)
        f = frame_features(pose, pose, 0.0)
        assert f is not None
        assert f.wrist_above_shoulder > 0.9
        assert f.trunk_verticality == pytest.approx(1.0, abs=0.01)

    def test_hands_are_below_the_shoulders_on_bars(self) -> None:
        pose = hanging_pose(175.0, arms_up=False)
        f = frame_features(pose, pose, 0.0)
        assert f is not None
        assert f.wrist_above_shoulder < -0.5

    def test_a_push_up_reads_as_horizontal(self) -> None:
        f = frame_features(push_up_pose(170.0), push_up_pose(170.0), 0.0)
        assert f is not None
        assert f.trunk_verticality < 0.2

    def test_features_are_scale_free(self) -> None:
        # A taller athlete is the same geometry, so the same numbers. If any
        # threshold in this module were an absolute length, this would fail.
        small = hanging_pose(120.0, arms_up=True)
        big = [Landmark(p.x * 1.3, p.y * 1.3, p.z * 1.3, p.visibility) for p in small]
        fs, fb = frame_features(small, small, 0.0), frame_features(big, big, 0.0)
        assert fs is not None and fb is not None
        assert fb.wrist_above_shoulder == pytest.approx(fs.wrist_above_shoulder, abs=1e-9)
        assert fb.elbow_deg == pytest.approx(fs.elbow_deg, abs=1e-9)

    def test_a_missing_joint_yields_no_features(self) -> None:
        # Never a neutral substitute: a fabricated posture would be classified
        # as confidently as a real one.
        truncated = hanging_pose(170.0, arms_up=True)[:20]
        assert frame_features(truncated, truncated, 0.0) is None


class TestClassification:
    def test_pull_up(self) -> None:
        frames = cycle(lambda a: hanging_pose(a, arms_up=True), 55.0, 172.0)
        result = classify_window(summarise(frames))
        assert result.exercise is Exercise.PULL_UP

    def test_dip(self) -> None:
        frames = cycle(lambda a: hanging_pose(a, arms_up=False), 85.0, 172.0)
        result = classify_window(summarise(frames))
        assert result.exercise is Exercise.DIP

    def test_push_up(self) -> None:
        result = classify_window(summarise(cycle(push_up_pose, 80.0, 172.0)))
        assert result.exercise is Exercise.PUSH_UP

    def test_squat(self) -> None:
        # `squat_pose` takes a depth in [0, 0.75], not an angle.
        result = classify_window(summarise(cycle(squat_pose, 0.0, 0.75)))
        assert result.exercise is Exercise.SQUAT

    def test_l_sit(self) -> None:
        frames = [(l_sit_pose(0.0), i * 1000.0 / 30.0) for i in range(60)]
        assert classify_window(summarise(frames)).exercise is Exercise.L_SIT


class TestSquatNeedsTheHip:
    """A squat folds the hip. Without that term the rule read "standing, legs
    moving, arms still" — which also describes walking, cycling and skipping
    rope, and labelled 34 of 100 out-of-domain clips a squat.

    It went unnoticed because the synthetic squat used to hold its hip rigid,
    which no real squat does. The fixture was wrong before the rule was.
    """

    def test_a_real_squat_folds_the_hip(self) -> None:
        window = summarise(cycle(squat_pose, 0.0, 0.75))
        assert window.hip_rom_deg > 60.0
        assert window.knee_rom_deg > 60.0

    def test_moving_legs_without_folding_the_hip_is_not_a_squat(self) -> None:
        # Pedalling, walking, skipping: the knee cycles, the hip barely does.
        def rigid_hip(depth: float) -> list[Landmark]:
            points = {}
            points.update(_mirror("HIP", HIP_HALF, 0.0, 0.0))
            points.update(_mirror("SHOULDER", SHOULDER_HALF, -TORSO, 0.0))
            points.update(_mirror("ELBOW", SHOULDER_HALF, -TORSO + UPPER_ARM, 0.0))
            points.update(_mirror("WRIST", SHOULDER_HALF, -TORSO + UPPER_ARM + FOREARM, 0.0))
            points.update(_mirror("KNEE", HIP_HALF, THIGH, 0.0))
            # Only the ankle swings, so the knee angle cycles and the hip does not.
            angle = math.radians(60.0 + 110.0 * depth)
            points.update(
                _mirror("ANKLE", HIP_HALF, THIGH + SHIN * math.sin(angle), -SHIN * math.cos(angle))
            )
            return _skeleton(points)

        window = summarise(cycle(rigid_hip, 0.0, 1.0))
        assert window.knee_rom_deg > 60.0
        assert window.hip_rom_deg < 20.0
        assert classify_window(window).exercise is not Exercise.SQUAT


class TestRefusal:
    """The behaviour the whole stage exists for.

    31 of 100 out-of-domain clips produced invented reps because nothing ever
    asked what the movement was. Refusing has to be cheap and frequent.
    """

    def test_a_dead_hang_is_not_a_pull_up(self) -> None:
        # Hanging still is the pull-up posture with none of the work. Counting
        # it would attribute reps to an athlete resting between sets.
        frames = [(hanging_pose(172.0, arms_up=True), i * 1000.0 / 30.0) for i in range(60)]
        assert classify_window(summarise(frames)).exercise is Exercise.UNKNOWN

    def test_elbow_flexion_alone_is_not_an_exercise(self) -> None:
        # The rowing case: elbows through a full range, hands at chest height,
        # trunk pitched forward, legs deliberately still. Rejecting it *without*
        # the help of a knee range is the stronger guarantee — an arms-only
        # drill exists and would otherwise slip through.
        result = classify_window(summarise(cycle(rowing_pose, 60.0, 170.0)))
        assert result.exercise is Exercise.UNKNOWN

    def test_a_short_window_refuses(self) -> None:
        frames = [(hanging_pose(120.0, arms_up=True), i * 1000.0 / 30.0) for i in range(5)]
        assert classify_window(summarise(frames)).exercise is Exercise.UNKNOWN

    def test_poor_tracking_refuses(self) -> None:
        world = hanging_pose(120.0, arms_up=True)
        blind = [Landmark(p.x, p.y, p.z, 0.1) for p in world]
        features = [
            f
            for i in range(60)
            if (f := frame_features(world, blind, i * 1000.0 / 30.0)) is not None
        ]
        result = classify_window(window_features(features))
        assert result.exercise is Exercise.UNKNOWN
        assert result.reason == "suivi insuffisant"

    def test_the_unclassifiable_are_declared_not_forgotten(self) -> None:
        assert Exercise.CHIN_UP in UNCLASSIFIABLE
        assert Exercise.MUSCLE_UP in UNCLASSIFIABLE


class TestHysteresis:
    """A label routes the rule set, so flipping it changes the corrections."""

    def test_one_bad_window_does_not_rename_the_exercise(self) -> None:
        classifier = ExerciseClassifier()
        t = 0.0
        for _ in range(4):
            for world, _dt in cycle(lambda a: hanging_pose(a, arms_up=True), 55.0, 172.0, 30):
                classifier.push(world, world, t)
                t += 1000.0 / 30.0
        assert classifier.current is Exercise.PULL_UP

        # One window of something else must not take the label.
        for world, _dt in cycle(push_up_pose, 80.0, 172.0, 20):
            result = classifier.push(world, world, t)
            t += 1000.0 / 30.0
            assert result is None or result.exercise is Exercise.PULL_UP
        assert classifier.current is Exercise.PULL_UP

    def test_a_sustained_change_is_eventually_accepted(self) -> None:
        classifier = ExerciseClassifier()
        t = 0.0
        for _ in range(6):
            for world, _dt in cycle(push_up_pose, 80.0, 172.0, 30):
                classifier.push(world, world, t)
                t += 1000.0 / 30.0
        assert classifier.current is Exercise.PUSH_UP
