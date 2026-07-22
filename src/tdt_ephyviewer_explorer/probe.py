"""Probe loading (probeinterface) and probe-native channel reordering."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
