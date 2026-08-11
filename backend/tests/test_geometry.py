"""Geometry tests.

These same cases are mirrored in ``web/src/pose/angles.test.ts``; the two
implementations must agree. Divergence here is the failure mode the dual-runtime
design is built to catch.
"""

from __future__ import annotations

import math

import pytest

from iacoach.geometry import Point3, angle_deg, midpoint, norm, symmetry_score


class TestAngle:
    def test_right_angle(self) -> None:
        shoulder = Point3(0.0, 1.0, 0.0)
        elbow = Point3(0.0, 0.0, 0.0)
        wrist = Point3(1.0, 0.0, 0.0)
        assert angle_deg(shoulder, elbow, wrist) == pytest.approx(90.0)

    def test_straight_arm(self) -> None:
        shoulder = Point3(0.0, 1.0, 0.0)
        elbow = Point3(0.0, 0.0, 0.0)
        wrist = Point3(0.0, -1.0, 0.0)
        assert angle_deg(shoulder, elbow, wrist) == pytest.approx(180.0)

    def test_fully_folded(self) -> None:
        shoulder = Point3(0.0, 1.0, 0.0)
        elbow = Point3(0.0, 0.0, 0.0)
        wrist = Point3(0.0, 1.0, 0.0)
        assert angle_deg(shoulder, elbow, wrist) == pytest.approx(0.0)

    def test_uses_the_third_dimension(self) -> None:
        """A 2D projection would read this as 180 degrees. It is 90."""
        a = Point3(0.0, 1.0, 0.0)
        vertex = Point3(0.0, 0.0, 0.0)
        c = Point3(0.0, 0.0, 1.0)
        assert angle_deg(a, vertex, c) == pytest.approx(90.0)

    def test_degenerate_segment_reads_as_extended(self) -> None:
        """Collapsed landmarks must never fabricate a flexed joint, which the FSM
        would read as a completed rep."""
        vertex = Point3(0.0, 0.0, 0.0)
        assert angle_deg(vertex, vertex, Point3(1.0, 0.0, 0.0)) == 180.0

    def test_no_domain_error_on_collinear_float_drift(self) -> None:
        """acos(1.0000000002) would raise; the clamp must absorb it."""
        a = Point3(1e-8, 0.0, 0.0)
        vertex = Point3(0.0, 0.0, 0.0)
        c = Point3(3e-8, 0.0, 0.0)
        assert not math.isnan(angle_deg(a, vertex, c))


class TestHelpers:
    def test_norm(self) -> None:
        assert norm(Point3(3.0, 4.0, 0.0)) == pytest.approx(5.0)

    def test_midpoint(self) -> None:
        assert midpoint(Point3(0.0, 0.0, 0.0), Point3(2.0, 4.0, 6.0)) == Point3(1.0, 2.0, 3.0)


class TestSymmetry:
    def test_identical_sides_score_one(self) -> None:
        assert symmetry_score(120.0, 120.0) == pytest.approx(1.0)

    def test_score_degrades_continuously(self) -> None:
        """Not a threshold: a 5-degree gap and a 15-degree gap must differ."""
        small = symmetry_score(120.0, 125.0)
        large = symmetry_score(120.0, 135.0)
        assert 1.0 > small > large > 0.0

    def test_beyond_tolerance_floors_at_zero(self) -> None:
        assert symmetry_score(90.0, 180.0) == 0.0

    def test_is_symmetric_in_its_arguments(self) -> None:
        assert symmetry_score(100.0, 115.0) == pytest.approx(symmetry_score(115.0, 100.0))

    def test_rejects_nonpositive_tolerance(self) -> None:
        with pytest.raises(ValueError):
            symmetry_score(100.0, 100.0, tolerance_deg=0.0)
