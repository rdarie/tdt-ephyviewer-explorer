"""Build ephyviewer sources (and viewers) from loaded TDT stores."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
from ephyviewer import (
    InMemoryAnalogSignalSource,
    InMemoryEpochSource,
    InMemoryEventSource,
    InMemorySpikeSource,
)

from tdt_ephyviewer_explorer.formatters.base import StimFormatter
from tdt_ephyviewer_explorer.probe import ProbeMap, reorder_channels


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
    params: dict = field(default_factory=dict)


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
        names = [f"ch{k:0>2d}" for k in range(data.shape[0])]
    signals = np.ascontiguousarray(data.T)  # samples x channels
    t_start = apply_delay(store.start_time, attachment.delay_ms)  # type: ignore[attr-defined]
    return InMemoryAnalogSignalSource(signals, fs, t_start=t_start, channel_names=names)


def scalar_rows(store: object, columns: Sequence[str]) -> list[dict]:
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

    :param store: Store exposing ``ts`` and optionally ``chan``/``sortcode``.
    :param attachment: Alignment options; ``delay_ms`` shifts every timestamp.
    :param group_fields: Ordered grouping fields to try.
    """
    ts = np.asarray(store.ts, dtype=float) + attachment.delay_ms / 1000.0  # type: ignore[attr-defined]
    present = [f for f in group_fields if getattr(store, f, None) is not None]
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
