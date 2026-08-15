"""The file name is the ground truth, so parsing it wrong fabricates a benchmark."""

from __future__ import annotations

import json
from pathlib import Path

from vision.eval.import_session import build, main, parse_name


def touch(root: Path, name: str) -> Path:
    path = root / name
    path.write_bytes(b"")
    return path


class TestTheNameCarriesTheTruth:
    def test_a_well_formed_name_yields_every_field(self) -> None:
        found = parse_name(Path("03_pullup_strict_face_05.mp4"))

        assert found == {
            "order": 3,
            "exercise": "pullup",
            "variant": "strict",
            "view": "face",
            "reps": 5,
        }

    def test_an_unreadable_name_is_refused_rather_than_guessed(self) -> None:
        """Defaulting to zero would put a fabricated count into a benchmark.

        A clip whose name does not parse is a clip whose repetition count is
        unknown. Every plausible default — zero, the previous clip's count — is
        a number the athlete never announced, and it would be graded as if they
        had.
        """
        for name in (
            "IMG_4821.mp4",  # the phone's own name
            "03_pullup_strict_face.mp4",  # count forgotten
            "pullup_strict_face_05.mp4",  # order forgotten
            "03_deadlift_strict_face_05.mp4",  # not an exercise the app knows
            "03_pullup_strict_face_cinq.mp4",  # count not a number
        ):
            assert parse_name(Path(name)) is None, name

    def test_the_variant_survives_into_the_manifest(self, tmp_path: Path) -> None:
        """Without it the run is unreadable exactly where it matters.

        `kip_tolerance_ms` cannot be recalibrated from strict repetitions alone —
        nothing in such a set sits on the other side of the threshold. The label
        has to be decided before the set and travel with it.
        """
        touch(tmp_path, "03_pullup_strict_face_05.mp4")
        touch(tmp_path, "07_pullup_kip_face_05.mp4")

        sets, _, _ = build(tmp_path)

        assert [e["variant"] for e in sets] == ["strict", "kip"]
        assert all(e["exercise"] == "pull_up" for e in sets)
        assert all(e["in_domain"] for e in sets)


class TestPerformedAndRestingAreGradedApart:
    def test_rest_clips_go_to_their_own_manifest(self, tmp_path: Path) -> None:
        """They answer opposite questions and the harness grades them in opposite modes.

        A set is scored against its announced count (sensitivity). A rest clip is
        scored on whether anything was counted at all (specificity). Feeding a
        dead hang into the sensitivity manifest would let "predicted 1, truth 0"
        pass as off-by-one accuracy.
        """
        touch(tmp_path, "03_pullup_strict_face_05.mp4")
        touch(tmp_path, "12_rest_deadhang_face_00.mp4")
        touch(tmp_path, "01_idle_tpose_face_00.mp4")

        sets, rest, rejected = build(tmp_path)

        assert [Path(e["path"]).name for e in sets] == ["03_pullup_strict_face_05.mp4"]
        assert len(rest) == 2
        assert all(e["reps"] == 0 for e in rest)
        assert not any("in_domain" in e for e in rest)
        assert rejected == []

    def test_a_directory_of_unreadable_names_exits_non_zero(self, tmp_path: Path) -> None:
        """Two empty manifests would read as a session that produced nothing.

        The distinction that matters at the end of a shoot: "the evening yielded
        nothing" and "nobody followed the naming convention" need different
        answers, and only one of them means the footage is lost.
        """
        touch(tmp_path, "IMG_4821.mp4")

        assert main([str(tmp_path)]) == 2

    def test_the_manifests_are_written_where_asked(self, tmp_path: Path) -> None:
        clips = tmp_path / "clips"
        clips.mkdir()
        touch(clips, "03_pullup_strict_face_05.mp4")
        touch(clips, "12_rest_deadhang_face_00.mp4")
        out = tmp_path / "manifests"

        assert main([str(clips), "--out-dir", str(out)]) == 0

        session = json.loads((out / "session.json").read_text())
        rest = json.loads((out / "session_rest.json").read_text())
        assert session["clips"][0]["reps"] == 5
        assert rest["clips"][0]["reps"] == 0
