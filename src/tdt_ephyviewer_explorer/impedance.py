"""Discovery and parsing of the per-block electrode-impedance CSV sidecars.

The rig writes one CSV per electrode array into the block directory (e.g.
``spinal.csv``, ``EMG.csv``), with one ``R<n> (kOhm)`` column per acquisition
channel plus metadata columns such as ``TIME (S)`` and ``FREQUENCY (Hz)``. This
module is Qt-free so every parser here is unit-testable headless.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImpedanceInfo:
    """Classified description of one impedance CSV.

    :param path: CSV path.
    :param name: Display / dock-prefix name (the file stem).
    :param frequencies: Distinct stimulation frequencies, sorted; empty when the
        file has no frequency column.
    :param channel_numbers: The ``n`` of each ``R<n>`` column, in file order.
    :param units: Impedance units parsed from the header, e.g. ``"kOhm"``.
    """

    path: Path
    name: str
    frequencies: tuple[float, ...]
    channel_numbers: tuple[int, ...]
    units: str


@dataclass(frozen=True)
class FrequencyGroup:
    """Impedances averaged over every row measured at one frequency.

    :param frequency: The frequency in Hz, or ``None`` when the file has no
        frequency column and all rows form a single group.
    :param values: One impedance per channel, in CSV column order.
    :param metadata: Averaged non-channel numeric columns (e.g. ``TARGET (uA)``,
        ``REF (kOhm)``), for display alongside the grid.
    """

    frequency: float | None
    values: np.ndarray
    metadata: dict[str, float]


@dataclass(frozen=True)
class ImpedanceData:
    """One impedance CSV, fully read and reduced.

    :param name: Display name (the file stem).
    :param channel_numbers: The ``n`` of each ``R<n>`` column, in file order.
    :param units: Impedance units, e.g. ``"kOhm"``.
    :param groups: One entry per distinct frequency, in ascending order.
    """

    name: str
    channel_numbers: tuple[int, ...]
    units: str
    groups: tuple[FrequencyGroup, ...]


def _split_columns(
    columns: Sequence[Any], cfg: Any
) -> tuple[list[str], list[int], str | None]:
    """Separate the ``R<n>`` channel columns from the metadata columns.

    :param columns: The CSV header, in file order.
    :param cfg: Composed config (uses ``cfg.impedance.channel_regex``).
    :returns: ``(channel_column_names, channel_numbers, units)``; ``units`` is
        ``None`` when no column matched.
    """
    pattern = re.compile(str(cfg.impedance.channel_regex))
    names: list[str] = []
    numbers: list[int] = []
    units: str | None = None
    for column in columns:
        match = pattern.match(str(column).strip())
        if match is not None:
            names.append(column)
            numbers.append(int(match.group(1)))
            units = units if units is not None else match.group(2)
    return names, numbers, units


def classify_impedance_csv(path: Path, cfg: Any) -> ImpedanceInfo | None:
    """Classify a CSV as an impedance sidecar by its header shape.

    Populating :attr:`ImpedanceInfo.frequencies` needs the frequency column, so
    this reads the whole file rather than just the header. These sidecars are a
    handful of rows, so the cost is negligible and the eager block-select path
    stays fast — unlike the ``.tsq`` and ``eS1p`` reads, which stay lazy.

    :param path: CSV path.
    :param cfg: Composed config (uses ``cfg.impedance``).
    :returns: The classified info, or ``None`` when the file is not an impedance
        CSV or carries no data rows.
    """
    try:
        frame = pd.read_csv(path)
    except (ValueError, UnicodeDecodeError, pd.errors.ParserError):
        log.info("could not parse %s as CSV; skipping", path.name)
        return None
    _, numbers, units = _split_columns(frame.columns, cfg)
    if len(numbers) < int(cfg.impedance.min_channels):
        return None
    if frame.empty:
        log.info("impedance CSV %s has no data rows; skipping", path.name)
        return None
    frequency_column = str(cfg.impedance.frequency_column)
    if frequency_column in frame.columns:
        frequencies = tuple(
            sorted(float(f) for f in frame[frequency_column].dropna().unique())
        )
    else:
        frequencies = ()
    return ImpedanceInfo(
        path=path,
        name=path.stem,
        frequencies=frequencies,
        channel_numbers=tuple(numbers),
        units=units or "",
    )


def scan_impedance(block_path: Path, cfg: Any) -> list[ImpedanceInfo]:
    """Find the impedance CSVs in a block directory.

    :param block_path: Block directory.
    :param cfg: Composed config (uses ``cfg.impedance.auto_scan``/``globs``).
    :returns: Classified infos, sorted by name; empty when auto-scan is off.
    """
    if not cfg.impedance.auto_scan:
        return []
    seen: set[Path] = set()
    infos: list[ImpedanceInfo] = []
    for pattern in cfg.impedance.globs:
        for path in sorted(block_path.glob(str(pattern))):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            info = classify_impedance_csv(path, cfg)
            if info is not None:
                infos.append(info)
    return sorted(infos, key=lambda i: i.name)


def read_impedance(path: Path, cfg: Any) -> ImpedanceData:
    """Read an impedance CSV and average its rows within each frequency.

    :param path: CSV path.
    :param cfg: Composed config (uses ``cfg.impedance``).
    :returns: The reduced impedance data.
    :raises ValueError: If the file has no ``R<n>`` channel columns.
    """
    frame = pd.read_csv(path)
    channel_columns, numbers, units = _split_columns(frame.columns, cfg)
    if not channel_columns:
        raise ValueError(f"{path.name} has no impedance channel columns")
    frequency_column = str(cfg.impedance.frequency_column)
    metadata_columns = [
        c
        for c in frame.columns
        if c not in channel_columns
        and c != frequency_column
        and pd.api.types.is_numeric_dtype(frame[c])
    ]
    if frequency_column in frame.columns:
        chunks: list[tuple[float | None, pd.DataFrame]] = [
            (float(frequency), chunk)
            for frequency, chunk in frame.groupby(frequency_column, sort=True)
        ]
    else:
        chunks = [(None, frame)]
    numeric = frame[channel_columns].apply(pd.to_numeric, errors="coerce")
    groups = tuple(
        FrequencyGroup(
            frequency=frequency,
            # NaN-skipping mean: an unmeasured cell drops out of the average, and a
            # channel with no numeric reading at all stays NaN (an empty grid cell).
            values=numeric.loc[chunk.index].mean(axis=0).to_numpy(dtype=float),
            metadata={c: float(chunk[c].mean()) for c in metadata_columns},
        )
        for frequency, chunk in chunks
    )
    return ImpedanceData(
        name=path.stem,
        channel_numbers=tuple(numbers),
        units=units or "",
        groups=groups,
    )
