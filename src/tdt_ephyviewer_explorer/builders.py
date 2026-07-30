"""Build ephyviewer sources (and viewers) from loaded TDT stores."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from ephyviewer import (
    EpochViewer,
    EventList,
    InMemoryAnalogSignalSource,
    InMemoryEpochSource,
    InMemoryEventSource,
    InMemorySpikeSource,
    SpectrogramViewer,
    SpikeTrainViewer,
    TimeFreqViewer,
    TraceViewer,
)
from hydra.utils import instantiate

from tdt_ephyviewer_explorer.formatters.base import GenericFormatter, StimFormatter
from tdt_ephyviewer_explorer.probe import ProbeMap, load_probe, reorder_channels
from tdt_ephyviewer_explorer.stores import ResolvedStore
from tdt_ephyviewer_explorer.viewers.impedance_view import ImpedanceViewer


@dataclass
class Attachment:
    """One viewer attached to one store, with alignment options.

    :param viewer_type: Viewer key (e.g. ``"trace"``).
    :param delay_ms: Milliseconds added to the store's start time (any store type).
    :param probe_path: Optional probe file for reorder (timeseries only).
    :param params: Viewer parameter overrides.
    """

    viewer_type: str
    delay_ms: float = 0.0
    probe_path: Path | None = None
    params: dict[str, Any] = field(default_factory=dict)


def apply_delay(t_start: float, delay_ms: float) -> float:
    """Shift ``t_start`` by ``delay_ms`` milliseconds.

    Unit-agnostic — needs no sample rate, so it applies uniformly to streams,
    events, epochs, and snips.

    :param t_start: Original start time in seconds.
    :param delay_ms: Delay in milliseconds (may be negative).
    :returns: The shifted start time in seconds.
    """
    return float(t_start) + delay_ms / 1000.0


def build_analog_source(
    store: object, attachment: Attachment, probe: ProbeMap | None
) -> InMemoryAnalogSignalSource:
    """Build an analog source from a stream store, applying delay and optional reorder.

    :param store: Loaded stream store exposing ``data`` (n_channels, n_samples), ``fs``,
        ``start_time``.
    :param attachment: Alignment and probe options.
    :param probe: Loaded probe map, or ``None`` for acquisition order.
    :returns: The configured in-memory analog source.
    """
    data: np.ndarray = np.asarray(store.data)  # type: ignore[attr-defined]
    if data.ndim == 1:
        data = data[np.newaxis, :]  # single-channel stream -> (1, n_samples)
    fs: float = float(store.fs)  # type: ignore[attr-defined]
    if probe is not None:
        data = reorder_channels(data, probe)
        names = probe.names
    else:
        names = getattr(store, "channel_names", None) or [
            f"ch{k:0>2d}" for k in range(data.shape[0])
        ]
    signals = np.ascontiguousarray(data.T)  # samples x channels
    t_start = apply_delay(store.start_time, attachment.delay_ms)  # type: ignore[attr-defined]
    return InMemoryAnalogSignalSource(signals, fs, t_start=t_start, channel_names=names)


def scalar_rows(store: object, columns: Sequence[str]) -> list[dict[str, Any]]:
    """Turn a scalar store's ``data (n_params, n_events)`` into per-event dicts.

    :param store: Scalar store exposing ``data``.
    :param columns: Column names, one per param row (length must match ``data`` rows).
    :returns: One dict per event, mapping column name to value.
    :raises ValueError: If ``columns`` length does not match the number of param rows.
    """
    data = np.asarray(store.data)  # type: ignore[attr-defined]
    if data.ndim == 1:
        data = data[np.newaxis, :]
    if len(columns) != data.shape[0]:
        raise ValueError(
            f"schema has {len(columns)} columns but store has {data.shape[0]} param rows"
        )
    return [
        {col: data[p, i] for p, col in enumerate(columns)}
        for i in range(data.shape[1])
    ]


def build_event_source(
    store: object,
    columns: Sequence[str],
    formatter: StimFormatter,
    attachment: Attachment,
) -> InMemoryEventSource:
    """Build an event source from a scalar store using ``formatter`` for labels.

    :param store: Scalar store exposing ``data`` and ``ts``.
    :param columns: Column schema for the param rows.
    :param formatter: Row-to-label formatter.
    :param attachment: Alignment options; ``delay_ms`` shifts every timestamp.
    :raises ValueError: If the number of timestamps does not match the number of events.
    """
    rows = scalar_rows(store, columns)
    ts = np.asarray(store.ts, dtype=float)  # type: ignore[attr-defined]
    if ts.shape[0] != len(rows):
        raise ValueError(
            f"store has {ts.shape[0]} timestamps but {len(rows)} events"
        )
    labels = np.array([formatter.format_row(r) for r in rows])
    ts = ts + attachment.delay_ms / 1000.0
    return InMemoryEventSource(
        all_events=[{"name": attachment.viewer_type, "time": ts, "label": labels}]
    )


def build_event_source_from_frame(
    df: "pd.DataFrame",
    *,
    time_column: str,
    time_units: str,
    sampling_rate: float | None,
    label_column: str | None,
    formatter: StimFormatter | None,
    viewer_type: str,
    delay_ms: float,
) -> InMemoryEventSource:
    """Build an event source from a processed-parquet DataFrame.

    :param df: The loaded events DataFrame (one row per event).
    :param time_column: Column holding event onset.
    :param time_units: ``"samples"`` (converted via ``sampling_rate``) or ``"seconds"``.
    :param sampling_rate: Required when ``time_units == "samples"``.
    :param label_column: Column used directly for labels (takes precedence); else
        ``formatter`` is used, else integer indices.
    :param formatter: Row-to-label fallback formatter, or ``None``.
    :param viewer_type: Event source name (dock key).
    :param delay_ms: Milliseconds added to every timestamp.
    :raises ValueError: If ``time_units == "samples"`` without a ``sampling_rate``,
        or if ``label_column`` is given but not present in ``df``.
    """
    ts = df[time_column].to_numpy(dtype=float)
    if time_units == "samples":
        if not sampling_rate:
            raise ValueError("time_units='samples' requires a sampling_rate")
        ts = ts / float(sampling_rate)
    ts = ts + delay_ms / 1000.0
    if label_column:
        if label_column not in df.columns:
            raise ValueError(f"label_column {label_column!r} not in frame")
        labels = df[label_column].astype(str).to_numpy()
    elif formatter is not None:
        labels = np.array([formatter.format_row(row) for row in df.to_dict("records")])
    else:
        labels = np.array([str(i) for i in range(len(df))])
    return InMemoryEventSource(
        all_events=[{"name": viewer_type, "time": ts, "label": labels}]
    )


def build_epoch_source(store: object, attachment: Attachment) -> InMemoryEpochSource:
    """Build an epoch source from an epoc store (onset/offset).

    :param store: Epoc store exposing ``onset`` and ``offset``.
    :param attachment: Alignment options; ``delay_ms`` shifts onset and offset equally
        (so duration is unchanged).
    """
    delay_s = attachment.delay_ms / 1000.0
    onset = np.asarray(store.onset, dtype=float) + delay_s  # type: ignore[attr-defined]
    offset = np.asarray(store.offset, dtype=float) + delay_s  # type: ignore[attr-defined]
    duration = offset - onset
    labels = np.array([str(i) for i in range(onset.size)])
    return InMemoryEpochSource(
        all_epochs=[
            {"name": attachment.viewer_type, "time": onset, "duration": duration, "label": labels}
        ]
    )


def build_spike_source(
    store: object,
    attachment: Attachment,
    group_fields: Sequence[str] = ("chan", "sortcode"),
) -> InMemorySpikeSource:
    """Build a spike source from a snip/event store, one train per (chan, sortcode) group.

    Fields absent on the store are dropped from the grouping. If no grouping field is
    present, all timestamps form a single train.

    :param store: Store exposing ``ts`` OR ``onset`` (epoc stores), and optionally
        ``chan``/``sortcode``.
    :param attachment: Alignment options; ``delay_ms`` shifts every timestamp.
    :param group_fields: Ordered grouping fields to try.
    """
    raw_times = getattr(store, "ts", None)
    if raw_times is None:
        raw_times = getattr(store, "onset", None)  # epoc stores use onset as event times
    if raw_times is None:
        raise ValueError("store has neither 'ts' nor 'onset' for a spike train")
    ts = np.asarray(raw_times, dtype=float) + attachment.delay_ms / 1000.0
    # Only group by a field whose length matches the number of timestamps.
    present = [
        f
        for f in group_fields
        if getattr(store, f, None) is not None
        and np.asarray(getattr(store, f)).ravel().size == ts.size
    ]
    if not present:
        return InMemorySpikeSource(all_spikes=[{"name": attachment.viewer_type, "time": ts}])
    arrays = {f: np.asarray(getattr(store, f)).ravel() for f in present}
    keys = list(zip(*(arrays[f] for f in present)))
    spikes: list[dict] = []
    for key in sorted(set(keys)):
        mask = np.array([k == key for k in keys])
        label = " ".join(
            f"{'ch' if f == 'chan' else 'u'}{int(v):0>2d}" for f, v in zip(present, key)
        )
        spikes.append({"name": label, "time": ts[mask]})
    return InMemorySpikeSource(all_spikes=spikes)


_VIEWER_CLASSES = {
    "trace": TraceViewer,
    "timefreq": TimeFreqViewer,
    "spectrogram": SpectrogramViewer,
    "eventlist": EventList,
    "spiketrain": SpikeTrainViewer,
    "epoch": EpochViewer,
    "impedance": ImpedanceViewer,
}

_ANALOG_VIEWERS = frozenset({"trace", "timefreq", "spectrogram"})


def build_viewer(viewer_type: str, source: object, name: str, params: dict[str, Any]) -> object:
    """Construct an ephyviewer viewer and apply parameter overrides.

    :param viewer_type: Key into the viewer registry.
    :param source: A built ephyviewer source.
    :param name: Unique viewer name (dock key).
    :param params: Parameter overrides applied via ``view.params[key] = value``.
    :returns: The configured viewer.
    :raises KeyError: If ``viewer_type`` is unknown.
    """
    view = _VIEWER_CLASSES[viewer_type](source=source, name=name)
    for key, value in params.items():
        view.params[key] = value
    return view


def build_source_for(
    resolved: ResolvedStore, attachment: Attachment, store: object, schemas: dict[str, Any]
) -> object:
    """Dispatch to the correct source builder for one attachment.

    :param resolved: The resolved store (role, schema, formatter).
    :param attachment: The viewer attachment.
    :param store: The loaded raw tdt store.
    :param schemas: Mapping of schema name -> column list.
    :returns: An ephyviewer source.
    :raises ValueError: If the viewer type is not valid for the store's role.
    """
    vt = attachment.viewer_type
    if vt not in resolved.viewers:
        raise ValueError(f"viewer {vt!r} not valid for role {resolved.role!r}")
    if vt in _ANALOG_VIEWERS:
        probe = load_probe(attachment.probe_path) if attachment.probe_path else None
        return build_analog_source(store, attachment, probe)
    if vt == "epoch":
        return build_epoch_source(store, attachment)
    if vt == "spiketrain":
        return build_spike_source(store, attachment)
    # eventlist on a stim/event store
    data = np.asarray(store.data)  # type: ignore[attr-defined]
    columns = list(schemas.get(resolved.schema, [])) if resolved.schema else []
    if not columns:
        n_params = 1 if data.ndim == 1 else data.shape[0]
        columns = [f"col{p:0>2d}" for p in range(n_params)]
    formatter = instantiate(resolved.formatter) if resolved.formatter else GenericFormatter(columns)
    return build_event_source(store, columns, formatter, attachment)
