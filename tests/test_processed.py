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


from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.processed import ProcessedInfo, classify


def test_classify_blob_timeseries(tmp_path: Path) -> None:
    p = tmp_path / "raw_data_mep.parquet"
    blob = {"contract_version": 1, "kind": "timeseries", "sampling_rate": 24414.0625,
            "t_start": 0.0, "channel_names": ["0", "1"], "units": "uV"}
    _write_parquet(p, pd.DataFrame({"0": [1.0, 2.0], "1": [3.0, 4.0]}), blob=blob)
    info = classify(p, load_config())
    assert isinstance(info, ProcessedInfo)
    assert info.kind == "timeseries" and info.role == "timeseries"
    assert info.name == "raw_data_mep"
    assert info.sampling_rate == 24414.0625 and info.t_start == 0.0
    assert info.channel_names == ["0", "1"] and info.units == "uV"
    assert "trace" in info.viewers


def test_classify_blob_event(tmp_path: Path) -> None:
    p = tmp_path / "stim_info_per_pulse.parquet"
    blob = {"contract_version": 1, "kind": "event", "time_column": "timestamp_sample",
            "time_units": "samples", "sampling_rate": 24414.0625,
            "label_column": "stim_site", "schema": "iz_param_names"}
    _write_parquet(p, pd.DataFrame({"timestamp_sample": [100, 200], "stim_site": ["E1", "E2"]}), blob=blob)
    info = classify(p, load_config())
    assert info.kind == "event" and info.role == "event"
    assert info.time_column == "timestamp_sample" and info.time_units == "samples"
    assert info.label_column == "stim_site" and info.schema == "iz_param_names"
    assert "eventlist" in info.viewers


def test_classify_heuristic_event_by_timestamp_column(tmp_path: Path) -> None:
    p = tmp_path / "untagged_events.parquet"
    _write_parquet(p, pd.DataFrame({"timestamp": [0.1, 0.2], "stim_site": ["a", "b"]}))
    info = classify(p, load_config())
    assert info.kind == "event" and info.time_column == "timestamp"
    assert info.time_units == "seconds" and info.label_column == "stim_site"


def test_classify_heuristic_timeseries_with_attrs_rate(tmp_path: Path) -> None:
    p = tmp_path / "mona_data.parquet"
    _write_parquet(p, pd.DataFrame({"0": [1.0, 2.0], "1": [3.0, 4.0]}),
                   attrs={"sampling_rate": 12207.03125})
    info = classify(p, load_config())
    assert info.kind == "timeseries" and info.sampling_rate == 12207.03125


def test_classify_skips_multiindex_feature_table(tmp_path: Path) -> None:
    p = tmp_path / "mep_full_rms.parquet"
    df = pd.DataFrame({"v": [1.0, 2.0]},
                      index=pd.MultiIndex.from_tuples([(1, "a"), (2, "b")], names=["ts", "site"]))
    _write_parquet(p, df)
    assert classify(p, load_config()) is None


from tdt_ephyviewer_explorer.processed import (
    from_stored_path,
    scan_preprocessed,
    to_stored_path,
)


def test_scan_preprocessed_returns_only_tagged(tmp_path: Path) -> None:
    block = "rRew03-1"
    pdir = tmp_path / "torpedo" / "preprocessed" / block
    pdir.mkdir(parents=True)
    _write_parquet(pdir / "raw_data.parquet",
                   pd.DataFrame({"0": [1.0]}),
                   blob={"contract_version": 1, "kind": "timeseries",
                         "sampling_rate": 24414.0625, "t_start": 0.0, "channel_names": ["0"]})
    _write_parquet(pdir / "untagged.parquet", pd.DataFrame({"0": [1.0]}))  # no blob -> skipped
    infos = scan_preprocessed(tmp_path, block, load_config())
    assert [i.name for i in infos] == ["raw_data"]


def test_scan_preprocessed_missing_dir_is_empty(tmp_path: Path) -> None:
    assert scan_preprocessed(tmp_path, "nope", load_config()) == []


def test_stored_path_relative_under_tank(tmp_path: Path) -> None:
    p = tmp_path / "torpedo" / "preprocessed" / "b" / "raw_data.parquet"
    stored = to_stored_path(p, tmp_path)
    assert stored == "torpedo/preprocessed/b/raw_data.parquet"
    assert from_stored_path(stored, tmp_path) == p


def test_stored_path_absolute_when_outside_tank(tmp_path: Path) -> None:
    outside = tmp_path.parent / "elsewhere" / "x.parquet"
    stored = to_stored_path(outside, tmp_path)
    assert Path(stored).is_absolute()
    assert from_stored_path(stored, tmp_path) == outside


from tdt_ephyviewer_explorer.builders import Attachment
from tdt_ephyviewer_explorer.processed import build_processed_source


def test_build_processed_source_timeseries(tmp_path: Path) -> None:
    p = tmp_path / "raw_data_mep.parquet"
    blob = {"contract_version": 1, "kind": "timeseries", "sampling_rate": 1000.0,
            "t_start": 0.5, "channel_names": ["a", "b"], "units": "uV"}
    _write_parquet(p, pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]}), blob=blob)
    info = classify(p, load_config())
    src = build_processed_source(info, Attachment("trace", delay_ms=10.0), load_config())
    assert src.signals.shape == (3, 2)          # samples x channels
    assert src.t_start == 0.51                    # 0.5 + 10 ms
    assert src.channel_names == ["a", "b"]


def test_build_processed_source_boolean_timeseries(tmp_path: Path) -> None:
    p = tmp_path / "stim_synch.parquet"
    blob = {"contract_version": 1, "kind": "timeseries", "sampling_rate": 1000.0,
            "t_start": 0.0, "channel_names": ["pulse", "blanking"]}
    _write_parquet(p, pd.DataFrame({"pulse": [True, False], "blanking": [False, True]}), blob=blob)
    info = classify(p, load_config())
    src = build_processed_source(info, Attachment("trace"), load_config())
    assert src.signals.shape == (2, 2)
    assert src.signals.dtype.kind == "f"          # bool cast to float


def test_build_processed_source_event(tmp_path: Path) -> None:
    p = tmp_path / "stim_info_per_pulse.parquet"
    blob = {"contract_version": 1, "kind": "event", "time_column": "timestamp_sample",
            "time_units": "samples", "sampling_rate": 1000.0, "label_column": "stim_site"}
    _write_parquet(p, pd.DataFrame({"timestamp_sample": [1000, 2000], "stim_site": ["E1", "E2"]}), blob=blob)
    info = classify(p, load_config())
    src = build_processed_source(info, Attachment("eventlist"), load_config())
    ev = src.all[0]
    assert list(ev["time"]) == [1.0, 2.0]
    assert list(ev["label"]) == ["E1", "E2"]


def test_build_processed_source_rejects_invalid_viewer(tmp_path: Path) -> None:
    p = tmp_path / "raw_data.parquet"
    blob = {"contract_version": 1, "kind": "timeseries", "sampling_rate": 1000.0,
            "t_start": 0.0, "channel_names": ["a"]}
    _write_parquet(p, pd.DataFrame({"a": [1.0]}), blob=blob)
    info = classify(p, load_config())
    import pytest
    with pytest.raises(ValueError, match="not valid"):
        build_processed_source(info, Attachment("eventlist"), load_config())
