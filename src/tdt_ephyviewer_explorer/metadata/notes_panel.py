"""The side panel showing a block's read-only notes or its editable analysis notes."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from PySide6 import QtWidgets
from PySide6.QtCore import QPoint, Qt, Signal

from tdt_ephyviewer_explorer.metadata.notes import (
    AnalysisNotes,
    Note,
    NotesConflict,
    format_clock,
    format_day,
)

_COLUMNS = ("#", "Timestamp", "Note")


class NotesPanel(QtWidgets.QWidget):
    """A titled table of notes, either read-only or editable.

    The header names the block and the file, because several blocks may be expanded
    at once while only one panel is visible.
    """

    notes_changed = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """:param parent: Parent Qt widget."""
        super().__init__(parent)
        self._model: AnalysisNotes | None = None
        self._clock: Callable[[], datetime] = datetime.now
        self._editable = False
        self._applying = False

        self._header = QtWidgets.QLabel("")
        self._header.setWordWrap(True)
        self._message = QtWidgets.QLabel("")
        self._message.setWordWrap(True)
        self._message.setVisible(False)

        self._table = QtWidgets.QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemChanged.connect(self._on_item_changed)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._header)
        layout.addWidget(self._message)
        layout.addWidget(self._table)

    @property
    def header_text(self) -> str:
        """The panel's title line."""
        return self._header.text()

    @property
    def message_text(self) -> str:
        """The inline error message; empty when there is nothing to report."""
        return self._message.text()

    @property
    def row_count(self) -> int:
        """Number of table rows, including the trailing blank row when editable."""
        return self._table.rowCount()

    def cell_text(self, row: int, column: int) -> str:
        """Return the text of one cell.

        :param row: 0-based row.
        :param column: 0-based column.
        :returns: The cell text, or ``""`` when the cell is empty.
        """
        item = self._table.item(row, column)
        return "" if item is None else item.text()

    def item_flags(self, row: int, column: int) -> Qt.ItemFlags:
        """Return one cell's item flags, for checking editability.

        :param row: 0-based row.
        :param column: 0-based column.
        :returns: The Qt item flags.
        """
        item = self._table.item(row, column)
        return Qt.NoItemFlags if item is None else item.flags()

    def set_cell_text(self, row: int, column: int, text: str) -> None:
        """Set a cell's text as if the user had typed it, running the edit handler.

        :param row: 0-based row.
        :param column: 0-based column.
        :param text: The new text.
        """
        item = self._table.item(row, column)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self._table.setItem(row, column, item)
        item.setText(text)

    def show_readonly(self, block_name: str, title: str, notes: Sequence[Note]) -> None:
        """Display notes that cannot be edited.

        :param block_name: Block the notes belong to.
        :param title: Subtitle naming the source file.
        :param notes: The notes to list.
        """
        self._model = None
        self._editable = False
        self._set_header(block_name, title)
        self._set_message("")
        self._fill(notes, editable=False, blank_row=False)

    def show_editable(
        self,
        block_name: str,
        title: str,
        model: AnalysisNotes,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        """Display an editable analysis-notes table.

        :param block_name: Block the notes belong to.
        :param title: Subtitle naming the source file.
        :param model: The editing model, saved after every change.
        :param clock: Supplies the wall clock for new notes; injectable for tests.
        """
        self._model = model
        self._clock = clock
        self._editable = True
        self._set_header(block_name, title)
        self._set_message("")
        self._fill(model.notes, editable=True, blank_row=True)

    def delete_row(self, row: int) -> None:
        """Delete the note in ``row`` and save.

        :param row: 0-based row; the trailing blank row is ignored.
        """
        if self._model is None or row >= len(self._model.notes):
            return
        self._model.delete(self._model.notes[row].index)
        if self._save(pending_append_text=None):
            self._fill(self._model.notes, editable=True, blank_row=True)

    def _set_header(self, block_name: str, title: str) -> None:
        """Write the two-line panel title."""
        self._header.setText(f"{block_name}\n{title}")

    def _set_message(self, text: str) -> None:
        """Show ``text`` inline, hiding the label when empty."""
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def _fill(self, notes: Sequence[Note], editable: bool, blank_row: bool) -> None:
        """Rebuild the table from ``notes``.

        :param notes: Notes to show.
        :param editable: Whether the note column accepts edits.
        :param blank_row: Whether to append an empty entry row.
        """
        # Setting an item's text always re-emits itemChanged, including when done
        # programmatically here; this guard is what stops that from being mistaken
        # for a user edit and re-entering _on_item_changed while we repopulate.
        self._applying = True
        try:
            self._table.setRowCount(len(notes) + (1 if blank_row else 0))
            for row, note in enumerate(notes):
                self._put(row, 0, str(note.index), editable=False)
                self._put(row, 1, self._stamp(note), editable=False)
                self._put(row, 2, note.text, editable=editable)
            if blank_row:
                row = len(notes)
                self._put(row, 0, "", editable=False)
                self._put(row, 1, "", editable=False)
                self._put(row, 2, "", editable=True)
        finally:
            self._applying = False

    @staticmethod
    def _stamp(note: Note) -> str:
        """Format a note's timestamp as ``3:49:37pm 07/27/2026``."""
        return f"{format_clock(note.timestamp)} {format_day(note.timestamp)}"

    def _put(self, row: int, column: int, text: str, editable: bool) -> None:
        """Place one cell with the right editability."""
        item = QtWidgets.QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        self._table.setItem(row, column, item)

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        """Append or edit a note when the user finishes typing in the note column."""
        if self._applying or not self._editable or self._model is None:
            return
        if item.column() != 2:
            return
        row = item.row()
        text = item.text().strip()
        existing = self._model.notes

        if row < len(existing):
            if text == existing[row].text:
                return
            self._model.edit(existing[row].index, text)
            pending_append_text = None
        else:
            if not text:
                return  # an empty entry row is not a note
            self._model.append(text, self._clock())
            pending_append_text = text  # restored into the blank row on conflict

        if self._save(pending_append_text):
            self._fill(self._model.notes, editable=True, blank_row=True)

    def _save(self, pending_append_text: str | None) -> bool:
        """Save the model, recovering from a stale-file conflict and reporting failures inline.

        A :exc:`NotesConflict` must never wedge the panel: without recovery, the
        model's staleness snapshot would never advance and every later save would
        raise the same conflict forever. So on conflict this reloads the model from
        disk (picking up the current snapshot), refills the table from the reloaded
        notes, and -- if the change that triggered the save was a brand-new note
        typed into the trailing blank row -- puts that text back into a fresh blank
        row so the user loses nothing and can retry by pressing Enter again.

        :param pending_append_text: The raw text of a just-appended new note, or
            ``None`` when the save followed an edit or a delete. Only a pending
            *new* note is restored after a conflict; an in-progress edit of an
            existing row is discarded by :meth:`AnalysisNotes.reload` along with
            everything else not yet on disk.
        :returns: ``True`` when the save succeeded.
        """
        if self._model is None:
            return False
        try:
            self._model.save()
        except NotesConflict as exc:
            self._model.reload()
            self._fill(self._model.notes, editable=True, blank_row=True)
            if pending_append_text is not None:
                self._restore_pending_text(pending_append_text)
            self._set_message(
                f"{exc} Reloaded the latest version from disk; your note was not "
                "saved. Retype it to save again."
            )
            return False
        except OSError as exc:
            self._set_message(f"Could not save notes: {exc}")
            return False
        self._set_message("")
        self.notes_changed.emit()
        return True

    def _restore_pending_text(self, text: str) -> None:
        """Put ``text`` back into the trailing blank row without triggering a save.

        Used after a conflict reload discards an in-memory, not-yet-saved new note,
        so the user does not have to retype it from scratch.

        :param text: The note text to restore.
        """
        row = self._table.rowCount() - 1
        self._applying = True  # this write must not be mistaken for a new edit
        try:
            item = self._table.item(row, 2)
            if item is None:
                item = QtWidgets.QTableWidgetItem()
                self._table.setItem(row, 2, item)
            item.setText(text)
        finally:
            self._applying = False

    def _on_context_menu(self, point: QPoint) -> None:
        """Offer a delete action on the clicked row.

        :param point: Click position, in the table's viewport coordinates.
        """
        if not self._editable or self._model is None:
            return
        row = self._table.rowAt(point.y())
        if row < 0 or row >= len(self._model.notes):
            return
        menu = QtWidgets.QMenu(self)
        action = menu.addAction("Delete note")
        if menu.exec(self._table.viewport().mapToGlobal(point)) == action:
            self.delete_row(row)
