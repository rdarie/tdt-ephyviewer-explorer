"""TDT store model, header parsing, and lazy loading."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class StoreInfo:
    """Lightweight description of one TDT store, from a header-only scan.

    :param name: Store code, e.g. ``"Wav1"``.
    :param tdt_type: tdt ``type_str``: ``streams``/``scalars``/``epocs``/``snips``.
    :param fs: Sample rate in Hz (streams/snips), else ``None``.
    :param n_channels: Channel count where derivable.
    :param n_samples: Sample count where derivable.
    :param t_start: Store start time in seconds (0.0 if unknown until load).
    :param duration: Duration in seconds where derivable.
    """

    name: str
    tdt_type: str
    fs: float | None
    n_channels: int | None
    n_samples: int | None
    t_start: float
    duration: float | None


def _get(store: Mapping[str, Any] | object, key: str) -> Any:
    """Read ``key`` from a dict-like or attribute-based tdt store object."""
    try:
        return store[key]  # type: ignore[index]
    except (KeyError, TypeError):
        return getattr(store, key, None)


def store_info_from_header(name: str, store: Mapping[str, Any] | object) -> StoreInfo:
    """Build a :class:`StoreInfo` from one header-scan store entry.

    :param name: Store code.
    :param store: A tdt header store (dict-like or attribute object).
    :returns: The parsed store description.
    """
    fs_raw = _get(store, "fs")
    fs = float(fs_raw) if fs_raw else None
    chan = _get(store, "chan")
    n_channels = int(np.unique(np.ravel(chan)).size) if chan is not None else None
    start = _get(store, "start_time")
    t_start = float(start) if start is not None else 0.0
    return StoreInfo(
        name=name,
        tdt_type=str(_get(store, "type_str")),
        fs=fs,
        n_channels=n_channels,
        n_samples=None,
        t_start=t_start,
        duration=None,
    )
