"""Tests for the tdt-metadata entry point."""
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.metadata.app import MetadataApp


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_constructs_a_window(qapp) -> None:
    app = MetadataApp()
    assert app.window is not None
    assert app.explorers == []


def test_open_in_explorer_launches_the_control_window(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import app as mod

    opened: list[tuple] = []

    class _FakeApp:
        def __init__(self, cfg=None):
            self.control_window = _FakeControl()

        def open_tank(self, tank_dir, block=None):
            opened.append((tank_dir, block))

    class _FakeControl:
        def show(self):
            pass

    monkeypatch.setattr(mod, "App", _FakeApp)
    app = MetadataApp()
    app.window.open_in_explorer_requested.emit(tmp_path, "blk")

    assert opened == [(tmp_path, "blk")]
    assert len(app.explorers) == 1


def test_main_without_tank_returns_zero(qapp, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import app as mod

    class _FakeQApp:
        def exec(self):
            return 0

    monkeypatch.setattr(mod, "mkQApp", lambda: _FakeQApp())
    assert mod.main([]) == 0


def test_main_with_a_tank_loads_it(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import app as mod

    tank = tmp_path / "tank"
    blk = tank / "blk-1"
    blk.mkdir(parents=True)
    (blk / "blk-1.tsq").write_bytes(b"")

    class _FakeQApp:
        def exec(self):
            return 0

    seen: list[Path] = []
    monkeypatch.setattr(mod, "mkQApp", lambda: _FakeQApp())
    monkeypatch.setattr(mod.MetadataWindow, "set_tank", lambda self, t: seen.append(t))
    assert mod.main(["--tank", str(tank)]) == 0
    assert seen == [tank]
