"""Probe loading (probeinterface) and probe-native channel reordering."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from probeinterface import read_probeinterface


@dataclass(frozen=True)
class ProbeMap:
    """Channel reordering map derived from a probeinterface file.

    :param order: For displayed channel ``k``, the raw acquisition channel index
        (``device_channel_indices`` in contact order).
    :param names: Display name per contact-ordered channel.
    """

    order: np.ndarray
    names: list[str]


def load_probe(path: Path) -> ProbeMap:
    """Load the first probe from a probeinterface JSON file.

    :param path: Path to the ``.json`` probe file.
    :returns: The reorder map and per-channel names.
    """
    group = read_probeinterface(str(path))
    probe = group.probes[0]
    order = np.asarray(probe.device_channel_indices, dtype=int)
    regions = probe.contact_annotations.get("brain_region")
    ids = probe.contact_ids
    if regions is not None and ids is not None:
        names = [f"{r} {i}" for r, i in zip(regions, ids)]
    elif ids is not None:
        names = [str(i) for i in ids]
    else:
        names = [f"ch{k:0>2d}" for k in range(order.size)]
    return ProbeMap(order=order, names=names)


def reorder_channels(data: np.ndarray, probe: ProbeMap) -> np.ndarray:
    """Reorder a ``(n_channels, n_samples)`` array into probe-native contact order.

    :param data: Raw acquisition-order signal, channels along axis 0.
    :param probe: The probe reorder map.
    :returns: A view/copy with rows permuted so row ``k`` = raw channel ``order[k]``.
    :raises ValueError: If the probe contact count does not match the channel count.
    """
    if data.shape[0] != probe.order.size:
        raise ValueError(
            f"probe channel count {probe.order.size} != stream channel count {data.shape[0]}"
        )
    return data[probe.order, :]


@dataclass(frozen=True)
class Layout:
    """2D grid placement of probe contacts.

    :param col: Column index per contact.
    :param row: Row index per contact; ``0`` is the top row when rendered.
    :param n_cols: Number of grid columns.
    :param n_rows: Number of grid rows.
    """

    col: np.ndarray
    row: np.ndarray
    n_cols: int
    n_rows: int


def _rank(values: np.ndarray) -> tuple[np.ndarray, int]:
    """Map values onto 0-based ranks of their sorted unique values.

    Ranking (rather than using coordinates directly) lets the same code handle
    integer topo annotations, sparse annotations, and micron positions.

    :param values: One coordinate per contact.
    :returns: The per-contact rank and the number of distinct values.
    """
    unique = np.unique(values)
    return np.searchsorted(unique, values), int(unique.size)


def _check_unique_cells(col: np.ndarray, row: np.ndarray, ids: Sequence[str]) -> None:
    """Raise if two contacts resolve to the same grid cell.

    :param col: Per-contact column index.
    :param row: Per-contact row index.
    :param ids: Per-contact identifiers, used to name the offenders.
    :raises ValueError: If any cell is claimed twice.
    """
    seen: dict[tuple[int, int], str] = {}
    for k, cell in enumerate(zip(col.tolist(), row.tolist())):
        if cell in seen:
            raise ValueError(
                f"contacts {seen[cell]!r} and {ids[k]!r} both map to grid cell "
                f"(col={cell[0]}, row={cell[1]}); check topo_x/topo_y or contact_positions"
            )
        seen[cell] = ids[k]


def probe_layout(path: Path) -> Layout:
    """Derive a 2D contact grid from a probeinterface JSON file.

    Uses the ``topo_x``/``topo_y`` contact annotations when both are present, since
    they express the intended anatomical arrangement; otherwise infers the grid by
    ranking the distinct ``contact_positions`` coordinates.

    Reads the file independently of :func:`load_probe` on purpose: a probe whose
    contacts collide in grid space is still perfectly usable for trace reordering,
    so that failure must not be raised on the timeseries path.

    :param path: Path to the ``.json`` probe file.
    :returns: The per-contact grid placement.
    :raises ValueError: If two contacts resolve to the same grid cell.
    """
    probe = read_probeinterface(str(path)).probes[0]
    annotations = probe.contact_annotations
    topo_x, topo_y = annotations.get("topo_x"), annotations.get("topo_y")
    if topo_x is not None and topo_y is not None:
        col, n_cols = _rank(np.asarray(topo_x))
        row, n_rows = _rank(np.asarray(topo_y))
    else:
        positions = np.asarray(probe.contact_positions, dtype=float)
        col, n_cols = _rank(positions[:, 0])
        row, n_rows = _rank(positions[:, 1])
    ids = probe.contact_ids
    labels = [str(i) for i in ids] if ids is not None else [str(k) for k in range(col.size)]
    _check_unique_cells(col, row, labels)
    return Layout(col=col, row=row, n_cols=n_cols, n_rows=n_rows)
