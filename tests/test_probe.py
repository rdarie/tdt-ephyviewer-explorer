"""Tests for probe loading and channel reordering."""
from pathlib import Path

import numpy as np
import pytest

from tdt_ephyviewer_explorer.probe import ProbeMap, load_probe, reorder_channels

FIXTURE = Path(__file__).parent / "fixtures" / "probe_4ch.json"


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
