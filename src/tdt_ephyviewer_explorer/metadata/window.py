"""The tdt-metadata browser window: a tank picker, a block tree, and a notes panel."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from omegaconf import DictConfig
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.notes import (
    NOTES_FILENAME,
    AnalysisNotes,
    analysis_notes_path,
    read_notes,
)
from tdt_ephyviewer_explorer.metadata.notes_panel import NotesPanel
from tdt_ephyviewer_explorer.metadata.stim import format_voice_line, stim_config_from
from tdt_ephyviewer_explorer.metadata.summary import (
    BlockCache,
    BlockSummary,
    load_details,
    scan_tank,
)
from tdt_ephyviewer_explorer.tank_picker import TankPicker

LOADING_TEXT = "loading…"
WARNING_MARK = "⚠"


class _WorkerSignals(QtCore.QObject):
    """Signals for :class:`_Worker`; ``QRunnable`` cannot carry them itself."""

    done = Signal(object)
    failed = Signal(object)


class _Worker(QtCore.QRunnable):
    """Runs a callable on the thread pool and reports the outcome on the GUI thread."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        """:param fn: The work to run off the GUI thread."""
        super().__init__()
        self._fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        """Execute the callable, emitting ``done`` or ``failed``."""
        try:
            self.signals.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - reported, never raised into Qt
            self.signals.failed.emit(exc)


#: Workers that have been started but have not reported yet. ``QThreadPool.start``
#: does not keep the Python side of a runnable alive, and a collected worker takes
#: its signal object -- and with it the queued result -- down before delivery,
#: leaving the row stuck on "loading…" forever. Entries are dropped once the worker
#: has reported, so this never grows without bound.
_IN_FLIGHT: "set[_Worker]" = set()


def run_in_pool(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[BaseException], None],
) -> None:
    """Run ``fn`` on the global thread pool, delivering the result to the GUI thread.

    The worker is held in :data:`_IN_FLIGHT` until it reports, because the pool does
    not own the Python object and a garbage collection between ``start`` and the
    emit would silently discard the result.

    :param fn: The work to run.
    :param on_done: Called with the result on success.
    :param on_error: Called with the exception on failure.
    """
    worker = _Worker(fn)
    # Python, not Qt, owns this runnable's lifetime; see _IN_FLIGHT.
    worker.setAutoDelete(False)
    _IN_FLIGHT.add(worker)
    worker.signals.done.connect(on_done)
    worker.signals.failed.connect(on_error)
    # Connected last, so the caller's handler runs before the worker is released.
    worker.signals.done.connect(lambda _result: _IN_FLIGHT.discard(worker))
    worker.signals.failed.connect(lambda _exc: _IN_FLIGHT.discard(worker))
    QtCore.QThreadPool.globalInstance().start(worker)


def format_duration(seconds: float | None) -> str:
    """Format a duration as ``9m08s``, or ``—`` when unknown.

    :param seconds: Duration in seconds, or ``None``.
    :returns: The formatted duration.
    """
    if seconds is None:
        return "—"
    total = int(round(seconds))
    return f"{total // 60}m{total % 60:02d}s"


def format_start(start: datetime | None) -> str:
    """Format a start time as ``15:48:30``, or ``—`` when unknown.

    :param start: The start timestamp, or ``None``.
    :returns: The formatted time of day.
    """
    return "—" if start is None else start.strftime("%H:%M:%S")


class MetadataWindow(QtWidgets.QWidget):
    """Browse a tank's blocks and their session metadata.

    Text metadata for every block is read up front; the ``.tsq`` index and the stim
    parameter stores are read only when a block is expanded, and cached thereafter.
    """

    open_in_explorer_requested = Signal(object, str)  # (tank_dir: Path, block: str)

    def __init__(
        self,
        cfg: DictConfig | None = None,
        runner: Callable[
            [Callable[[], Any], Callable[[Any], None], Callable[[BaseException], None]], None
        ] = run_in_pool,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """:param cfg: Configuration; loaded from the packaged config when ``None``.
        :param runner: Schedules background work. Tests inject a synchronous one.
        :param parent: Parent Qt widget."""
        super().__init__(parent)
        self._cfg = cfg if cfg is not None else load_config()
        self._runner = runner
        self._cache = BlockCache()
        self._tank_dir: Path | None = None
        self._items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        self._loading: set[str] = set()

        self._picker = TankPicker()
        self._picker.tank_changed.connect(self.set_tank)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["#", "Block", "Start", "Duration"])
        # The counter owns column 0, so the expand arrows and the child indent move
        # to the block column beside it.
        self._tree.setTreePosition(1)
        self._tree.header().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)

        self._panel = NotesPanel()
        self._panel.setVisible(False)
        self._panel.notes_changed.connect(self._on_notes_changed)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self._tree)
        splitter.addWidget(self._panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._picker)
        layout.addWidget(splitter, 1)  # all spare height goes to the tree, not the picker
        self.setWindowTitle("tdt-metadata")

    @property
    def picker(self) -> TankPicker:
        """The tank picker at the top of the window."""
        return self._picker

    @property
    def panel(self) -> NotesPanel:
        """The notes side panel."""
        return self._panel

    @property
    def tank_dir(self) -> Path | None:
        """The tank currently browsed, or ``None``."""
        return self._tank_dir

    def set_tank(self, tank_dir: Path) -> None:
        """Scan a tank's text metadata and rebuild the block tree.

        :param tank_dir: The tank directory.
        """
        self._tank_dir = tank_dir
        self._picker.show_tank(tank_dir)
        self._cache.use_tank(tank_dir)
        self._panel.setVisible(False)
        self._tree.clear()
        self._items = {}
        self._loading = set()
        for summary in scan_tank(tank_dir):
            cached = self._cache.get(summary.name)
            if cached is None:
                self._cache.put(summary)
                cached = summary
            self._add_row(cached)
        self._fit_block_column()

    def _fit_block_column(self) -> None:
        """Widen the block column to its content, so names are not elided.

        The counter column takes width the block column used to have, and a fixed
        default is not enough for a full block name plus the indent.
        """
        self._tree.resizeColumnToContents(1)

    def block_names(self) -> list[str]:
        """The block names currently listed, in tree order."""
        return [
            self._tree.topLevelItem(i).data(0, Qt.UserRole)
            for i in range(self._tree.topLevelItemCount())
        ]

    def row_text(self, name: str) -> list[str]:
        """The collapsed-row columns for one block.

        :param name: Block name.
        :returns: ``[index, block, start, duration]``.
        """
        item = self._items[name]
        return [item.text(i) for i in range(4)]

    def detail_lines(self, name: str) -> list[str]:
        """The expanded child rows for one block, flattened depth-first.

        :param name: Block name.
        :returns: One string per child row.
        """
        out: list[str] = []

        def walk(node: QtWidgets.QTreeWidgetItem) -> None:
            """Append ``node``'s descendants, depth-first."""
            for i in range(node.childCount()):
                child = node.child(i)
                text = " ".join(t for t in (child.text(1), child.text(2)) if t)
                out.append(text)
                walk(child)

        walk(self._items[name])
        return out

    def expand_block(self, name: str) -> None:
        """Expand a block, loading its details on first expansion.

        :param name: Block name.
        """
        item = self._items[name]
        item.setExpanded(True)
        self._ensure_details(name)

    def open_notes(self, name: str) -> None:
        """Show the block's read-only ``Notes.txt`` in the side panel.

        :param name: Block name.
        """
        summary = self._require(name)
        self._panel.setVisible(True)
        self._panel.show_readonly(name, f"{NOTES_FILENAME} · read-only", summary.notes)

    def open_analysis_notes(self, name: str) -> None:
        """Show the block's editable analysis notes in the side panel.

        :param name: Block name.
        """
        summary = self._require(name)
        filename = str(self._cfg.metadata.analysis_notes_filename)
        header = read_notes(summary.path / NOTES_FILENAME)
        model = AnalysisNotes.load(summary.path, filename, header)
        self._panel.setVisible(True)
        self._panel.show_editable(name, f"Analysis notes · {filename}", model)

    def request_open_in_explorer(self, name: str) -> None:
        """Ask the application to open this block in tdt-explore.

        :param name: Block name.
        """
        if self._tank_dir is not None:
            self.open_in_explorer_requested.emit(self._tank_dir, name)

    def _require(self, name: str) -> BlockSummary:
        """Return the cached summary for ``name``.

        :param name: Block name.
        :returns: The cached summary.
        :raises KeyError: If the block is not listed.
        """
        summary = self._cache.get(name)
        if summary is None:
            raise KeyError(f"no such block: {name}")
        return summary

    def _add_row(self, summary: BlockSummary) -> None:
        """Add or refresh one block's top-level row and its children.

        :param summary: The summary to render.
        """
        item = self._items.get(summary.name)
        if item is None:
            item = QtWidgets.QTreeWidgetItem(self._tree)
            item.setData(0, Qt.UserRole, summary.name)
            self._items[summary.name] = item
        mark = f"{WARNING_MARK} " if summary.warnings else ""
        item.setText(0, str(self._tree.indexOfTopLevelItem(item)))
        item.setText(1, f"{mark}{summary.name}")
        item.setText(2, format_start(summary.start))
        item.setText(3, format_duration(summary.duration_s))
        self._rebuild_children(item, summary)

    def _rebuild_children(
        self, item: QtWidgets.QTreeWidgetItem, summary: BlockSummary
    ) -> None:
        """Replace a block row's children to match its current summary.

        :param item: The block's top-level row.
        :param summary: The summary to render.
        """
        item.takeChildren()
        for label, value in (
            ("Experiment", summary.experiment),
            ("Subject", summary.subject),
            ("User", summary.user),
        ):
            if value:
                self._child(item, label, value)

        gizmos = QtWidgets.QTreeWidgetItem(item, ["", "Gizmos", ""])
        if not summary.details_loaded:
            QtWidgets.QTreeWidgetItem(gizmos, ["", LOADING_TEXT, ""])
        for gizmo in summary.gizmos:
            kind = gizmo.kind or ""
            QtWidgets.QTreeWidgetItem(
                gizmos, ["", f"{gizmo.object_id}  {kind}".strip(), " ".join(gizmo.stores)]
            )

        if not summary.details_loaded:
            stim = QtWidgets.QTreeWidgetItem(item, ["", "Stimulation", ""])
            QtWidgets.QTreeWidgetItem(stim, ["", LOADING_TEXT, ""])
        elif summary.stim:
            settings, _ = stim_config_from(self._cfg)
            stim = QtWidgets.QTreeWidgetItem(item, ["", "Stimulation", ""])
            for entry in summary.stim:
                store_row = QtWidgets.QTreeWidgetItem(
                    stim,
                    [
                        "",
                        entry.store,
                        f"{entry.n_pulses} pulses · {entry.n_combinations} combinations",
                    ],
                )
                for voice in entry.voices:
                    QtWidgets.QTreeWidgetItem(
                        store_row,
                        ["", f"voice {voice.voice}", format_voice_line(voice, settings)],
                    )

        self._notes_row(item, "Notes", len(summary.notes), summary.name, analysis=False)
        self._notes_row(
            item, "Analysis notes", self._analysis_count(summary), summary.name, analysis=True
        )

        for warning in summary.warnings:
            self._child(item, WARNING_MARK, warning)

    def _analysis_count(self, summary: BlockSummary) -> int:
        """Count the block's saved analysis notes without creating the file.

        :param summary: The block's summary.
        :returns: The number of notes already on disk.
        """
        filename = str(self._cfg.metadata.analysis_notes_filename)
        return len(read_notes(analysis_notes_path(summary.path, filename)).notes)

    def _notes_row(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        label: str,
        count: int,
        block: str,
        analysis: bool,
    ) -> None:
        """Add a notes row carrying a count and an Expand button.

        :param parent: The block's top-level row.
        :param label: Row label.
        :param count: Number of notes in the file.
        :param block: Block name, bound into the button's handler.
        :param analysis: ``True`` for the editable analysis-notes row.
        """
        row = QtWidgets.QTreeWidgetItem(
            parent, ["", label, f"{count} note{'' if count == 1 else 's'}"]
        )
        button = QtWidgets.QPushButton("Expand")
        if analysis:
            button.clicked.connect(lambda: self.open_analysis_notes(block))
        else:
            button.clicked.connect(lambda: self.open_notes(block))
        self._tree.setItemWidget(row, 3, button)

    @staticmethod
    def _child(parent: QtWidgets.QTreeWidgetItem, label: str, value: str) -> None:
        """Add a simple label/value child row, leaving the counter column blank.

        :param parent: Row to add the child to.
        :param label: Block-column text.
        :param value: Start-column text.
        """
        QtWidgets.QTreeWidgetItem(parent, ["", label, value])

    def _ensure_details(self, name: str) -> None:
        """Load a block's tier-1 and tier-2 data once, off the GUI thread.

        Expanding a row schedules this twice -- once explicitly and once through
        ``itemExpanded`` -- and ``details_loaded`` does not go true until the load
        lands, so an in-flight block is tracked separately. Without it, every
        expansion reads the whole stim store twice.

        :param name: Block name.
        """
        summary = self._require(name)
        if summary.details_loaded or name in self._loading:
            return
        self._loading.add(name)
        self._runner(
            lambda: load_details(summary, self._cfg),
            lambda result: self._on_details(result),
            lambda exc: self._on_details_failed(name, exc),
        )

    def _on_details(self, summary: BlockSummary) -> None:
        """Cache and render a loaded summary.

        :param summary: The summary returned by the worker.
        """
        self._loading.discard(summary.name)
        if summary.name not in self._items:
            return  # the tank was switched while this was loading
        self._cache.put(summary)
        self._add_row(summary)
        self._items[summary.name].setExpanded(True)
        self._fit_block_column()  # the new child rows are wider than the collapsed ones

    def _on_details_failed(self, name: str, exc: BaseException) -> None:
        """Record a worker failure on the block's row rather than raising.

        :param name: Block whose load failed.
        :param exc: The exception the worker raised.
        """
        from dataclasses import replace

        self._loading.discard(name)
        if name not in self._items:
            return  # the tank was switched while this was loading
        summary = self._require(name)
        failed = replace(
            summary,
            warnings=summary.warnings + (f"could not load details: {exc}",),
            details_loaded=True,
        )
        self._cache.put(failed)
        self._add_row(failed)
        self._items[name].setExpanded(True)

    def _on_item_expanded(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Load details when a top-level block row is expanded.

        :param item: The row that was expanded.
        """
        name = item.data(0, Qt.UserRole)
        if name:
            self._ensure_details(name)

    def _on_notes_changed(self) -> None:
        """Refresh note counts after the panel saves."""
        for name in list(self._items):
            self._add_row(self._require(name))

    def _top_level_name(self, item: QtWidgets.QTreeWidgetItem | None) -> str | None:
        """Walk up to the owning block row and return its name.

        :param item: Any row in the tree, or ``None``.
        :returns: The owning block's name, or ``None``.
        """
        while item is not None:
            name = item.data(0, Qt.UserRole)
            if name:
                return str(name)
            item = item.parent()
        return None

    def _on_context_menu(self, point: QtCore.QPoint) -> None:
        """Offer 'Open in tdt-explore' on the clicked block.

        :param point: Click position, in tree-viewport coordinates.
        """
        name = self._top_level_name(self._tree.itemAt(point))
        if name is None:
            return
        menu = QtWidgets.QMenu(self)
        action = menu.addAction("Open in tdt-explore")
        if menu.exec(self._tree.viewport().mapToGlobal(point)) == action:
            self.request_open_in_explorer(name)

    def _on_double_click(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        """Double-clicking a block opens it in tdt-explore.

        :param item: The row that was double-clicked.
        :param _column: The clicked column; unused.
        """
        name = self._top_level_name(item)
        if name is not None:
            self.request_open_in_explorer(name)
