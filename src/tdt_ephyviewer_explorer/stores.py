"""TDT store model, header parsing, and lazy loading."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import tdt


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
    except (KeyError, TypeError, AttributeError):
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


VALID_VIEWERS: dict[str, tuple[str, ...]] = {
    "timeseries": ("trace", "timefreq", "spectrogram"),
    "stim": ("eventlist", "spiketrain"),
    "event": ("eventlist", "spiketrain"),
    "epoch": ("epoch", "spiketrain"),
    "snip": ("spiketrain",),
    "impedance": ("impedance",),
}

TDT_TYPE_TO_ROLE: dict[str, str] = {
    "streams": "timeseries",
    "scalars": "event",
    "epocs": "epoch",
    "snips": "snip",
}


@dataclass(frozen=True)
class RoleRule:
    """A name-pattern rule mapping a store to a semantic role.

    :param pattern: fnmatch pattern tested against the store name.
    :param role: Semantic role (key of :data:`VALID_VIEWERS`).
    :param schema: Named column schema, or ``None``.
    :param viewers: Allowed viewer types; empty means use the role default.
    :param formatter: Hydra ``_target_`` spec for a stim formatter, or ``None``.
    """

    pattern: str
    role: str
    schema: str | None = None
    viewers: tuple[str, ...] = ()
    formatter: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResolvedStore:
    """A store with its resolved role and viewer options."""

    info: StoreInfo
    role: str
    schema: str | None
    viewers: tuple[str, ...]
    formatter: dict[str, Any] | None


def rules_from_config(cfg: Any) -> list[RoleRule]:
    """Convert the ``roles`` list of a composed config into :class:`RoleRule` objects."""
    rules: list[RoleRule] = []
    for r in cfg.roles:
        rules.append(
            RoleRule(
                pattern=str(r.pattern),
                role=str(r.role),
                schema=str(r.schema) if r.get("schema") is not None else None,
                viewers=tuple(r.get("viewers") or ()),
                formatter=dict(r.formatter) if r.get("formatter") is not None else None,
            )
        )
    return rules


def resolve_role(info: StoreInfo, rules: Sequence[RoleRule]) -> ResolvedStore:
    """Resolve a store's semantic role via name patterns, falling back to its tdt type.

    :param info: The store description.
    :param rules: Ordered role rules; first match wins.
    :returns: The resolved store with role, schema, viewers, and formatter.
    :raises KeyError: If the tdt type is unknown and no rule matches.
    """
    for rule in rules:
        if fnmatchcase(info.name, rule.pattern):
            viewers = rule.viewers or VALID_VIEWERS[rule.role]
            return ResolvedStore(info, rule.role, rule.schema, viewers, rule.formatter)
    role = TDT_TYPE_TO_ROLE[info.tdt_type]
    return ResolvedStore(info, role, None, VALID_VIEWERS[role], None)


def _store_from_block(blk: object, name: str) -> Any:
    """Return the named store from a loaded tdt block across its store groups.

    :param blk: A loaded tdt block (StructType) supporting ``[]`` and ``keys()``.
    :param name: Store code to extract.
    :raises KeyError: If the store is not present in any group.
    """
    for group in ("streams", "scalars", "epocs", "snips"):
        if group in blk.keys():  # type: ignore[attr-defined]
            section = blk[group]  # type: ignore[index]
            if name in section.keys():
                return section[name]
    raise KeyError(f"store {name!r} not found in loaded block")


def load_store(block_path: Path, name: str, headers: Any | None = None) -> Any:
    """Load a single store's full data from a block.

    :param block_path: Path to the block directory.
    :param name: Store code to load.
    :param headers: Pre-parsed headers (see :func:`~tank.read_headers`) to reuse,
        avoiding a re-parse of the block's ``.tsq`` index; ``None`` parses it here.
    :returns: The raw tdt store object (from ``streams``/``scalars``/``epocs``/``snips``).
    :raises KeyError: If the store is not present in the block.
    """
    kwargs: dict[str, Any] = {"store": [name]}
    if headers is not None:
        kwargs["headers"] = headers
    blk = tdt.read_block(str(block_path), **kwargs)
    try:
        return _store_from_block(blk, name)
    except KeyError:
        raise KeyError(f"store {name!r} not found in block {block_path}") from None
