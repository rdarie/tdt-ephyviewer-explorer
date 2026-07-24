"""Discovery, classification, and loading of tss-pipeline processed parquets."""
from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from omegaconf import OmegaConf

from tdt_ephyviewer_explorer.builders import (
    Attachment,
    build_analog_source,
    build_event_source_from_frame,
)
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter
from tdt_ephyviewer_explorer.probe import load_probe
from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

CONTRACT_KEY = b"tdt_explore"


def read_contract(path: Path) -> dict | None:
    """Read the embedded ``tdt_explore`` JSON contract from a parquet's schema metadata.

    :param path: Path to the parquet file.
    :returns: The parsed contract dict, or ``None`` if the key is absent or the
        value is not valid JSON.
    """
    metadata = pq.read_schema(str(path)).metadata or {}
    raw = metadata.get(CONTRACT_KEY)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class ProcessedInfo:
    """Classified description of one processed parquet (header-only).

    :param path: Parquet path.
    :param kind: ``"timeseries"`` or ``"event"``.
    :param role: Semantic role (equals ``kind``; keys :data:`~stores.VALID_VIEWERS`).
    :param name: Display/dock name (default = file stem).
    :param sampling_rate: Hz for timeseries / samples-based events; else ``None``.
    :param t_start: Block-relative seconds of sample 0 (timeseries); ``0.0`` otherwise.
    :param channel_names: Timeseries channel labels, or ``None`` (use df columns).
    :param time_column: Event onset column, or ``None``.
    :param time_units: ``"seconds"`` or ``"samples"`` (events).
    :param label_column: Event label column, or ``None``.
    :param schema: Named column schema for a formatter, or ``None``.
    :param units: Display units (e.g. ``"uV"``), or ``None``.
    :param viewers: Allowed viewer types for this role.
    """

    path: Path
    kind: str
    role: str
    name: str
    sampling_rate: float | None
    t_start: float
    channel_names: list[str] | None
    time_column: str | None
    time_units: str
    label_column: str | None
    schema: str | None
    units: str | None
    viewers: tuple[str, ...]


def _schema_summary(schema: pa.Schema) -> tuple[list[str], bool, bool]:
    """Return ``(data_columns, is_range_index, is_multiindex)`` without loading data.

    Reads embedded pandas metadata from an already-parsed schema only.

    :param schema: Already-parsed parquet schema.
    """
    meta = schema.metadata or {}
    pandas_meta = json.loads(meta[b"pandas"]) if b"pandas" in meta else {}
    index_cols = pandas_meta.get("index_columns", [])
    is_range = (
        len(index_cols) == 1
        and isinstance(index_cols[0], dict)
        and index_cols[0].get("kind") == "range"
    )
    is_multiindex = len(index_cols) > 1 or len(pandas_meta.get("column_indexes", [])) > 1
    index_names = {c for c in index_cols if isinstance(c, str)}
    columns = [n for n in schema.names if n not in index_names]
    return columns, is_range, is_multiindex


def _all_numeric(schema: pa.Schema, columns: list[str]) -> bool:
    """True if every named column has a numeric (int/float/bool) parquet type.

    :param schema: Already-parsed parquet schema.
    :param columns: Column names to check.
    """
    for name in columns:
        t = schema.field(name).type
        if not (pa.types.is_integer(t) or pa.types.is_floating(t) or pa.types.is_boolean(t)):
            return False
    return True


def _attrs_sampling_rate(schema: pa.Schema) -> float | None:
    """Read ``sampling_rate`` from a ``PANDAS_ATTRS`` metadata blob, if present.

    :param schema: Already-parsed parquet schema.
    """
    meta = schema.metadata or {}
    raw = meta.get(b"PANDAS_ATTRS")
    if raw is None:
        return None
    try:
        return json.loads(raw).get("sampling_rate")
    except (ValueError, TypeError):
        return None


def _info_from_contract(path: Path, blob: dict[str, Any]) -> ProcessedInfo:
    """Build a :class:`ProcessedInfo` from a parsed contract blob."""
    kind = blob["kind"]
    channels = blob.get("channel_names")
    return ProcessedInfo(
        path=path,
        kind=kind,
        role=kind,
        name=path.stem,
        sampling_rate=blob.get("sampling_rate"),
        t_start=float(blob.get("t_start", 0.0)),
        channel_names=list(channels) if channels else None,
        time_column=blob.get("time_column"),
        time_units=blob.get("time_units", "seconds"),
        label_column=blob.get("label_column"),
        schema=blob.get("schema"),
        units=blob.get("units"),
        viewers=VALID_VIEWERS[kind],
    )


def classify(path: Path, cfg: Any) -> ProcessedInfo | None:
    """Classify a parquet as timeseries/event, contract-first with heuristic fallback.

    :param path: Parquet path.
    :param cfg: Composed config (uses ``cfg.processed``).
    :returns: A :class:`ProcessedInfo`, or ``None`` if the file is out of scope
        (feature/MultiIndex tables, or an unrecognizable structure).
    """
    blob = read_contract(path)
    if blob is not None:
        return _info_from_contract(path, blob)

    schema = pq.read_schema(str(path))
    columns, is_range, is_multiindex = _schema_summary(schema)
    if is_multiindex:
        return None
    candidates = list(cfg.processed.time_column_candidates)
    time_col = next((c for c in candidates if c in columns), None)
    if time_col is not None:
        label = str(cfg.processed.default_label_column)
        return ProcessedInfo(
            path, "event", "event", path.stem, None, 0.0, None,
            time_col, "seconds", label if label in columns else None,
            None, None, VALID_VIEWERS["event"],
        )
    if is_range and columns and _all_numeric(schema, columns):
        fs = _attrs_sampling_rate(schema)
        if fs is not None:
            return ProcessedInfo(
                path, "timeseries", "timeseries", path.stem, float(fs), 0.0, None,
                None, "seconds", None, None, None, VALID_VIEWERS["timeseries"],
            )
    return None


def scan_preprocessed(tank_dir: Path, block: str, cfg: Any) -> list[ProcessedInfo]:
    """Scan ``<tank>/<preprocessed_subpath>/<block>/`` and classify its parquets.

    Auto-discovery is contract-only: files without a ``tdt_explore`` blob are
    skipped (the producer tags everything intended for the viewer). Names matching
    ``cfg.processed.ignore_globs`` are also skipped.

    :param tank_dir: The tank directory.
    :param block: Block directory name (dataset dirs are 1:1 with block names).
    :param cfg: Composed config.
    :returns: Classified infos, sorted by name.
    """
    pdir = tank_dir / str(cfg.processed.preprocessed_subpath) / block
    if not pdir.is_dir():
        return []
    ignore = list(cfg.processed.ignore_globs)
    infos: list[ProcessedInfo] = []
    for path in sorted(pdir.glob("*.parquet")):
        if any(fnmatch(path.name, pat) for pat in ignore):
            continue
        if read_contract(path) is None:  # blob-only auto-scan
            continue
        info = classify(path, cfg)
        if info is not None:
            infos.append(info)
    return infos


def to_stored_path(abs_path: Path, tank_dir: Path) -> str:
    """Serialize a parquet path: tank-relative (POSIX) if under ``tank_dir``, else absolute."""
    abs_path = abs_path.resolve()
    tank_dir = tank_dir.resolve()
    try:
        return abs_path.relative_to(tank_dir).as_posix()
    except ValueError:
        return str(abs_path)


def from_stored_path(stored: str, tank_dir: Path) -> Path:
    """Inverse of :func:`to_stored_path`: resolve a stored path against ``tank_dir``."""
    p = Path(stored)
    return p if p.is_absolute() else (tank_dir.resolve() / p)


class _TimeseriesAdapter:
    """Duck-typed view of a timeseries DataFrame for :func:`~builders.build_analog_source`."""

    def __init__(self, df: pd.DataFrame, info: ProcessedInfo) -> None:
        self.data = df.to_numpy(dtype=float).T  # (n_channels, n_samples), bool->float
        self.fs = info.sampling_rate
        self.start_time = info.t_start
        self.channel_names = info.channel_names or [str(c) for c in df.columns]


def build_processed_source(info: ProcessedInfo, attachment: Attachment, cfg: Any) -> object:
    """Load a processed parquet and build the ephyviewer source for one attachment.

    :param info: The classified processed-parquet info.
    :param attachment: The viewer attachment (viewer type, delay, probe, params).
    :param cfg: Composed config (uses ``cfg.schemas`` for event label fallback).
    :returns: An ephyviewer source.
    :raises ValueError: If the attachment's viewer type is invalid for the role, or
        a timeseries lacks a sampling rate.
    """
    if attachment.viewer_type not in info.viewers:
        raise ValueError(
            f"viewer {attachment.viewer_type!r} not valid for kind {info.kind!r}"
        )
    df = pd.read_parquet(info.path)
    if info.kind == "timeseries":
        if not info.sampling_rate:
            raise ValueError(f"timeseries {info.name!r} has no sampling_rate")
        store = _TimeseriesAdapter(df, info)
        probe = load_probe(attachment.probe_path) if attachment.probe_path else None
        return build_analog_source(store, attachment, probe)
    # event
    formatter = None
    if not info.label_column and info.schema:
        schemas = OmegaConf.to_container(cfg.schemas, resolve=True)
        columns = list(schemas.get(info.schema, []))
        if columns:
            formatter = GenericFormatter(columns)
    return build_event_source_from_frame(
        df,
        time_column=info.time_column,
        time_units=info.time_units,
        sampling_rate=info.sampling_rate,
        label_column=info.label_column,
        formatter=formatter,
        viewer_type=attachment.viewer_type,
        delay_ms=attachment.delay_ms,
    )
