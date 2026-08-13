"""Generates the exercise-classification conformance fixtures.

The classifier exists twice — ``iacoach.classify`` and
``web/src/analysis/classify.ts`` — because the phone routes the rule set live
while the offline evaluation classifies recorded video. The two must not drift:
a label decides which corrections an athlete is given, so a divergence would
show up as different coaching from the same movement, with nothing to say why.

Each fixture carries the landmark frames, the per-frame features, the window
features and the final classification. Both languages replay it and must match.

The postures are **synthetic** — limb lengths and joint angles assembled by
hand. They lock the geometry the rules read and, above all, they lock the
*refusals*: `rowing_not_an_exercise` is the shape that produced most of the
invented reps in the specificity run, and it must stay `unknown` in both
implementations.

Usage:  python -m iacoach.scripts.make_classify_fixtures [--check]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from iacoach.classify import Landmark, classify_window, frame_features, window_features
from iacoach.config import REPO_ROOT
from iacoach.frame import LANDMARK

CLASSIFY_DIR = REPO_ROOT / "fixtures" / "classify"

FPS = 30.0
UPPER_ARM, FOREARM = 0.30, 0.25
TORSO, THIGH, SHIN = 0.50, 0.45, 0.42
SHOULDER_HALF, HIP_HALF = 0.18, 0.12

Points = dict[str, tuple[float, float, float]]


def _skeleton(points: Points, visibility: float = 1.0) -> list[Landmark]:
    """33 landmarks; only the ones the classifier reads carry a position."""
    out = [Landmark(0.0, 0.0, 0.0, visibility) for _ in range(33)]
    for name, (x, y, z) in points.items():
        out[LANDMARK[name]] = Landmark(x, y, z, visibility)
    return out


def _mirror(name: str, x: float, y: float, z: float) -> Points:
    return {f"LEFT_{name}": (-x, y, z), f"RIGHT_{name}": (x, y, z)}


def hanging_pose(elbow_deg: float, *, arms_up: bool) -> list[Landmark]:
    """Vertical trunk, straight legs, arms overhead (bar) or down (bars).

    y points down, matching MediaPipe world landmarks.
    """
    sign = -1.0 if arms_up else 1.0
    rad = math.radians(elbow_deg)
    elbow_y = -TORSO + sign * UPPER_ARM
    # The forearm swings in the y-z plane so the two sides stay symmetric.
    points: Points = {}
    points.update(_mirror("HIP", HIP_HALF, 0.0, 0.0))
    points.update(_mirror("SHOULDER", SHOULDER_HALF, -TORSO, 0.0))
    points.update(_mirror("ELBOW", SHOULDER_HALF, elbow_y, 0.0))
    points.update(
        _mirror(
            "WRIST",
            SHOULDER_HALF,
            elbow_y - sign * FOREARM * math.cos(rad),
            FOREARM * math.sin(rad),
        )
    )
    points.update(_mirror("KNEE", HIP_HALF, THIGH, 0.0))
    points.update(_mirror("ANKLE", HIP_HALF, THIGH + SHIN, 0.0))
    return _skeleton(points)


def push_up_pose(elbow_deg: float) -> list[Landmark]:
    """Trunk horizontal along z, hands under the shoulders."""
    rad = math.radians(elbow_deg)
    points: Points = {}
    points.update(_mirror("HIP", HIP_HALF, 0.0, 0.0))
    points.update(_mirror("SHOULDER", SHOULDER_HALF, -0.02, -TORSO))
    points.update(_mirror("ELBOW", SHOULDER_HALF, UPPER_ARM, -TORSO))
    points.update(
        _mirror(
            "WRIST",
            SHOULDER_HALF,
            UPPER_ARM + FOREARM * math.cos(rad),
            -TORSO - FOREARM * math.sin(rad),
        )
    )
    points.update(_mirror("KNEE", HIP_HALF, 0.0, THIGH))
    points.update(_mirror("ANKLE", HIP_HALF, 0.0, THIGH + SHIN))
    return _skeleton(points)


def squat_pose(knee_deg: float) -> list[Landmark]:
    """Near-upright trunk, arms hanging still, knee angle driven exactly.

    The ankle is placed by rotating the knee->hip direction by the wanted angle
    in the y-z plane, so `knee_deg` is the angle by construction rather than an
    approximation that would drift with the limb lengths.
    """
    knee_y, knee_z = THIGH * 0.9, -0.10
    length = math.hypot(knee_y, knee_z)
    ux, uy = -knee_y / length, -knee_z / length
    rad = math.radians(knee_deg)

    points: Points = {}
    points.update(_mirror("HIP", HIP_HALF, 0.0, 0.0))
    points.update(_mirror("SHOULDER", SHOULDER_HALF, -TORSO + 0.01, -0.08))
    points.update(_mirror("ELBOW", SHOULDER_HALF, -TORSO + UPPER_ARM, 0.02))
    points.update(_mirror("WRIST", SHOULDER_HALF, -TORSO + UPPER_ARM + FOREARM, 0.04))
    points.update(_mirror("KNEE", HIP_HALF, knee_y, knee_z))
    points.update(
        _mirror(
            "ANKLE",
            HIP_HALF,
            knee_y + SHIN * (ux * math.cos(rad) - uy * math.sin(rad)),
            knee_z + SHIN * (ux * math.sin(rad) + uy * math.cos(rad)),
        )
    )
    return _skeleton(points)


def l_sit_pose(_: float) -> list[Landmark]:
    """Trunk upright, hips folded to 90 deg, knees locked, arms static."""
    points: Points = {}
    points.update(_mirror("HIP", HIP_HALF, 0.0, 0.0))
    points.update(_mirror("SHOULDER", SHOULDER_HALF, -TORSO, 0.0))
    points.update(_mirror("ELBOW", SHOULDER_HALF, -TORSO + UPPER_ARM, 0.0))
    points.update(_mirror("WRIST", SHOULDER_HALF, -TORSO + UPPER_ARM + FOREARM, 0.0))
    points.update(_mirror("KNEE", HIP_HALF, 0.0, -THIGH))
    points.update(_mirror("ANKLE", HIP_HALF, 0.0, -THIGH - SHIN))
    return _skeleton(points)


def rowing_pose(elbow_deg: float) -> list[Landmark]:
    """Not an exercise this app counts, and the reason this fixture exists.

    Elbows cycling through a full range, hands at chest height, trunk pitched
    forward, legs deliberately still — a rowing stroke, or a bent-over row, or
    someone hauling on a rope. `034_rowing_machine` alone produced 10 invented
    reps. The legs are held still on purpose: rejecting this *without* the help
    of a knee range is the stronger guarantee, because an arms-only drill
    exists and would otherwise slip through.
    """
    rad = math.radians(elbow_deg)
    shoulder_y, shoulder_z = -TORSO * 0.75, -TORSO * 0.6
    points: Points = {}
    points.update(_mirror("HIP", HIP_HALF, 0.0, 0.0))
    points.update(_mirror("SHOULDER", SHOULDER_HALF, shoulder_y, shoulder_z))
    points.update(_mirror("ELBOW", SHOULDER_HALF, shoulder_y, shoulder_z - UPPER_ARM))
    points.update(
        _mirror(
            "WRIST",
            SHOULDER_HALF,
            shoulder_y + FOREARM * math.sin(rad) * 0.3,
            shoulder_z - UPPER_ARM - FOREARM * math.cos(math.pi - rad),
        )
    )
    points.update(_mirror("KNEE", HIP_HALF, THIGH * 0.7, -THIGH * 0.6))
    points.update(_mirror("ANKLE", HIP_HALF, THIGH * 0.7, -THIGH * 0.6 - SHIN))
    return _skeleton(points)


def dead_hang_pose(_: float) -> list[Landmark]:
    """The pull-up posture with none of the work.

    Counting this would credit reps to an athlete resting between sets.
    """
    return hanging_pose(172.0, arms_up=True)


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    pose: Callable[[float], list[Landmark]]
    low_deg: float
    high_deg: float
    seconds: float = 2.0


def _scenarios() -> list[Scenario]:
    return [
        Scenario(
            "pullup",
            "Tractions à la barre : mains au-dessus des épaules, buste vertical.",
            lambda a: hanging_pose(a, arms_up=True),
            55.0,
            172.0,
        ),
        Scenario(
            "dip",
            "Dips aux barres parallèles : mains au niveau des hanches, buste vertical.",
            lambda a: hanging_pose(a, arms_up=False),
            85.0,
            172.0,
        ),
        Scenario("pushup", "Pompes : buste horizontal.", push_up_pose, 80.0, 172.0),
        Scenario("squat", "Squats : le genou travaille, le coude non.", squat_pose, 70.0, 172.0),
        Scenario(
            "l_sit",
            "L-sit : hanches à 90°, genoux verrouillés, rien ne bouge.",
            l_sit_pose,
            0.0,
            0.0,
        ),
        Scenario(
            "rowing_not_an_exercise",
            "Rameur : coudes en pleine amplitude, mais ce n'est aucun exercice suivi.",
            rowing_pose,
            60.0,
            170.0,
        ),
        Scenario(
            "dead_hang_not_a_rep",
            "Suspension immobile : la posture de la traction sans le travail.",
            dead_hang_pose,
            0.0,
            0.0,
        ),
    ]


def _rounded(lm: Landmark) -> Landmark:
    """Round before computing anything from it.

    The expected values are computed from *these* coordinates, not from the
    unrounded ones, so the fixture is reproducible from its own contents. The
    counter's fixtures learned this the hard way: `angle_deg` goes through
    `acos`, ill-conditioned at ±1, and a 1e-9 wobble on a coordinate came out as
    1.5e-8 on the angle.
    """
    return Landmark(round(lm.x, 9), round(lm.y, 9), round(lm.z, 9), lm.visibility)


STORED = (
    "LEFT_SHOULDER",
    "RIGHT_SHOULDER",
    "LEFT_ELBOW",
    "RIGHT_ELBOW",
    "LEFT_WRIST",
    "RIGHT_WRIST",
    "LEFT_HIP",
    "RIGHT_HIP",
    "LEFT_KNEE",
    "RIGHT_KNEE",
    "LEFT_ANKLE",
    "RIGHT_ANKLE",
)
"""The landmarks the classifier actually reads.

The first version of these fixtures stored all 33, of which 21 were zero
padding — 1.7 MB and 91 000 lines of JSON for seven synthetic scenarios, which
buries every future diff. Only the read landmarks are stored; the readers
rebuild the padding, which is inert by construction since nothing indexes it."""

PAD = {"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 1.0}
"""What the omitted landmarks were. Written down so both readers rebuild the
same frame, and so the values stay reproducible rather than conventional."""


def _sparse(landmarks: list[Landmark]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in STORED:
        lm = landmarks[LANDMARK[name]]
        out[str(LANDMARK[name])] = {
            "x": lm.x,
            "y": lm.y,
            "z": lm.z,
            "visibility": lm.visibility,
        }
    return out


def _payload(scenario: Scenario) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    features = []

    for i in range(int(scenario.seconds * FPS)):
        t_ms = round(i * 1000.0 / FPS, 6)
        phase = 2.0 * math.pi * i / FPS
        mid = (scenario.low_deg + scenario.high_deg) / 2.0
        angle = mid + (scenario.high_deg - scenario.low_deg) / 2.0 * math.cos(phase)
        landmarks = [_rounded(lm) for lm in scenario.pose(angle)]
        frames.append({"t_ms": t_ms, "landmarks": _sparse(landmarks)})
        found = frame_features(landmarks, landmarks, t_ms)
        assert found is not None, "the synthetic frames always carry every landmark"
        features.append(found)

    window = window_features(features)
    verdict = classify_window(window)
    return {
        "name": scenario.name,
        "description": scenario.description,
        "fps": FPS,
        "landmark_count": 33,
        "pad": PAD,
        "frames": frames,
        "expected_frames": [asdict(f) for f in features],
        "expected_window": asdict(window),
        "expected": {
            "exercise": verdict.exercise.value,
            "confidence": verdict.confidence,
            "reason": verdict.reason,
            "scores": {e.value: s for e, s in verdict.scores.items()},
        },
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

    CLASSIFY_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []

    for scenario in _scenarios():
        path = CLASSIFY_DIR / f"{scenario.name}.json"
        rendered = _dump(_payload(scenario))
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != rendered:
                stale.append(path.name)
        else:
            path.write_text(rendered, encoding="utf-8")

    if args.check and stale:
        print(
            "Fixtures de classification périmées : "
            + ", ".join(stale)
            + "\nRelancer : python -m iacoach.scripts.make_classify_fixtures",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
