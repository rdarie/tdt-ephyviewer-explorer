"""Tests for processed-parquet discovery, classification, and loading (Qt-free)."""
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tdt_ephyviewer_explorer.processed import CONTRACT_KEY, read_contract


def _write_parquet(path: Path, df: pd.DataFrame, *, blob: dict | None = None,
                   attrs: dict | None = None) -> None:
    """Write ``df`` to ``path``, embedding ``blob`` under the contract key and
    ``attrs`` under ``PANDAS_ATTRS`` (mirrors how tss-pipeline writes metadata)."""
    table = pa.Table.from_pandas(df)
    md = dict(table.schema.metadata or {})
    if blob is not None:
        md[CONTRACT_KEY] = json.dumps(blob).encode("utf-8")
    if attrs is not None:
        md[b"PANDAS_ATTRS"] = json.dumps(attrs).encode("utf-8")
    pq.write_table(table.replace_schema_metadata(md), path)


def test_read_contract_returns_blob(tmp_path: Path) -> None:
    p = tmp_path / "ts.parquet"
    blob = {"contract_version": 1, "kind": "timeseries", "sampling_rate": 24414.0625,
            "t_start": 0.0, "channel_names": ["0", "1"]}
    _write_parquet(p, pd.DataFrame({"0": [1.0, 2.0], "1": [3.0, 4.0]}), blob=blob)
    assert read_contract(p) == blob


def test_read_contract_none_when_absent(tmp_path: Path) -> None:
    p = tmp_path / "plain.parquet"
    _write_parquet(p, pd.DataFrame({"0": [1.0]}))
    assert read_contract(p) is None


def test_read_contract_none_when_malformed(tmp_path: Path) -> None:
    p = tmp_path / "bad.parquet"
    table = pa.Table.from_pandas(pd.DataFrame({"0": [1.0]}))
    md = dict(table.schema.metadata or {})
    md[CONTRACT_KEY] = b"{not valid json"
    pq.write_table(table.replace_schema_metadata(md), p)
    assert read_contract(p) is None
