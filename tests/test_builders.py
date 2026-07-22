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


from dataclasses import dataclass as _dc

from tdt_ephyviewer_explorer.builders import (
    build_epoch_source,
    build_event_source,
    build_spike_source,
    scalar_rows,
)
from tdt_ephyviewer_explorer.formatters.iz_voice import IZVoiceFormatter


@_dc
class FakeScalar:
    data: np.ndarray
    ts: np.ndarray


def test_scalar_rows_zips_columns() -> None:
    store = FakeScalar(data=np.array([[5, 6], [10, 20]]), ts=np.array([0.0, 1.0]))
    rows = scalar_rows(store, ["chanA", "ampA"])
    assert rows == [{"chanA": 5, "ampA": 10}, {"chanA": 6, "ampA": 20}]


def test_build_event_source_uses_formatter_and_delay() -> None:
    store = FakeScalar(
        data=np.array([[5, 0], [0, 0], [0, 0], [0, 0],  # chanA, chanB, chanC, chanD
                       [100, 0], [0, 0], [0, 0], [0, 0]]),  # ampA..ampD
        ts=np.array([2.0]),
    )
    cols = ["chanA", "chanB", "chanC", "chanD", "ampA", "ampB", "ampC", "ampD"]
    src = build_event_source(store, cols, IZVoiceFormatter(), Attachment("eventlist"))
    ev = src.all[0]  # ephyviewer stores channel dicts under `.all`
    assert ev["label"][0] == "chA: 05 100 uA"
    assert ev["time"][0] == 2.0


@_dc
class FakeEpoc:
    onset: np.ndarray
    offset: np.ndarray


def test_build_epoch_source_computes_duration() -> None:
    store = FakeEpoc(onset=np.array([1.0, 3.0]), offset=np.array([1.5, 3.25]))
    src = build_epoch_source(store, Attachment("epoch"))
    ep = src.all[0]
    assert list(ep["time"]) == [1.0, 3.0]
    assert list(np.round(ep["duration"], 2)) == [0.5, 0.25]


@_dc
class FakeSnip:
    ts: np.ndarray
    chan: np.ndarray
    sortcode: np.ndarray


def test_build_spike_source_groups_by_chan_sortcode() -> None:
    store = FakeSnip(
        ts=np.array([0.1, 0.2, 0.3]),
        chan=np.array([1, 1, 2]),
        sortcode=np.array([1, 1, 1]),
    )
    src = build_spike_source(store, Attachment("spiketrain"))
    names = sorted(s["name"] for s in src.all)
    assert names == ["ch01 u01", "ch02 u01"]
