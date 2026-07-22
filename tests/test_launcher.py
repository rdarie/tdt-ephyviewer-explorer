"""Qt smoke tests for viewer building and the block launcher."""
import numpy as np
import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.builders import Attachment, build_viewer, build_analog_source


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_build_viewer_returns_trace_viewer(qapp) -> None:
    class S:
        data = np.zeros((2, 50))
        fs = 1000.0
        start_time = 0.0

    src = build_analog_source(S(), Attachment("trace"), probe=None)
    view = build_viewer("trace", src, name="Wav1:trace", params={"display_labels": True})
    assert view.name == "Wav1:trace"
    assert view.params["display_labels"] is True
