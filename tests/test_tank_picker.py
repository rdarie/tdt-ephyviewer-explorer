"""Tests for the shared tank-directory picker."""
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from PySide6 import QtWidgets

from tdt_ephyviewer_explorer.tank_picker import TankPicker


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def _make_tank(tmp_path: Path) -> Path:
    tank = tmp_path / "tank"
    blk = tank / "blockA-1"
    blk.mkdir(parents=True)
    (blk / "blockA-1.tsq").write_bytes(b"")
    return tank


def test_the_picker_does_not_stretch_in_a_tall_layout(qapp, tmp_path) -> None:
    # A default size policy lets the one-row picker soak up the window's spare
    # height, pushing everything below it off the bottom.
    host = QtWidgets.QWidget()
    picker = TankPicker()
    below = QtWidgets.QSplitter()  # as in the metadata window: no vertical stretch of its own
    below.addWidget(QtWidgets.QTreeWidget())
    layout = QtWidgets.QVBoxLayout(host)
    layout.addWidget(picker)
    layout.addWidget(below)
    host.resize(900, 900)
    layout.activate()

    assert picker.height() <= picker.sizeHint().height()


def test_set_tank_adopts_and_emits(qapp, tmp_path) -> None:
    picker = TankPicker()
    seen: list[Path] = []
    picker.tank_changed.connect(seen.append)
    tank = _make_tank(tmp_path)

    assert picker.set_tank(tank) is True
    assert picker.tank_dir == tank
    assert seen == [tank]


def test_set_tank_rejects_tank_with_no_blocks(qapp, tmp_path) -> None:
    picker = TankPicker()
    seen: list[Path] = []
    picker.tank_changed.connect(seen.append)
    empty = tmp_path / "empty"
    empty.mkdir()

    assert picker.set_tank(empty) is False
    assert picker.tank_dir is None  # rejected paths are never adopted
    assert seen == []
    assert picker.message_text != ""


def test_set_tank_rejects_missing_directory(qapp, tmp_path) -> None:
    picker = TankPicker()
    assert picker.set_tank(tmp_path / "nope") is False
    assert picker.tank_dir is None
    assert picker.message_text != ""


def test_show_tank_adopts_without_emitting(qapp, tmp_path) -> None:
    picker = TankPicker()
    seen: list[Path] = []
    picker.tank_changed.connect(seen.append)
    tank = _make_tank(tmp_path)

    picker.show_tank(tank)
    assert picker.tank_dir == tank
    assert seen == []  # display-only: no signal, so no re-entrant reload


def test_message_clears_after_a_good_pick(qapp, tmp_path) -> None:
    picker = TankPicker()
    empty = tmp_path / "empty"
    empty.mkdir()
    picker.set_tank(empty)
    assert picker.message_text != ""

    picker.set_tank(_make_tank(tmp_path))
    assert picker.message_text == ""
