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


def test_apply_delay_converts_ms_to_seconds() -> None:
    assert apply_delay(1.0, 20.0) == 1.02


def test_build_analog_source_shapes_and_tstart() -> None:
    store = FakeStream(data=np.zeros((4, 100)), fs=1000.0, start_time=0.5)
    src = build_analog_source(store, Attachment("trace", delay_ms=10.0), probe=None)
    assert src.signals.shape == (100, 4)  # samples x channels
    assert src.t_start == 0.51


def test_build_analog_source_handles_1d_single_channel() -> None:
    store = FakeStream(data=np.arange(50.0), fs=1000.0, start_time=0.0)  # 1-D
    src = build_analog_source(store, Attachment("trace"), probe=None)
    assert src.signals.shape == (50, 1)
    assert src.channel_names == ["ch00"]


def test_build_analog_source_applies_probe_reorder_and_names() -> None:
    store = FakeStream(data=np.array([[0.0], [1.0], [2.0], [3.0]]), fs=1000.0, start_time=0.0)
    probe = ProbeMap(order=np.array([3, 2, 1, 0]), names=["w", "x", "y", "z"])
    src = build_analog_source(store, Attachment("trace"), probe=probe)
    assert list(src.signals[0, :]) == [3.0, 2.0, 1.0, 0.0]
    assert src.channel_names == ["w", "x", "y", "z"]


from dataclasses import dataclass as _dc

import pytest

from tdt_ephyviewer_explorer.builders import (
    build_epoch_source,
    build_event_source,
    build_spike_source,
    scalar_rows,
)
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter
from tdt_ephyviewer_explorer.formatters.iz_voice import IZVoiceFormatter


@_dc
class FakeScalar:
    data: np.ndarray
    ts: np.ndarray


def test_scalar_rows_zips_columns() -> None:
    store = FakeScalar(data=np.array([[5, 6], [10, 20]]), ts=np.array([0.0, 1.0]))
    rows = scalar_rows(store, ["chanA", "ampA"])
    assert rows == [{"chanA": 5, "ampA": 10}, {"chanA": 6, "ampA": 20}]


def test_scalar_rows_reshapes_1d_data() -> None:
    store = FakeScalar(data=np.array([5, 6, 7]), ts=np.array([0.0, 1.0, 2.0]))
    rows = scalar_rows(store, ["chanA"])
    assert rows == [{"chanA": 5}, {"chanA": 6}, {"chanA": 7}]


def test_scalar_rows_column_mismatch_raises() -> None:
    store = FakeScalar(data=np.array([[5, 6], [10, 20]]), ts=np.array([0.0, 1.0]))
    with pytest.raises(ValueError, match="columns"):
        scalar_rows(store, ["chanA"])


def test_build_event_source_uses_formatter_and_applies_delay() -> None:
    store = FakeScalar(
        data=np.array([[5], [0], [0], [0],   # chanA, chanB, chanC, chanD
                       [100], [0], [0], [0]]),  # ampA..ampD
        ts=np.array([2.0]),
    )
    cols = ["chanA", "chanB", "chanC", "chanD", "ampA", "ampB", "ampC", "ampD"]
    # 1000 ms delay -> +1.0 s.
    src = build_event_source(store, cols, IZVoiceFormatter(), Attachment("eventlist", delay_ms=1000.0))
    ev = src.all[0]  # ephyviewer stores channel dicts under `.all`
    assert ev["label"][0] == "chA: 05 100 uA"
    assert ev["time"][0] == 3.0


def test_build_event_source_ts_length_mismatch_raises() -> None:
    store = FakeScalar(data=np.array([[5, 6]]), ts=np.array([2.0]))  # 2 events, 1 ts
    with pytest.raises(ValueError, match="timestamps"):
        build_event_source(store, ["chanA"], GenericFormatter(["chanA"]), Attachment("eventlist"))


@_dc
class FakeEpoc:
    onset: np.ndarray
    offset: np.ndarray


def test_build_epoch_source_computes_duration_and_applies_delay() -> None:
    store = FakeEpoc(onset=np.array([1.0, 3.0]), offset=np.array([1.5, 3.25]))
    src = build_epoch_source(store, Attachment("epoch", delay_ms=500.0))  # +0.5 s
    ep = src.all[0]
    assert list(ep["time"]) == [1.5, 3.5]
    assert list(np.round(ep["duration"], 2)) == [0.5, 0.25]  # duration is delay-invariant


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


@_dc
class FakeBareSpikes:
    ts: np.ndarray


def test_build_spike_source_single_train_when_ungrouped() -> None:
    store = FakeBareSpikes(ts=np.array([0.1, 0.2]))
    src = build_spike_source(store, Attachment("spiketrain"))
    assert len(src.all) == 1
    assert list(src.all[0]["time"]) == [0.1, 0.2]


def test_build_spike_source_ignores_mismatched_group_field() -> None:
    @_dc
    class FakeMismatch:
        ts: np.ndarray
        chan: np.ndarray

    store = FakeMismatch(ts=np.arange(5.0), chan=np.array([1]))  # chan len 1 != ts len 5
    src = build_spike_source(store, Attachment("spiketrain"))
    assert len(src.all) == 1
    assert list(src.all[0]["time"]) == [0.0, 1.0, 2.0, 3.0, 4.0]


from tdt_ephyviewer_explorer.builders import build_source_for
from tdt_ephyviewer_explorer.stores import ResolvedStore, StoreInfo


def _resolved(role, viewers, schema=None, formatter=None):
    info = StoreInfo("X", "scalars", None, 1, None, 0.0, None)
    return ResolvedStore(info, role, schema, viewers, formatter)


def test_build_source_for_rejects_invalid_viewer() -> None:
    resolved = _resolved("timeseries", ("trace",))
    store = FakeStream(data=np.zeros((2, 5)), fs=1000.0, start_time=0.0)
    with pytest.raises(ValueError, match="not valid"):
        build_source_for(resolved, Attachment("eventlist"), store, {})


def test_build_source_for_analog() -> None:
    from ephyviewer import InMemoryAnalogSignalSource
    resolved = _resolved("timeseries", ("trace",))
    store = FakeStream(data=np.zeros((2, 5)), fs=1000.0, start_time=0.0)
    src = build_source_for(resolved, Attachment("trace"), store, {})
    assert isinstance(src, InMemoryAnalogSignalSource)


def test_build_source_for_eventlist_schemaless_1d() -> None:
    from ephyviewer import InMemoryEventSource
    resolved = _resolved("event", ("eventlist", "spiketrain"))
    store = FakeScalar(data=np.arange(4.0), ts=np.arange(4.0))  # 1-D -> 1 param row
    src = build_source_for(resolved, Attachment("eventlist"), store, {})
    assert isinstance(src, InMemoryEventSource)
    assert len(src.all[0]["time"]) == 4  # 4 events, single placeholder col00


def test_build_source_for_eventlist_with_schema_generic_formatter() -> None:
    resolved = _resolved("stim", ("eventlist",), schema="iz")
    store = FakeScalar(data=np.array([[5.0, 6.0]]), ts=np.array([0.0, 1.0]))
    src = build_source_for(resolved, Attachment("eventlist"), store, {"iz": ["chanA"]})
    assert src.all[0]["label"][0] == "chanA: 5.0"


def test_build_source_for_spiketrain_on_event() -> None:
    from ephyviewer import InMemorySpikeSource
    resolved = _resolved("event", ("eventlist", "spiketrain"))
    store = FakeScalar(data=np.arange(3.0), ts=np.arange(3.0))
    src = build_source_for(resolved, Attachment("spiketrain"), store, {})
    assert isinstance(src, InMemorySpikeSource)


def test_build_source_for_epoch_and_spiketrain_on_epoch() -> None:
    from ephyviewer import InMemoryEpochSource, InMemorySpikeSource
    resolved = _resolved("epoch", ("epoch", "spiketrain"))
    store = FakeEpoc(onset=np.array([1.0, 2.0]), offset=np.array([1.5, 2.5]))
    ep = build_source_for(resolved, Attachment("epoch"), store, {})
    assert isinstance(ep, InMemoryEpochSource)
    sp = build_source_for(resolved, Attachment("spiketrain"), store, {})  # onset fallback
    assert isinstance(sp, InMemorySpikeSource)
    assert list(sp.all[0]["time"]) == [1.0, 2.0]


import pandas as pd

from tdt_ephyviewer_explorer.builders import build_event_source_from_frame
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter


@dataclass
class FakeNamedStream:
    data: np.ndarray
    fs: float
    start_time: float
    channel_names: list


def test_build_analog_source_uses_store_channel_names() -> None:
    store = FakeNamedStream(data=np.zeros((2, 10)), fs=1000.0, start_time=0.0,
                            channel_names=["pulse", "blanking"])
    src = build_analog_source(store, Attachment("trace"), probe=None)
    assert src.channel_names == ["pulse", "blanking"]


def test_build_event_source_from_frame_samples_to_seconds_and_label() -> None:
    df = pd.DataFrame({"timestamp_sample": [24414, 48828], "stim_site": ["E1", "E2"]})
    src = build_event_source_from_frame(
        df, time_column="timestamp_sample", time_units="samples",
        sampling_rate=24414.0625, label_column="stim_site", formatter=None,
        viewer_type="eventlist", delay_ms=0.0,
    )
    ev = src.all[0]
    assert abs(ev["time"][0] - 24414 / 24414.0625) < 1e-9
    assert list(ev["label"]) == ["E1", "E2"]


def test_build_event_source_from_frame_delay_and_formatter_fallback() -> None:
    df = pd.DataFrame({"timestamp": [1.0], "ampA": [100]})
    src = build_event_source_from_frame(
        df, time_column="timestamp", time_units="seconds", sampling_rate=None,
        label_column=None, formatter=GenericFormatter(["ampA"]),
        viewer_type="eventlist", delay_ms=20.0,
    )
    ev = src.all[0]
    assert ev["time"][0] == 1.02
    assert ev["label"][0] == "ampA: 100"


def test_build_event_source_from_frame_missing_label_column_raises() -> None:
    import pytest
    df = pd.DataFrame({"timestamp": [1.0], "stim_site": ["E1"]})
    with pytest.raises(ValueError, match="label_column"):
        build_event_source_from_frame(
            df, time_column="timestamp", time_units="seconds", sampling_rate=None,
            label_column="does_not_exist", formatter=None,
            viewer_type="eventlist", delay_ms=0.0,
        )


def test_build_viewer_epochencoder(tmp_path) -> None:
    import pytest
    pytest.importorskip("ephyviewer")
    from ephyviewer import EpochEncoder, mkQApp

    from tdt_ephyviewer_explorer.annotations import build_annotation_source, resolve_labels_path
    from tdt_ephyviewer_explorer.builders import build_viewer
    from tdt_ephyviewer_explorer.config_schema import load_config

    mkQApp()
    cfg = load_config()
    block = tmp_path / "blk"
    block.mkdir()
    src = build_annotation_source(block, resolve_labels_path(cfg), cfg)
    view = build_viewer("epochencoder", src, name="annotations", params={})
    assert isinstance(view, EpochEncoder)
    assert view.name == "annotations"
