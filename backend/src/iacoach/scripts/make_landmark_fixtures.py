"""Generates the landmark-level conformance fixtures.

``fixtures/sequences/`` starts from ``FrameSample`` and locks the counter.
These start one stage earlier — from raw landmarks — and lock the *sampler*:
the elbow angles, the trunk lean and the hip speed that everything downstream
is computed from.

That stage exists twice, in ``web/src/analysis/frame.ts`` and in
``iacoach.frame``, because the phone runs it live and the offline evaluation
runs it over recorded video. Two implementations of the same geometry is
exactly the shape of bug that stays invisible until the numbers from a dataset
and the numbers from a session quietly stop meaning the same thing.

Usage:  python -m iacoach.scripts.make_landmark_fixtures [--check]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from typing import Any

from iacoach.config import REPO_ROOT
from iacoach.frame import LANDMARK, FrameSampler, Landmark

LANDMARK_DIR = REPO_ROOT / "fixtures" / "landmarks"

FPS = 30.0
UPPER_ARM_M = 0.30
FOREARM_M = 0.28
SHOULDER_HALF_WIDTH_M = 0.20
HIP_HALF_WIDTH_M = 0.15
TORSO_M = 0.50


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    seconds: float
    reps: float
    trunk_amplitude_deg: float
    hip_drift_m: float
    occluded_window_s: tuple[float, float] | None


def _scenarios() -> list[Scenario]:
    return [
        Scenario(
            name="pullup_clean",
            description=(
                "Trois tractions régulières, buste stable, aucun déplacement parasite du bassin."
            ),
            seconds=6.0,
            reps=3.0,
            trunk_amplitude_deg=0.0,
            hip_drift_m=0.0,
            occluded_window_s=None,
        ),
        Scenario(
            name="pullup_swing_occlusion",
            description=(
                "Deux tractions avec balancement du buste et dérive latérale du "
                "bassin, plus une fenêtre où les poignets passent sous le seuil "
                "de visibilité."
            ),
            seconds=4.0,
            reps=2.0,
            trunk_amplitude_deg=12.0,
            hip_drift_m=0.06,
            occluded_window_s=(1.5, 2.2),
        ),
    ]


def _rotate_xy(x: float, y: float, radians: float) -> tuple[float, float]:
    cos, sin = math.cos(radians), math.sin(radians)
    return x * cos - y * sin, x * sin + y * cos


def _frame(scenario: Scenario, t_s: float) -> tuple[list[Landmark], list[Landmark]]:
    """One frame of a synthetic pull-up, in metric world coordinates.

    The y axis points down, as MediaPipe's world landmarks do, and the origin
    sits at the hip midpoint.
    """
    phase = 2.0 * math.pi * scenario.reps * t_s / scenario.seconds
    # 175 deg hanging, 45 deg at the top of the pull.
    elbow_deg = 110.0 + 65.0 * math.cos(phase)
    trunk_rad = math.radians(scenario.trunk_amplitude_deg * math.sin(phase))
    # Lateral hip travel: the parasitic momentum the kipping score looks for.
    hip_x = scenario.hip_drift_m * math.sin(2.0 * phase)

    hip_left = (hip_x - HIP_HALF_WIDTH_M, 0.0, 0.0)
    hip_right = (hip_x + HIP_HALF_WIDTH_M, 0.0, 0.0)

    # Shoulders sit a torso above the hips, tilted by the trunk lean.
    lean_x, lean_y = _rotate_xy(0.0, -TORSO_M, trunk_rad)
    shoulder_cx, shoulder_cy = hip_x + lean_x, lean_y

    world: list[Landmark] = [Landmark(0.0, 0.0, 0.0, 0.9) for _ in range(33)]

    def place(index: int, x: float, y: float, z: float, visibility: float = 0.9) -> None:
        world[index] = Landmark(x, y, z, visibility)

    for side, sign in (("LEFT", -1.0), ("RIGHT", 1.0)):
        shoulder_x = shoulder_cx + sign * SHOULDER_HALF_WIDTH_M
        shoulder_y = shoulder_cy
        # Upper arm points up towards the bar; elbow is below the shoulder.
        elbow_x, elbow_y = shoulder_x, shoulder_y + UPPER_ARM_M
        # Forearm makes `elbow_deg` with the elbow->shoulder direction, opening
        # outwards, so 180 deg puts the wrist straight below the elbow.
        # With the elbow->shoulder direction being (0, -1) in this y-down frame,
        # the wrist sits at (sin θ, -cos θ): θ = 180 deg puts it straight below
        # the elbow (arm extended), θ = 45 deg pulls it up towards the bar.
        rad = math.radians(elbow_deg)
        wrist_x = elbow_x + sign * FOREARM_M * math.sin(rad)
        wrist_y = elbow_y - FOREARM_M * math.cos(rad)
        place(LANDMARK[f"{side}_SHOULDER"], shoulder_x, shoulder_y, 0.0)
        place(LANDMARK[f"{side}_ELBOW"], elbow_x, elbow_y, 0.0)
        place(LANDMARK[f"{side}_WRIST"], wrist_x, wrist_y, 0.0)

    place(LANDMARK["LEFT_HIP"], *hip_left)
    place(LANDMARK["RIGHT_HIP"], *hip_right)

    # The normalised set only feeds the confidence figure here, so its geometry
    # is irrelevant — its visibilities are not.
    occluded = (
        scenario.occluded_window_s is not None
        and scenario.occluded_window_s[0] <= t_s <= scenario.occluded_window_s[1]
    )
    normalized = [Landmark(0.5, 0.5, 0.0, 0.9) for _ in range(33)]
    if occluded:
        for index in (LANDMARK["LEFT_WRIST"], LANDMARK["RIGHT_WRIST"]):
            normalized[index] = Landmark(0.5, 0.5, 0.0, 0.3)

    return world, normalized


def _rounded(lm: Landmark) -> Landmark:
    """Rounds a landmark to what the file will actually hold.

    Load-bearing: the expected samples are computed from *these* values, not
    from the full-precision ones. Otherwise the fixture would not be
    reproducible from its own contents, and the replay would fail by a hair.
    Near a straight arm the failure is not even that small — `angle_deg` goes
    through `acos`, which is ill-conditioned at ±1, so a 1e-9 wobble on a
    coordinate came out as 1.5e-8 on the angle.
    """
    return Landmark(round(lm.x, 9), round(lm.y, 9), round(lm.z, 9), lm.visibility)


def _landmark_json(lm: Landmark) -> dict[str, Any]:
    return {"x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility}


def _payload(scenario: Scenario) -> dict[str, Any]:
    sampler = FrameSampler()
    frames: list[dict[str, Any]] = []
    expected: list[dict[str, Any]] = []

    total = int(scenario.seconds * FPS)
    for i in range(total):
        t_ms = round(i * 1000.0 / FPS, 6)
        raw_world, raw_normalized = _frame(scenario, t_ms / 1000.0)
        world = [_rounded(lm) for lm in raw_world]
        normalized = [_rounded(lm) for lm in raw_normalized]
        frames.append(
            {
                "t_ms": t_ms,
                "world": [_landmark_json(lm) for lm in world],
                "normalized": [_landmark_json(lm) for lm in normalized],
            }
        )
        sample = sampler.sample(world, normalized, t_ms)
        assert sample is not None, "the synthetic frames always carry every landmark"
        expected.append(json.loads(sample.model_dump_json()))

    return {
        "name": scenario.name,
        "description": scenario.description,
        "fps": FPS,
        "frames": frames,
        "expected": expected,
    }


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed fixtures are stale. Used in CI.",
    )
    args = parser.parse_args(argv)

    LANDMARK_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []

    for scenario in _scenarios():
        path = LANDMARK_DIR / f"{scenario.name}.json"
        rendered = _dump(_payload(scenario))
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(path.name)
        else:
            path.write_text(rendered, encoding="utf-8")

    if args.check and stale:
        print(
            "Stale landmark fixtures: "
            + ", ".join(sorted(stale))
            + "\nRun: python -m iacoach.scripts.make_landmark_fixtures",
            file=sys.stderr,
        )
        return 1

    if not args.check:
        print(f"Wrote {len(_scenarios())} landmark fixtures to {LANDMARK_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
