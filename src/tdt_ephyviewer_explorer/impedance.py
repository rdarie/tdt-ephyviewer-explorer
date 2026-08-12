"""Discovery and parsing of the per-block electrode-impedance CSV sidecars.

The rig writes one CSV per electrode array into the block directory (e.g.
``spinal.csv``, ``EMG.csv``), with one ``R<n> (kOhm)`` column per acquisition
channel plus metadata columns such as ``TIME (S)`` and ``FREQUENCY (Hz)``. This
module is Qt-free so every parser here is unit-testable headless.
"""
from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from tdt_ephyviewer_explorer.builders import Attachment
from tdt_ephyviewer_explorer.probe import Layout, ProbeMap, load_probe, probe_layout

log = logging.getLogger(__name__)


class _BlankMissingFormatter(string.Formatter):
    """``str.Formatter`` that renders unknown/unformattable fields as empty.

    Keeps a live-edited GUI annotation template usable across blocks with and
    without a probe: an absent keyword, a stray positional field (``{}``/``{0}``),
    or a numeric spec applied to an absent (empty) value, yields ``""`` rather
    than raising.
    """

    def get_value(self, key: Any, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        if isinstance(key, str):
            return kwargs.get(key, "")
        try:
            return super().get_value(key, args, kwargs)
        except (IndexError, KeyError):
            return ""

    def format_field(self, value: Any, format_spec: str) -> str:
        try:
            return super().format_field(value, format_spec)
        except (ValueError, TypeError):
            return ""


_CELL_FORMATTER = _BlankMissingFormatter()


def format_cell(template: str, fields: Mapping[str, Any]) -> str:
    """Render one annotation cell from a named-field template.

    :param template: A ``str.format``-style template using named fields, e.g.
        ``"R{channel}\\n{impedance:.0f}"``.
    :param fields: The available field values for this cell.
    :returns: The formatted label; missing fields and failed specs render empty.
    """
    return _CELL_FORMATTER.vformat(template, (), dict(fields))


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


@dataclass(frozen=True)
class ImpedanceGridSource:
    """Ephyviewer-style source for the impedance viewer.

    Deliberately exposes no ``t_start``: impedance is a per-block property, not a
    signal, and ``MainViewer.add_view`` keys off that attribute when deciding
    whether to widen the navigation range.

    :param name: Display name (the CSV stem).
    :param units: Impedance units, e.g. ``"kOhm"``.
    :param frequencies: One entry per grid; ``None`` when the file has no
        frequency column.
    :param grids: ``(n_rows, n_cols)`` arrays, NaN where no contact occupies the
        cell. Row ``0`` renders at the top.
    :param fields: ``(n_rows, n_cols)`` object array of per-cell field dicts for
        annotation templating (``channel``/``units``/``name`` always, plus
        ``contact_id``/``region`` when a probe was supplied); ``None`` for empty
        cells.
    :param metadata: Averaged metadata columns, one dict per grid.
    """

    name: str
    units: str
    frequencies: tuple[float | None, ...]
    grids: tuple[np.ndarray, ...]
    fields: np.ndarray
    metadata: tuple[dict[str, float], ...]


def build_grid_source(
    data: ImpedanceData, probe: ProbeMap | None, layout: Layout | None
) -> ImpedanceGridSource:
    """Place per-channel impedances onto a probe-topology grid.

    Contact ``k`` is wired to acquisition channel ``probe.order[k]``, and the CSV
    numbers its channels from 1, so contact ``k`` takes the column ``R{order[k]+1}``.
    Without a probe the contacts form a 1xN strip in CSV column order.

    :param data: The reduced impedance data.
    :param probe: Loaded probe map, or ``None`` for a strip layout.
    :param layout: Grid placement from :func:`~probe.probe_layout`, or ``None``.
    :returns: The viewer source.
    :raises ValueError: If the probe's contact count differs from the CSV's
        channel count, or a required ``R<n>`` column is absent.
    """
    n_channels = len(data.channel_numbers)
    if probe is None or layout is None:
        col = np.arange(n_channels)
        row = np.zeros(n_channels, dtype=int)
        n_cols, n_rows = n_channels, 1
        labels = [f"R{n}" for n in data.channel_numbers]
        wanted = list(data.channel_numbers)
    else:
        if probe.order.size != n_channels:
            raise ValueError(
                f"probe has {probe.order.size} contacts but {data.name} has "
                f"{n_channels} impedance channels"
            )
        col, row = layout.col, layout.row
        n_cols, n_rows = layout.n_cols, layout.n_rows
        labels = list(probe.names)
        wanted = [int(o) + 1 for o in probe.order]

    index_of = {number: j for j, number in enumerate(data.channel_numbers)}
    missing = sorted({n for n in wanted if n not in index_of})
    if missing:
        raise ValueError(
            f"{data.name} has no column for channel(s) {missing}; present "
            f"channels are {sorted(index_of)}"
        )

    cell_fields = np.full((n_rows, n_cols), None, dtype=object)
    for k in range(len(wanted)):
        cell = {"channel": int(wanted[k]), "units": data.units, "name": labels[k]}
        if probe is not None:
            if probe.contact_ids is not None:
                cell["contact_id"] = probe.contact_ids[k]
            if probe.regions is not None:
                cell["region"] = probe.regions[k]
        cell_fields[row[k], col[k]] = cell
    grids = []
    for group in data.groups:
        grid = np.full((n_rows, n_cols), np.nan)
        for k, number in enumerate(wanted):
            grid[row[k], col[k]] = group.values[index_of[number]]
        grids.append(grid)

    return ImpedanceGridSource(
        name=data.name,
        units=data.units,
        frequencies=tuple(g.frequency for g in data.groups),
        grids=tuple(grids),
        fields=cell_fields,
        metadata=tuple(g.metadata for g in data.groups),
    )


def build_impedance_source(
    info: ImpedanceInfo, attachment: Attachment, cfg: Any
) -> ImpedanceGridSource:
    """Read an impedance CSV and build the source for one attachment.

    :param info: The classified impedance CSV.
    :param attachment: The viewer attachment; ``probe_path`` supplies the layout.
    :param cfg: Composed config (uses ``cfg.impedance``).
    :returns: The viewer source.
    """
    data = read_impedance(info.path, cfg)
    if attachment.probe_path is None:
        return build_grid_source(data, None, None)
    return build_grid_source(
        data, load_probe(attachment.probe_path), probe_layout(attachment.probe_path)
    )
