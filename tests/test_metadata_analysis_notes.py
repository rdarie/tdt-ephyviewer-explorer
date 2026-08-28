"""Tests for the editable analysis-notes sidecar."""
from datetime import datetime
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.notes import (
    AnalysisNotes,
    NotesConflict,
    NotesFile,
    parse_notes,
)

FILENAME = "analysis_notes.txt"
HEADER = NotesFile(
    experiment="cnn_gp_mep_all_udp_v2",
    subject="Epi_02_Green",
    user="User",
    start=datetime(2026, 7, 27, 15, 48, 30),
    stop=datetime(2026, 7, 27, 15, 57, 38),
    notes=(),
    warnings=(),
)
T1 = datetime(2026, 7, 29, 14, 2, 14)
T2 = datetime(2026, 7, 29, 14, 5, 31)


def test_load_on_a_block_with_no_file(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    assert an.notes == ()
    assert an.path == tmp_path / "tdt_explore" / FILENAME  # writes land in the subfolder
    assert not an.path.exists()  # browsing must not create the file


def test_save_creates_the_tdt_explore_subfolder(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("x", T1)
    an.save()  # subfolder does not exist yet; save must create it
    assert an.path == tmp_path / "tdt_explore" / FILENAME
    assert (tmp_path / "tdt_explore").is_dir()
    assert an.path.is_file()


def test_append_and_save_creates_the_file(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("EMG saturated", T1)
    an.save()

    text = an.path.read_bytes().decode("utf-8")
    assert 'Note-1: 2:02:14pm 07/29/2026 "EMG saturated"' in text
    assert "Subject: Epi_02_Green" in text  # header copied from the recording
    assert text.endswith("\r\n")


def test_saved_file_reloads_identically(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("first", T1)
    an.append("second", T2)
    an.save()

    reloaded = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    assert [(n.index, n.timestamp, n.text) for n in reloaded.notes] == [
        (1, T1, "first"),
        (2, T2, "second"),
    ]


def test_edit_replaces_text_and_keeps_the_timestamp(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("typo", T1)
    an.edit(1, "fixed")
    assert an.notes[0].text == "fixed"
    assert an.notes[0].timestamp == T1  # provenance survives an edit


def test_delete_renumbers_the_rest(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    an.append("two", T2)
    an.delete(1)
    assert [(n.index, n.text) for n in an.notes] == [(1, "two")]


def test_delete_then_save_then_reload(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    an.append("two", T2)
    an.delete(1)
    an.save()
    assert [n.text for n in AnalysisNotes.load(tmp_path, FILENAME, HEADER).notes] == ["two"]


def test_edit_and_delete_reject_a_bad_index(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    with pytest.raises(IndexError):
        an.edit(2, "nope")
    with pytest.raises(IndexError):
        an.delete(0)


def test_save_refuses_when_the_file_changed_underneath(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("mine", T1)
    an.save()

    other = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    other.append("theirs", T2)
    other.save()  # a second editor writes

    an.append("mine again", T2)
    with pytest.raises(NotesConflict):
        an.save()  # stale snapshot must not clobber
    assert "theirs" in an.path.read_bytes().decode("utf-8")


def test_reload_after_a_conflict_picks_up_the_other_writers_notes(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("mine", T1)
    an.save()

    other = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    other.append("theirs", T2)
    other.save()

    an.append("mine again", T2)
    with pytest.raises(NotesConflict):
        an.save()

    an.reload()
    assert [n.text for n in an.notes] == ["mine", "theirs"]  # pending edit is gone


def test_reload_lets_a_subsequent_save_succeed(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("mine", T1)
    an.save()

    other = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    other.append("theirs", T2)
    other.save()

    an.append("mine again", T2)
    with pytest.raises(NotesConflict):
        an.save()

    an.reload()
    an.append("mine again", T2)
    an.save()  # would still raise NotesConflict without reload()

    text = an.path.read_bytes().decode("utf-8")
    assert "mine again" in text


def test_reload_clears_the_conflict(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("mine", T1)
    an.save()
    other = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    other.append("theirs", T2)
    other.save()

    fresh = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    fresh.append("mine again", T2)
    fresh.save()  # no conflict: snapshot is current
    assert [n.text for n in AnalysisNotes.load(tmp_path, FILENAME, HEADER).notes] == [
        "mine",
        "theirs",
        "mine again",
    ]


def test_save_on_an_unwritable_directory_raises(tmp_path: Path, monkeypatch) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("x", T1)

    def boom(self, data):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(OSError):
        an.save()  # must surface, never swallow


def test_header_is_preserved_from_an_existing_file(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    an.save()

    different = NotesFile(
        experiment="other", subject="other", user="other",
        start=None, stop=None, notes=(), warnings=(),
    )
    reloaded = AnalysisNotes.load(tmp_path, FILENAME, different)
    reloaded.append("two", T2)
    reloaded.save()

    text = an.path.read_bytes().decode("utf-8")
    assert "Subject: Epi_02_Green" in text  # the file's own header wins
    assert "Subject: other" not in text


def test_notes_are_ordered_and_indexed_after_several_appends(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    for i, moment in enumerate((T1, T2, datetime(2026, 7, 29, 15, 0, 0)), start=1):
        an.append(f"note {i}", moment)
    assert [n.index for n in an.notes] == [1, 2, 3]


def test_saved_text_parses_with_the_shared_parser(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("EMG saturated", T1)
    an.save()
    nf = parse_notes(an.path.read_bytes().decode("utf-8"))
    assert nf.notes[0].timestamp == T1
    assert nf.warnings == ()
