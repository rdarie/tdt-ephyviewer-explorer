"""Build ephyviewer sources (and viewers) from loaded TDT stores."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from ephyviewer import InMemoryAnalogSignalSource

from tdt_ephyviewer_explorer.probe import ProbeMap, reorder_channels


@dataclass
class Attachment:
    """One viewer attached to one store, with alignment options.

    :param viewer_type: Viewer key (e.g. ``"trace"``).
    :param delay_samples: Samples added to the store's start time.
    :param probe_path: Optional probe file for reorder (timeseries only).
    :param params: Viewer parameter overrides.
    """

    viewer_type: str
    delay_samples: int = 0
    probe_path: Path | None = None
    params: dict = field(default_factory=dict)


def apply_delay(t_start: float, delay_samples: int, fs: float) -> float:
    """Shift ``t_start`` by ``delay_samples / fs`` seconds."""
    return float(t_start) + delay_samples / fs


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
    fs: float = float(store.fs)  # type: ignore[attr-defined]
    if probe is not None:
        data = reorder_channels(data, probe)
        names = probe.names
    else:
        names = [f"ch{k:0>2d}" for k in range(data.shape[0])]
    signals = np.ascontiguousarray(data.T)  # samples x channels
    t_start = apply_delay(store.start_time, attachment.delay_samples, fs)  # type: ignore[attr-defined]
    return InMemoryAnalogSignalSource(signals, fs, t_start=t_start, channel_names=names)
