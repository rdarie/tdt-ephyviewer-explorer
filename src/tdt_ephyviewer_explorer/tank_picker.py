"""A shared tank-directory picker, used by both the explorer and the metadata app."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtCore import Signal

from tdt_ephyviewer_explorer.tank import list_blocks


class TankPicker(QtWidgets.QWidget):
    """A read-only path field, a Browse button, and an inline validation message.

    :attr:`tank_changed` fires only for directories holding at least one block, so
    consumers never have to re-validate. Use :meth:`show_tank` to reflect a tank
    adopted elsewhere without triggering that signal.
    """

    tank_changed = Signal(object)  # emits a Path

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """:param parent: Parent Qt widget."""
        super().__init__(parent)
        self._tank_dir: Path | None = None

        self._field = QtWidgets.QLineEdit()
        self._field.setReadOnly(True)
        self._field.setPlaceholderText("No tank selected")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        self._message = QtWidgets.QLabel("")
        self._message.setWordWrap(True)
        self._message.setVisible(False)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Tank"))
        row.addWidget(self._field, 1)
        row.addWidget(browse)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self._message)
        # One row of controls: never taller than it needs to be, or it soaks up the
        # host window's spare height and squeezes whatever sits below it.
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum
        )

    @property
    def tank_dir(self) -> Path | None:
        """The currently adopted tank directory, or ``None``."""
        return self._tank_dir

    @property
    def message_text(self) -> str:
        """The inline validation message; empty when there is nothing to report."""
        return self._message.text()

    def set_tank(self, tank_dir: Path) -> bool:
        """Validate a tank, adopt it, and emit :attr:`tank_changed`.

        A directory that does not exist or holds no blocks is reported inline and
        left unadopted, so a bad pick never clears a good one.

        :param tank_dir: Candidate Synapse tank directory.
        :returns: ``True`` if the tank was adopted.
        """
        problem = self._validate(tank_dir)
        if problem is not None:
            self._set_message(problem)
            return False
        self.show_tank(tank_dir)
        self.tank_changed.emit(tank_dir)
        return True

    def show_tank(self, tank_dir: Path) -> None:
        """Display a tank adopted elsewhere, without emitting :attr:`tank_changed`.

        Consumers call this from their own ``set_tank`` so that a programmatic tank
        change updates the field without bouncing a signal back and re-entering.

        :param tank_dir: The tank directory to display.
        """
        self._tank_dir = tank_dir
        self._field.setText(str(tank_dir))
        self._set_message("")

    @staticmethod
    def _validate(tank_dir: Path) -> str | None:
        """Return a human-readable problem with ``tank_dir``, or ``None`` if it is fine."""
        if not tank_dir.is_dir():
            return f"Not a directory: {tank_dir}"
        if not list_blocks(tank_dir):
            return f"No blocks found in {tank_dir}"
        return None

    def _set_message(self, text: str) -> None:
        """Show ``text`` inline, hiding the label when empty."""
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def _on_browse(self) -> None:
        """Prompt for a directory and try to adopt it."""
        start = str(self._tank_dir) if self._tank_dir is not None else ""
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select tank directory", start
        )
        if chosen:
            self.set_tank(Path(chosen))
