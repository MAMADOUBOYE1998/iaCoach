"""Generate the shared conformance fixtures.

Two artefacts per scenario:

- ``fixtures/sequences/<name>.json`` — the input: a synthetic frame sequence plus
  the outcome I asserted *by construction* when writing it (how many reps, how
  many should count, which flags). That expectation is the semantic check, and it
  is hand-authored, not derived from the implementation.
- ``fixtures/golden/<name>.json`` — the output: the full ``RepEvent`` stream the
  Python implementation produces. This is a golden file; its job is to catch
  drift, both across releases and between the Python and TypeScript
  implementations.

Both test suites read both files. Python passing its own golden file proves
nothing on its own — the value is that TypeScript must reproduce it exactly, and
that a behaviour change shows up as a reviewable diff.

Usage:  python -m iacoach.scripts.make_fixtures [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from iacoach.config import REPO_ROOT
from iacoach.contracts import Exercise, ExerciseCalibration, FrameSample
from iacoach.counting import analyse_sequence

SEQUENCES_DIR = REPO_ROOT / "fixtures" / "sequences"
GOLDEN_DIR = REPO_ROOT / "fixtures" / "golden"

FPS = 30.0
ROM_MIN_DEG = 40.0  # calibrated maximum flexion (chin over bar)
ROM_MAX_DEG = 172.0  # calibrated full extension (dead hang)


def _calibration() -> ExerciseCalibration:
    return ExerciseCalibration(
        exercise=Exercise.PULL_UP,
        joint="elbow",
        rom_min_deg=ROM_MIN_DEG,
        rom_max_deg=ROM_MAX_DEG,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        confidence=1.0,
    )


class _Noise:
    """Tiny LCG. Deterministic across languages and Python versions, which
    ``random`` is not guaranteed to be."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0xFFFFFFFF

    def next(self) -> float:
        """Uniform in [-1, 1)."""
        self._state = (1664525 * self._state + 1013904223) & 0xFFFFFFFF
        return (self._state / 0x80000000) - 1.0


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass
class RepShape:
    """One synthetic repetition."""

    peak_flexion: float
    concentric_s: float = 1.0
    top_pause_s: float = 0.3
    eccentric_s: float = 1.4
    bottom_pause_s: float = 0.6
    hip_speed: float = 0.05
    asymmetry_deg: float = 0.0
    trunk_deg: float = 2.0
    confidence: float = 1.0


def _flexion_to_angle(flexion: float) -> float:
    return ROM_MAX_DEG - flexion * (ROM_MAX_DEG - ROM_MIN_DEG)


def _build_frames(reps: list[RepShape], *, seed: int, lead_in_s: float = 1.0) -> list[FrameSample]:
    """Render a list of rep shapes into a frame sequence at FPS."""
    noise = _Noise(seed)
    frames: list[FrameSample] = []
    t_ms = 0.0
    step_ms = 1000.0 / FPS

    def emit(flexion: float, shape: RepShape) -> None:
        nonlocal t_ms
        jitter = noise.next() * 0.3  # sub-degree sensor jitter
        angle = _flexion_to_angle(flexion) + jitter
        frames.append(
            FrameSample(
                t_ms=round(t_ms, 4),
                elbow_left_deg=angle + shape.asymmetry_deg,
                elbow_right_deg=angle - shape.asymmetry_deg,
                trunk_deg=shape.trunk_deg,
                # Hips only move during the pull; a dead hang is still.
                hip_speed=shape.hip_speed if flexion > 0.2 else 0.02,
                confidence=shape.confidence,
            )
        )
        t_ms += step_ms

    # Settle at full extension so the counter can confirm a dead hang before
    # anything is counted. Starting mid-movement would fabricate a partial rep.
    lead = RepShape(peak_flexion=0.0)
    for _ in range(int(lead_in_s * FPS)):
        emit(0.0, lead)

    for shape in reps:
        for i in range(int(shape.concentric_s * FPS)):
            emit(shape.peak_flexion * _smoothstep(i / (shape.concentric_s * FPS)), shape)
        for _ in range(int(shape.top_pause_s * FPS)):
            emit(shape.peak_flexion, shape)
        for i in range(int(shape.eccentric_s * FPS)):
            emit(shape.peak_flexion * (1.0 - _smoothstep(i / (shape.eccentric_s * FPS))), shape)
        for _ in range(int(shape.bottom_pause_s * FPS)):
            emit(0.0, shape)

    return frames


@dataclass
class Scenario:
    name: str
    description: str
    reps: list[RepShape]
    seed: int
    expected_events: int
    expected_counted: int
    expected_flags: list[list[str]]
    """Flags per emitted event, in order. Hand-authored from the scenario's
    intent — this is the assertion the golden file cannot make for itself."""


def _scenarios() -> list[Scenario]:
    strict = dict(hip_speed=0.05, trunk_deg=2.0)

    return [
        Scenario(
            name="clean_5_reps",
            description="Five strict pull-ups, full range, no swing. The baseline.",
            reps=[RepShape(peak_flexion=0.95, **strict) for _ in range(5)],
            seed=1,
            expected_events=5,
            expected_counted=5,
            expected_flags=[[]] * 5,
        ),
        Scenario(
            name="short_rom_3_reps",
            description=(
                "Three attempts stopping around 62% of range. Real attempts, so "
                "they are recorded with their scores, but none counts."
            ),
            reps=[RepShape(peak_flexion=0.62, **strict) for _ in range(3)],
            seed=2,
            expected_events=3,
            expected_counted=0,
            expected_flags=[["rom_short"]] * 3,
        ),
        Scenario(
            name="kipping_last_2_of_4",
            description=(
                "Four full-range reps; the last two are driven by hip momentum. "
                "Range is fine, so a threshold counter sees four clean reps."
            ),
            reps=[
                RepShape(peak_flexion=0.93, **strict),
                RepShape(peak_flexion=0.93, **strict),
                RepShape(peak_flexion=0.93, hip_speed=1.30, trunk_deg=4.0, concentric_s=0.6),
                RepShape(peak_flexion=0.93, hip_speed=1.45, trunk_deg=4.0, concentric_s=0.6),
            ],
            seed=3,
            expected_events=4,
            expected_counted=4,
            expected_flags=[[], [], ["kipping"], ["kipping"]],
        ),
        Scenario(
            name="asymmetry_3_reps",
            description="Three reps with the left arm trailing the right by ~12 degrees.",
            reps=[RepShape(peak_flexion=0.90, asymmetry_deg=6.0, **strict) for _ in range(3)],
            seed=4,
            expected_events=3,
            expected_counted=3,
            expected_flags=[["asymmetry"]] * 3,
        ),
        Scenario(
            name="trunk_swing_3_reps",
            description="Three reps with a pronounced trunk lean throughout.",
            reps=[RepShape(peak_flexion=0.90, hip_speed=0.05, trunk_deg=26.0) for _ in range(3)],
            seed=5,
            expected_events=3,
            expected_counted=3,
            expected_flags=[["trunk_swing"]] * 3,
        ),
        Scenario(
            name="occlusion_middle_rep",
            description=(
                "Three reps; tracking degrades badly on the second. Its form "
                "scores are unreliable, so only low_confidence is reported — no "
                "correction is invented from bad data."
            ),
            reps=[
                RepShape(peak_flexion=0.92, **strict),
                RepShape(peak_flexion=0.92, hip_speed=0.05, trunk_deg=2.0, confidence=0.35),
                RepShape(peak_flexion=0.92, **strict),
            ],
            seed=6,
            expected_events=3,
            expected_counted=3,
            expected_flags=[[], ["low_confidence"], []],
        ),
        Scenario(
            name="noise_no_reps",
            description=(
                "Repositioning and shrugging on the bar, peaking around 30% of "
                "range. Nothing here is a repetition."
            ),
            reps=[RepShape(peak_flexion=0.30, **strict) for _ in range(4)],
            seed=7,
            expected_events=0,
            expected_counted=0,
            expected_flags=[],
        ),
        Scenario(
            name="mixed_full_then_short",
            description=(
                "A set going to failure: two clean reps, then two that fall "
                "short as fatigue sets in. The pattern the coach has to see."
            ),
            reps=[
                RepShape(peak_flexion=0.94, **strict),
                RepShape(peak_flexion=0.92, **strict),
                RepShape(peak_flexion=0.68, hip_speed=0.05, trunk_deg=2.0, concentric_s=1.4),
                RepShape(peak_flexion=0.55, hip_speed=0.05, trunk_deg=2.0, concentric_s=1.6),
            ],
            seed=8,
            expected_events=4,
            expected_counted=2,
            expected_flags=[[], [], ["rom_short"], ["rom_short"]],
        ),
    ]


def _sequence_payload(scenario: Scenario) -> dict[str, object]:
    frames = _build_frames(scenario.reps, seed=scenario.seed)
    return {
        "name": scenario.name,
        "description": scenario.description,
        "exercise": Exercise.PULL_UP.value,
        "fps": FPS,
        "calibration": _calibration().model_dump(mode="json"),
        "expected": {
            "events": scenario.expected_events,
            "counted": scenario.expected_counted,
            "flags": scenario.expected_flags,
        },
        "frames": [f.model_dump(mode="json") for f in frames],
    }


def _golden_payload(scenario: Scenario, sequence: dict[str, object]) -> list[dict[str, object]]:
    frames = [FrameSample.model_validate(f) for f in sequence["frames"]]  # type: ignore[arg-type]
    events = analyse_sequence(Exercise.PULL_UP, _calibration(), frames)
    return [e.model_dump(mode="json") for e in events]


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the committed fixtures are stale. Used in CI.",
    )
    args = parser.parse_args(argv)

    SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    stale: list[str] = []
    mismatched: list[str] = []

    for scenario in _scenarios():
        sequence = _sequence_payload(scenario)
        golden = _golden_payload(scenario, sequence)

        # The generator refuses to emit a fixture whose golden output contradicts
        # the hand-authored expectation: a fixture that disagrees with its own
        # premise would silently become a test of whatever the code happens to do.
        counted = sum(1 for e in golden if e["counted"])
        flags = [e["flags"] for e in golden]
        if (
            len(golden) != scenario.expected_events
            or counted != scenario.expected_counted
            or flags != scenario.expected_flags
        ):
            mismatched.append(
                f"{scenario.name}: expected {scenario.expected_events} events / "
                f"{scenario.expected_counted} counted / {scenario.expected_flags}, "
                f"got {len(golden)} / {counted} / {flags}"
            )
            continue

        for path, payload in (
            (SEQUENCES_DIR / f"{scenario.name}.json", sequence),
            (GOLDEN_DIR / f"{scenario.name}.json", golden),
        ):
            rendered = _dump(payload)
            if args.check:
                current = path.read_text(encoding="utf-8") if path.exists() else ""
                if current != rendered:
                    stale.append(path.name)
            else:
                path.write_text(rendered, encoding="utf-8")

    if mismatched:
        print("Fixture expectations do not match the analyser:", file=sys.stderr)
        for line in mismatched:
            print(f"  - {line}", file=sys.stderr)
        return 2

    if args.check and stale:
        print(
            "Stale fixtures: "
            + ", ".join(sorted(set(stale)))
            + "\nRun: python -m iacoach.scripts.make_fixtures",
            file=sys.stderr,
        )
        return 1

    if not args.check:
        print(f"Wrote {len(_scenarios())} fixtures to {SEQUENCES_DIR} and {GOLDEN_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
