"""Tests for probe loading and channel reordering."""
from pathlib import Path

import numpy as np
import pytest

from tdt_ephyviewer_explorer.probe import (
    Layout,
    ProbeMap,
    load_probe,
    probe_layout,
    reorder_channels,
)

FIXTURE = Path(__file__).parent / "fixtures" / "probe_4ch.json"
TOPO_FIXTURE = Path(__file__).parent / "fixtures" / "probe_topo_4ch.json"
DUP_FIXTURE = Path(__file__).parent / "fixtures" / "probe_dup_topo_2ch.json"


def test_load_probe_reads_order_and_names() -> None:
    probe = load_probe(FIXTURE)
    assert list(probe.order) == [3, 2, 1, 0]
    assert probe.names == ["A 00", "B 01", "C 02", "D 03"]


def test_reorder_channels_permutes_rows() -> None:
    probe = load_probe(FIXTURE)
    data = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])  # channel i has value i
    out = reorder_channels(data, probe)
    assert list(out[:, 0]) == [3, 2, 1, 0]


def test_reorder_channels_count_mismatch_raises() -> None:
    probe = load_probe(FIXTURE)
    with pytest.raises(ValueError, match="channel count"):
        reorder_channels(np.zeros((3, 10)), probe)


def test_probe_layout_uses_topo_annotations() -> None:
    # topo_x [1,0,1,0] / topo_y [0,0,1,1] -> a 2x2 grid, overriding the 1x4
    # arrangement that contact_positions alone would imply.
    layout = probe_layout(TOPO_FIXTURE)
    assert isinstance(layout, Layout)
    assert (layout.n_cols, layout.n_rows) == (2, 2)
    assert list(layout.col) == [1, 0, 1, 0]
    assert list(layout.row) == [0, 0, 1, 1]


def test_probe_layout_infers_from_contact_positions() -> None:
    # probe_4ch.json has no topo annotations: x is constant, y is 0/100/200/300,
    # so the contacts infer to a single column of four rows.
    layout = probe_layout(FIXTURE)
    assert (layout.n_cols, layout.n_rows) == (1, 4)
    assert list(layout.col) == [0, 0, 0, 0]
    assert list(layout.row) == [0, 1, 2, 3]


def test_probe_layout_duplicate_cell_raises() -> None:
    with pytest.raises(ValueError, match="both map to grid cell"):
        probe_layout(DUP_FIXTURE)
