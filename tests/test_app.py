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
