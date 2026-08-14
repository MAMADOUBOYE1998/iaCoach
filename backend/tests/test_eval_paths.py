"""Clip resolution in the offline evaluation harness.

This is not biomechanics, and it earns a test file anyway. The harness once
reported `{"clips": 3, "scored": 0, "skipped": 3}` and exited 0 — a summary
shaped exactly like a measurement, produced by finding no videos at all. The
manifest was right about the filenames and wrong about the directory, and the
dataset's clips sat one level below where it looked.

So: three properties, all of them about telling "I measured nothing" apart from
"I measured something".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision.eval.evaluate import ClipLocator, _index_by_name, main


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


class TestIndexByName:
    def test_finds_a_clip_one_directory_below_the_manifest(self, tmp_path: Path) -> None:
        """The exact QUVA case: manifest says `082.mp4`, file is in `videos/`."""
        _touch(tmp_path / "videos" / "082_pullups.mp4")
        _touch(tmp_path / "annotations" / "082_pullups.npy")

        index = _index_by_name(tmp_path)

        assert index["082_pullups.mp4"] == [tmp_path / "videos" / "082_pullups.mp4"]

    def test_keeps_both_when_a_name_repeats(self, tmp_path: Path) -> None:
        """Two files, one name. The caller must be able to refuse.

        Returning the first hit would score one video against the other's
        annotation and report a number for it. A wrong count with a plausible
        provenance is worse than no count.
        """
        _touch(tmp_path / "session_a" / "clip.mp4")
        _touch(tmp_path / "session_b" / "clip.mp4")

        found = index_names(_index_by_name(tmp_path)["clip.mp4"])

        assert found == {"session_a/clip.mp4", "session_b/clip.mp4"}

    def test_ignores_directories(self, tmp_path: Path) -> None:
        """A directory named `clip.mp4` is not a clip, and would be opened as one."""
        (tmp_path / "clip.mp4").mkdir()
        _touch(tmp_path / "real" / "clip.mp4")

        assert _index_by_name(tmp_path)["clip.mp4"] == [tmp_path / "real" / "clip.mp4"]

    def test_empty_root_yields_no_names(self, tmp_path: Path) -> None:
        """The lookup has to fail cleanly, not raise — it is the missing-file path."""
        assert _index_by_name(tmp_path) == {}


def index_names(paths: list[Path]) -> set[str]:
    return {"/".join(p.parts[-2:]) for p in paths}


class TestFindingNothingIsAnError:
    """`main` never reaches MediaPipe here — every clip fails before scoring."""

    @staticmethod
    def _setup(tmp_path: Path, clips: list[str]) -> tuple[Path, Path]:
        manifest = tmp_path / "manifest.json"
        manifest.write_text(
            json.dumps({"clips": [{"path": c, "reps": 8} for c in clips]}),
            encoding="utf-8",
        )
        model = _touch(tmp_path / "pose.task")
        return manifest, model

    def test_exits_2_and_says_where_it_looked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        manifest, model = self._setup(tmp_path, ["clips/a.mp4", "clips/b.mp4"])

        code = main([str(manifest), "--model", str(model)])

        assert code == 2
        err = capsys.readouterr().err
        # The old harness exited 0 with an empty summary. The regression to
        # guard is the exit code; the message is what makes it actionable.
        assert str(tmp_path) in err
        assert "--clips-root" in err

    def test_a_missing_model_is_a_different_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Same exit code, and it must not be blamed on the clips.

        Both are setup errors and both return 2. Reporting "aucun clip trouvé"
        when the real problem is the pose model would send someone hunting
        through their dataset for a file that was never the issue.
        """
        manifest, _ = self._setup(tmp_path, ["clips/a.mp4"])

        assert main([str(manifest), "--model", str(tmp_path / "nope.task")]) == 2
        err = capsys.readouterr().err
        assert "Modèle de pose absent" in err
        assert "clip" not in err


class TestClipLocator:
    """The redirection itself, without MediaPipe in the way."""

    def test_the_manifest_being_right_costs_no_walk(self, tmp_path: Path) -> None:
        """A correct manifest must not pay for the recovery path.

        Asserted through the private index rather than a timing: the point is
        that the tree is never walked, not that walking it is fast.
        """
        _touch(tmp_path / "clips" / "a.mp4")
        locator = ClipLocator(tmp_path)

        path, note = locator.locate("clips/a.mp4")

        assert path == (tmp_path / "clips" / "a.mp4").resolve()
        assert note == ""
        assert locator._index is None

    def test_finds_the_clip_elsewhere_and_counts_it(self, tmp_path: Path) -> None:
        _touch(tmp_path / "videos" / "a.mp4")
        locator = ClipLocator(tmp_path)

        path, note = locator.locate("clips/a.mp4")

        assert path == (tmp_path / "videos" / "a.mp4").resolve()
        assert "retrouvé" in note
        assert locator.relocated == 1

    def test_refuses_an_ambiguous_name(self, tmp_path: Path) -> None:
        """Two candidates is not "found". Picking one would score a guess."""
        _touch(tmp_path / "run1" / "a.mp4")
        _touch(tmp_path / "run2" / "a.mp4")
        locator = ClipLocator(tmp_path)

        path, note = locator.locate("clips/a.mp4")

        assert path is None
        assert note == "nom ambigu (2 fichiers)"
        assert locator.relocated == 0

    def test_walks_once_across_many_misses(self, tmp_path: Path) -> None:
        _touch(tmp_path / "videos" / "a.mp4")
        _touch(tmp_path / "videos" / "b.mp4")
        locator = ClipLocator(tmp_path)

        locator.locate("clips/a.mp4")
        built = locator._index
        locator.locate("clips/b.mp4")

        assert locator._index is built
        assert locator.relocated == 2

    def test_a_genuinely_absent_clip_stays_absent(self, tmp_path: Path) -> None:
        assert ClipLocator(tmp_path).locate("clips/a.mp4") == (None, "fichier absent")
