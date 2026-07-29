"""Tests for the notes side panel."""
from datetime import datetime
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.metadata.notes import AnalysisNotes, Note, NotesFile
from tdt_ephyviewer_explorer.metadata.notes_panel import NotesPanel

HEADER = NotesFile("e", "s", "u", datetime(2026, 7, 27, 15, 48, 30), None, (), ())
NOW = datetime(2026, 7, 29, 14, 2, 14)


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def _model(tmp_path: Path) -> AnalysisNotes:
    return AnalysisNotes.load(tmp_path, "analysis_notes.txt", HEADER)


def test_readonly_view_lists_the_notes(qapp) -> None:
    panel = NotesPanel()
    panel.show_readonly(
        "blk", "Notes.txt · read-only",
        [Note(1, datetime(2026, 7, 27, 15, 49, 37), "first"),
         Note(2, datetime(2026, 7, 27, 15, 50, 16), "second")],
    )
    assert panel.row_count == 2  # no trailing blank row when read-only
    assert "blk" in panel.header_text
    assert "read-only" in panel.header_text
    assert panel.cell_text(0, 2) == "first"


def test_readonly_cells_are_not_editable(qapp) -> None:
    from PySide6.QtCore import Qt

    panel = NotesPanel()
    panel.show_readonly("blk", "Notes.txt · read-only",
                        [Note(1, datetime(2026, 7, 27, 15, 49, 37), "only")])
    assert not (panel.item_flags(0, 2) & Qt.ItemIsEditable)


def test_editable_view_has_a_trailing_blank_row(qapp, tmp_path) -> None:
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", _model(tmp_path), lambda: NOW)
    assert panel.row_count == 1  # just the blank entry row
    assert panel.cell_text(0, 2) == ""


def test_typing_in_the_blank_row_appends_and_saves(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    fired: list[int] = []
    panel.notes_changed.connect(lambda: fired.append(1))
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    panel.set_cell_text(0, 2, "EMG saturated")
    assert [n.text for n in model.notes] == ["EMG saturated"]
    assert model.path.exists()
    assert panel.row_count == 2  # a fresh blank row appeared
    assert fired == [1]


def test_new_note_is_stamped_with_the_injected_clock(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    panel.set_cell_text(0, 2, "stamped")
    assert model.notes[0].timestamp == NOW


def test_blank_input_is_ignored(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    panel.set_cell_text(0, 2, "   ")
    assert model.notes == ()
    assert not model.path.exists()


def test_editing_an_existing_row_saves(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    model.append("typo", NOW)
    model.save()
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    panel.set_cell_text(0, 2, "fixed")
    assert model.notes[0].text == "fixed"
    assert "fixed" in model.path.read_bytes().decode("utf-8")


def test_delete_removes_the_row_and_saves(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    model.append("one", NOW)
    model.append("two", NOW)
    model.save()
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    panel.delete_row(0)
    assert [n.text for n in model.notes] == ["two"]
    assert panel.row_count == 2  # one note plus the blank row


def test_timestamp_column_is_read_only(qapp, tmp_path) -> None:
    from PySide6.QtCore import Qt

    model = _model(tmp_path)
    model.append("one", NOW)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    assert not (panel.item_flags(0, 1) & Qt.ItemIsEditable)  # provenance is not editable
    assert panel.item_flags(0, 2) & Qt.ItemIsEditable


def test_a_conflicting_save_is_reported_and_not_silent(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    model.append("mine", NOW)
    model.save()

    other = _model(tmp_path)
    other.append("theirs", NOW)
    other.save()  # someone else writes

    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    panel.set_cell_text(panel.row_count - 1, 2, "mine again")

    assert "changed on disk" in panel.message_text  # (i) explained, not swallowed
    assert [n.text for n in model.notes] == ["mine", "theirs"]  # (ii) reloaded from disk
    assert model.path.read_bytes().decode("utf-8").count("theirs") == 1
    assert panel.cell_text(panel.row_count - 1, 2) == "mine again"  # (iii) pending text kept

    # (iv) the reload advanced the model's snapshot, so a retry now saves cleanly --
    # this would keep failing forever without AnalysisNotes.reload().
    panel.set_cell_text(panel.row_count - 1, 2, "mine again, resaved")
    assert panel.message_text == ""
    assert [n.text for n in model.notes] == ["mine", "theirs", "mine again, resaved"]
    assert "mine again, resaved" in model.path.read_bytes().decode("utf-8")


def test_a_write_failure_is_reported(qapp, tmp_path, monkeypatch) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    def boom(self, data):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "write_bytes", boom)
    panel.set_cell_text(0, 2, "nope")
    assert "read-only" in panel.message_text


def test_filling_the_table_never_mutates_the_model(qapp, tmp_path) -> None:
    """The ``_applying`` guard must stop programmatic table writes from being
    mistaken for user edits, independent of the ``text == existing text``
    shortcuts in ``_on_item_changed`` -- so this spies on the model's own
    ``append``/``edit`` rather than relying on those shortcuts to save it."""
    model = _model(tmp_path)
    model.append("one", NOW)
    model.save()

    calls: list[str] = []
    real_append = model.append
    real_edit = model.edit
    model.append = lambda text, now: (calls.append("append"), real_append(text, now))[1]  # type: ignore[method-assign]
    model.edit = lambda index, text: (calls.append("edit"), real_edit(index, text))[1]  # type: ignore[method-assign]

    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)  # populates via _fill
    panel.delete_row(0)
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)  # refill again

    assert calls == []


def test_switching_views_replaces_the_content(qapp, tmp_path) -> None:
    panel = NotesPanel()
    panel.show_readonly("blkA", "Notes.txt · read-only",
                        [Note(1, NOW, "a"), Note(2, NOW, "b")])
    panel.show_editable("blkB", "Analysis notes", _model(tmp_path), lambda: NOW)
    assert "blkB" in panel.header_text
    assert panel.row_count == 1  # the read-only rows are gone
