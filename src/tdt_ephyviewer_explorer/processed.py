"""Discovery, classification, and loading of tss-pipeline processed parquets."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

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


def _schema_summary(path: Path) -> tuple[list[str], bool, bool]:
    """Return ``(data_columns, is_range_index, is_multiindex)`` without loading data.

    Parses the parquet schema + embedded pandas metadata only.
    """
    schema = pq.read_schema(str(path))
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


def _all_numeric(path: Path, columns: list[str]) -> bool:
    """True if every named column has a numeric (int/float/bool) parquet type."""
    schema = pq.read_schema(str(path))
    for name in columns:
        t = schema.field(name).type
        if not (pa.types.is_integer(t) or pa.types.is_floating(t) or pa.types.is_boolean(t)):
            return False
    return True


def _attrs_sampling_rate(path: Path) -> float | None:
    """Read ``sampling_rate`` from a ``PANDAS_ATTRS`` metadata blob, if present."""
    meta = pq.read_schema(str(path)).metadata or {}
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

    columns, is_range, is_multiindex = _schema_summary(path)
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
    if is_range and columns and _all_numeric(path, columns):
        fs = _attrs_sampling_rate(path)
        if fs is not None:
            return ProcessedInfo(
                path, "timeseries", "timeseries", path.stem, float(fs), 0.0, None,
                None, "seconds", None, None, None, VALID_VIEWERS["timeseries"],
            )
    return None
