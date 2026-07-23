"""Smoke tests for the app orchestrator."""
import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.app import App


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_app_constructs_control_window(qapp) -> None:
    app = App()
    assert app.control_window is not None
    assert app.windows == []


def test_on_launch_threads_control_window_headers(qapp, monkeypatch) -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer import app as app_mod
    from tdt_ephyviewer_explorer.session import Session

    captured: dict = {}

    def fake_launch_block(block_path, session, cfg, headers=None):
        captured["headers"] = headers

        class _Win:
            def show(self):
                pass

        return _Win()

    monkeypatch.setattr(app_mod, "launch_block", fake_launch_block)
    app = App()
    app._tank_dir = Path("tank")
    heads = object()
    app.control_window._headers = heads  # as if a block was scanned
    app._on_launch(Session(block="blk", attachments={}))
    assert captured["headers"] is heads  # reuse the already-parsed index at launch
