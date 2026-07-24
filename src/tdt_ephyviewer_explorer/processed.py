"""Discovery, classification, and loading of tss-pipeline processed parquets."""
from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

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
