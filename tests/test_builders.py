"""Tests for ephyviewer source builders (Qt-free)."""
from dataclasses import dataclass

import numpy as np

from tdt_ephyviewer_explorer.builders import (
    Attachment,
    apply_delay,
    build_analog_source,
)
from tdt_ephyviewer_explorer.probe import ProbeMap


@dataclass
class FakeStream:
    data: np.ndarray
    fs: float
    start_time: float


def test_apply_delay_converts_samples_to_seconds() -> None:
    assert apply_delay(1.0, 20, 1000.0) == 1.02


def test_build_analog_source_shapes_and_tstart() -> None:
    store = FakeStream(data=np.zeros((4, 100)), fs=1000.0, start_time=0.5)
    src = build_analog_source(store, Attachment("trace", delay_samples=10), probe=None)
    assert src.signals.shape == (100, 4)  # samples x channels
    assert src.t_start == 0.51


def test_build_analog_source_applies_probe_reorder_and_names() -> None:
    store = FakeStream(data=np.array([[0.0], [1.0], [2.0], [3.0]]), fs=1000.0, start_time=0.0)
    probe = ProbeMap(order=np.array([3, 2, 1, 0]), names=["w", "x", "y", "z"])
    src = build_analog_source(store, Attachment("trace"), probe=probe)
    assert list(src.signals[0, :]) == [3.0, 2.0, 1.0, 0.0]
    assert src.channel_names == ["w", "x", "y", "z"]
