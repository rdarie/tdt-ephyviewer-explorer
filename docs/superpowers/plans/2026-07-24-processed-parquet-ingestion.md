# Processed-Parquet Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let tdt-explore ingest tss-pipeline processed parquets (timeseries + event kinds) via auto-discovery and a manual "Add processed…" button, alongside raw TDT stores.

**Architecture:** A new Qt-free `processed.py` reads a `b"tdt_explore"` JSON contract embedded in each parquet's schema metadata (heuristic fallback for untagged files), classifies each file, and loads it through the existing ephyviewer source builders (reused via a thin duck-typed adapter for timeseries; a new frame-based builder for events). `Session` gains a parallel `processed` list so existing TDT sessions keep loading unchanged; `plan_views` and the Control Window realize both source types.

**Tech Stack:** Python 3.12+, pandas + pyarrow (parquet), ephyviewer (`InMemoryAnalogSignalSource`/`InMemoryEventSource`), Hydra (config), pyqtgraph ParameterTree + PySide6 (GUI), pytest.

## Global Constraints

- Python **3.12+**; always run via the venv (`uv run …`); never call `python`/`pytest`/`pip` outside it.
- Package manager: **uv**. Add deps to `pyproject.toml`, then `uv sync`.
- **No hardcoded paths, no magic numbers** — all patterns/rates live in Hydra config under `processed:`.
- **Strict typing** on every new function; **reST docstrings** (`:param:`/`:returns:`/`:raises:`).
- Config groups use `# @package _global_` and are composed via `config/config.yaml` `defaults`.
- Config is loaded read-only via `config_schema.load_config`.
- Contract is **authoritative**: key `b"tdt_explore"`, `contract_version` 1, kinds `"timeseries"|"event"`. Timeseries payload always carries `sampling_rate`, `t_start`, `channel_names`. Event payload: `time_column="timestamp_sample"`, `time_units="samples"`, `sampling_rate`, `label_column="stim_site"`, `schema="iz_param_names"`.
- Event time → seconds: `seconds = df[time_column] / sampling_rate` in **float64** (when `time_units=="samples"`); `delay_ms` added after.
- Each `src/` module has a mirror `tests/test_<module>.py`. Suite is Qt-free/headless; Qt-touching tests use an `ephyviewer.mkQApp()` module fixture.
- TDD: failing test first; commit after each green task. **Never `git add` gitignored files.**
- Raw block dirs are never written to; sessions persist under `<tank>/tdt_explore/sessions/`.

---

## File Structure

- **Create** `src/tdt_ephyviewer_explorer/processed.py` — contract read, classification, discovery, load, adapters, path helpers (Qt-free).
- **Create** `src/tdt_ephyviewer_explorer/config/processed/default.yaml` — the `processed:` config group.
- **Modify** `src/tdt_ephyviewer_explorer/config/config.yaml` — add `processed` to `defaults`.
- **Modify** `src/tdt_ephyviewer_explorer/builders.py` — `build_analog_source` honors source `channel_names`; new `build_event_source_from_frame`.
- **Modify** `src/tdt_ephyviewer_explorer/session.py` — `ProcessedSource` dataclass + `Session.processed`; load/save round-trip.
- **Modify** `src/tdt_ephyviewer_explorer/launcher.py` — `plan_views` realizes `session.processed`.
- **Modify** `src/tdt_ephyviewer_explorer/control_window.py` — processed tree groups, auto-scan on block select, `spec_to_session`/`_apply_session` for processed, "Add processed…" button.
- **Modify** `pyproject.toml` — add `pyarrow`.
- **Create** `tests/test_processed.py`; extend `tests/test_builders.py`, `tests/test_session.py`, `tests/test_launcher.py`, `tests/test_control_window.py`, `tests/test_config.py`.

---

## Task 1: Add pyarrow + read the embedded contract

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Create: `src/tdt_ephyviewer_explorer/processed.py`
- Test: `tests/test_processed.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `read_contract(path: Path) -> dict | None`; module constant `CONTRACT_KEY = b"tdt_explore"`; test helper `_write_parquet(path, df, *, blob=None, attrs=None)`.

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml`, add `"pyarrow",` to the `dependencies` list (after `"pandas",`). Then:

Run: `uv sync`
Expected: resolves and installs pyarrow into `.venv`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_processed.py`:

```python
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_processed.py -v`
Expected: FAIL — `ModuleNotFoundError` / `cannot import name 'read_contract'`.

- [ ] **Step 4: Implement `read_contract`**

Create `src/tdt_ephyviewer_explorer/processed.py`:

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_processed.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/tdt_ephyviewer_explorer/processed.py tests/test_processed.py
git commit -m "feat(processed): add pyarrow dep and read_contract"
```

---

## Task 2: Add the `processed` config group

**Files:**
- Create: `src/tdt_ephyviewer_explorer/config/processed/default.yaml`
- Modify: `src/tdt_ephyviewer_explorer/config/config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `cfg.processed.{preprocessed_subpath, auto_scan, default_sampling_rate, time_column_candidates, default_label_column, ignore_globs}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_load_config_has_processed_group() -> None:
    cfg = load_config()
    assert cfg.processed.preprocessed_subpath == "torpedo/preprocessed"
    assert cfg.processed.auto_scan is True
    assert cfg.processed.default_sampling_rate == 24414.0625
    assert list(cfg.processed.time_column_candidates) == ["timestamp"]
    assert cfg.processed.default_label_column == "stim_site"
    assert list(cfg.processed.ignore_globs) == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_load_config_has_processed_group -v`
Expected: FAIL — `omegaconf.errors.ConfigAttributeError: Key 'processed' not in ...`.

- [ ] **Step 3: Create the config group**

Create `src/tdt_ephyviewer_explorer/config/processed/default.yaml`:

```yaml
# @package _global_
processed:
  preprocessed_subpath: torpedo/preprocessed  # <tank>/<subpath>/<block>/*.parquet
  auto_scan: true                              # scan the preprocessed dir on block select
  default_sampling_rate: 24414.0625            # fallback for blob-less manual-add timeseries
  time_column_candidates: ["timestamp"]        # heuristic event detection (untagged files)
  default_label_column: stim_site              # heuristic event label column
  ignore_globs: []                             # filename globs to skip in auto-scan
```

- [ ] **Step 4: Wire it into the defaults**

Edit `src/tdt_ephyviewer_explorer/config/config.yaml`, add `- processed: default` to the `defaults` list (before `- _self_`):

```yaml
defaults:
  - viewer: default
  - roles: default
  - schema: default
  - startup: default
  - processed: default
  - _self_
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (all config tests).

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/config/processed/default.yaml src/tdt_ephyviewer_explorer/config/config.yaml tests/test_config.py
git commit -m "feat(config): add processed config group"
```

---

## Task 3: `ProcessedInfo` + classification (blob + heuristic + skip)

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/processed.py`
- Test: `tests/test_processed.py`

**Interfaces:**
- Consumes: `read_contract`; `stores.VALID_VIEWERS`; `cfg.processed`.
- Produces:
  - `@dataclass(frozen=True) ProcessedInfo` with fields: `path: Path`, `kind: str`, `role: str`, `name: str`, `sampling_rate: float | None`, `t_start: float`, `channel_names: list[str] | None`, `time_column: str | None`, `time_units: str`, `label_column: str | None`, `schema: str | None`, `units: str | None`, `viewers: tuple[str, ...]`.
  - `classify(path: Path, cfg) -> ProcessedInfo | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processed.py`:

```python
import pandas as pd

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_processed.py -k classify -v`
Expected: FAIL — `cannot import name 'ProcessedInfo'`.

- [ ] **Step 3: Implement `ProcessedInfo`, schema summary, and `classify`**

Add to `src/tdt_ephyviewer_explorer/processed.py` (new imports at top; new code below `read_contract`):

```python
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

from tdt_ephyviewer_explorer.stores import VALID_VIEWERS


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_processed.py -v`
Expected: PASS (all `classify` + `read_contract` tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/processed.py tests/test_processed.py
git commit -m "feat(processed): ProcessedInfo and contract-first classify"
```

---

## Task 4: Directory scan + stored-path helpers

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/processed.py`
- Test: `tests/test_processed.py`

**Interfaces:**
- Consumes: `classify`; `cfg.processed.{preprocessed_subpath, ignore_globs}`.
- Produces:
  - `scan_preprocessed(tank_dir: Path, block: str, cfg) -> list[ProcessedInfo]` (blob-only: files with no contract are skipped).
  - `to_stored_path(abs_path: Path, tank_dir: Path) -> str` — tank-relative (POSIX) if under tank, else absolute.
  - `from_stored_path(stored: str, tank_dir: Path) -> Path` — inverse.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processed.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_processed.py -k "scan or stored" -v`
Expected: FAIL — `cannot import name 'scan_preprocessed'`.

- [ ] **Step 3: Implement scan + path helpers**

Append to `src/tdt_ephyviewer_explorer/processed.py`:

```python
from fnmatch import fnmatch


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_processed.py -v`
Expected: PASS (all processed tests so far).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/processed.py tests/test_processed.py
git commit -m "feat(processed): blob-only directory scan and stored-path helpers"
```

---

## Task 5: Builder extensions — channel names + frame-based event source

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/builders.py:57-79` (`build_analog_source`)
- Modify: `src/tdt_ephyviewer_explorer/builders.py` (add `build_event_source_from_frame`)
- Test: `tests/test_builders.py`

**Interfaces:**
- Consumes: `Attachment`; `InMemoryAnalogSignalSource`, `InMemoryEventSource`; `StimFormatter`.
- Produces:
  - `build_analog_source` now uses `getattr(store, "channel_names", None)` when no probe.
  - `build_event_source_from_frame(df, *, time_column, time_units, sampling_rate, label_column, formatter, viewer_type, delay_ms) -> InMemoryEventSource`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_builders.py`:

```python
import pandas as pd

from tdt_ephyviewer_explorer.builders import build_event_source_from_frame
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter


@dataclass
class FakeNamedStream:
    data: np.ndarray
    fs: float
    start_time: float
    channel_names: list


def test_build_analog_source_uses_store_channel_names() -> None:
    store = FakeNamedStream(data=np.zeros((2, 10)), fs=1000.0, start_time=0.0,
                            channel_names=["pulse", "blanking"])
    src = build_analog_source(store, Attachment("trace"), probe=None)
    assert src.channel_names == ["pulse", "blanking"]


def test_build_event_source_from_frame_samples_to_seconds_and_label() -> None:
    df = pd.DataFrame({"timestamp_sample": [24414, 48828], "stim_site": ["E1", "E2"]})
    src = build_event_source_from_frame(
        df, time_column="timestamp_sample", time_units="samples",
        sampling_rate=24414.0625, label_column="stim_site", formatter=None,
        viewer_type="eventlist", delay_ms=0.0,
    )
    ev = src.all_events[0]
    assert abs(ev["time"][0] - 24414 / 24414.0625) < 1e-9
    assert list(ev["label"]) == ["E1", "E2"]


def test_build_event_source_from_frame_delay_and_formatter_fallback() -> None:
    df = pd.DataFrame({"timestamp": [1.0], "ampA": [100]})
    src = build_event_source_from_frame(
        df, time_column="timestamp", time_units="seconds", sampling_rate=None,
        label_column=None, formatter=GenericFormatter(["ampA"]),
        viewer_type="eventlist", delay_ms=20.0,
    )
    ev = src.all_events[0]
    assert ev["time"][0] == 1.02
    assert ev["label"][0] == "ampA: 100"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builders.py -k "channel_names or from_frame" -v`
Expected: FAIL — `cannot import name 'build_event_source_from_frame'`; channel-names test fails (names are `ch00`/`ch01`).

- [ ] **Step 3: Extend `build_analog_source`**

In `src/tdt_ephyviewer_explorer/builders.py`, change the `else` branch of the probe check in `build_analog_source` (currently `names = [f"ch{k:0>2d}" ...]`):

```python
    if probe is not None:
        data = reorder_channels(data, probe)
        names = probe.names
    else:
        names = getattr(store, "channel_names", None) or [
            f"ch{k:0>2d}" for k in range(data.shape[0])
        ]
```

- [ ] **Step 4: Add `build_event_source_from_frame`**

Append to `src/tdt_ephyviewer_explorer/builders.py` (after `build_event_source`). Add `import pandas as pd` and `from typing import Optional` are not needed — use existing imports plus `import pandas as pd` at top:

```python
def build_event_source_from_frame(
    df: "pd.DataFrame",
    *,
    time_column: str,
    time_units: str,
    sampling_rate: float | None,
    label_column: str | None,
    formatter: StimFormatter | None,
    viewer_type: str,
    delay_ms: float,
) -> InMemoryEventSource:
    """Build an event source from a processed-parquet DataFrame.

    :param df: The loaded events DataFrame (one row per event).
    :param time_column: Column holding event onset.
    :param time_units: ``"samples"`` (converted via ``sampling_rate``) or ``"seconds"``.
    :param sampling_rate: Required when ``time_units == "samples"``.
    :param label_column: Column used directly for labels (takes precedence); else
        ``formatter`` is used, else integer indices.
    :param formatter: Row-to-label fallback formatter, or ``None``.
    :param viewer_type: Event source name (dock key).
    :param delay_ms: Milliseconds added to every timestamp.
    :raises ValueError: If ``time_units == "samples"`` without a ``sampling_rate``.
    """
    ts = df[time_column].to_numpy(dtype=float)
    if time_units == "samples":
        if not sampling_rate:
            raise ValueError("time_units='samples' requires a sampling_rate")
        ts = ts / float(sampling_rate)
    ts = ts + delay_ms / 1000.0
    if label_column and label_column in df.columns:
        labels = df[label_column].astype(str).to_numpy()
    elif formatter is not None:
        labels = np.array([formatter.format_row(row) for row in df.to_dict("records")])
    else:
        labels = np.array([str(i) for i in range(len(df))])
    return InMemoryEventSource(
        all_events=[{"name": viewer_type, "time": ts, "label": labels}]
    )
```

Add near the other top-of-file imports in `builders.py`:

```python
import pandas as pd
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builders.py -v`
Expected: PASS (existing + new builder tests).

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/builders.py tests/test_builders.py
git commit -m "feat(builders): store channel names + frame-based event source"
```

---

## Task 6: Load + build a source from a `ProcessedInfo`

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/processed.py`
- Test: `tests/test_processed.py`

**Interfaces:**
- Consumes: `ProcessedInfo`; `builders.{Attachment, build_analog_source, build_event_source_from_frame}`; `probe.load_probe`; `formatters.base.GenericFormatter`; `cfg.schemas`.
- Produces: `build_processed_source(info: ProcessedInfo, attachment: Attachment, cfg) -> object` (an ephyviewer source). Internal `_TimeseriesAdapter` (duck-typed: `.data`, `.fs`, `.start_time`, `.channel_names`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_processed.py`:

```python
from omegaconf import OmegaConf

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
    ev = src.all_events[0]
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_processed.py -k build_processed -v`
Expected: FAIL — `cannot import name 'build_processed_source'`.

- [ ] **Step 3: Implement the loader/builder**

Append to `src/tdt_ephyviewer_explorer/processed.py` (add imports at top of file):

```python
import numpy as np
import pandas as pd
from omegaconf import OmegaConf

from tdt_ephyviewer_explorer.builders import (
    Attachment,
    build_analog_source,
    build_event_source_from_frame,
)
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter
from tdt_ephyviewer_explorer.probe import load_probe


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_processed.py -v`
Expected: PASS (all processed tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/processed.py tests/test_processed.py
git commit -m "feat(processed): load and build ephyviewer sources from parquets"
```

---

## Task 7: `Session.processed` + `ProcessedSource` persistence

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `@dataclass ProcessedSource` with fields `path: str`, `kind: str`, `name: str`, `attachments: list[dict]`, and optional overrides `sampling_rate: float | None = None`, `t_start: float | None = None`, `time_column: str | None = None`, `time_units: str | None = None`, `label_column: str | None = None`.
  - `Session` gains `processed: list[ProcessedSource] = field(default_factory=list)`.
  - `load_session` reconstructs `processed` into `ProcessedSource` objects.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
from tdt_ephyviewer_explorer.session import ProcessedSource


def test_session_processed_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        attachments={"Wav1": [{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}]},
        processed=[
            ProcessedSource(
                path="torpedo/preprocessed/rRew03-1/raw_data_mep.parquet",
                kind="timeseries",
                name="raw_data_mep",
                attachments=[{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}],
            )
        ],
    )
    out = save_session(session, tmp_path, "s")
    loaded = load_session(out)
    assert loaded == session
    assert isinstance(loaded.processed[0], ProcessedSource)


def test_session_defaults_empty_processed() -> None:
    assert Session(block="b").processed == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_session.py -v`
Expected: FAIL — `cannot import name 'ProcessedSource'`.

- [ ] **Step 3: Implement the data model + load reconstruction**

Edit `src/tdt_ephyviewer_explorer/session.py`. Add the dataclass above `Session`, extend `Session`, and update `load_session`:

```python
@dataclass
class ProcessedSource:
    """A processed-parquet source composed into a session.

    :param path: Stored path (tank-relative when under the tank, else absolute).
    :param kind: ``"timeseries"`` or ``"event"``.
    :param name: Display / dock-prefix name.
    :param attachments: Serialized attachment dicts (same shape as TDT attachments).
    :param sampling_rate: Override used only for blob-less manually-added files.
    :param t_start: Override for blob-less files.
    :param time_column: Override for blob-less event files.
    :param time_units: Override for blob-less event files.
    :param label_column: Override for blob-less event files.
    """

    path: str
    kind: str
    name: str
    attachments: list[dict] = field(default_factory=list)
    sampling_rate: float | None = None
    t_start: float | None = None
    time_column: str | None = None
    time_units: str | None = None
    label_column: str | None = None


@dataclass
class Session:
    """A saved composition: which viewers are attached to which stores.

    :param block: Block directory name.
    :param attachments: TDT store name -> list of serialized attachment dicts.
    :param processed: Processed-parquet sources composed into this session.
    """

    block: str
    attachments: dict[str, list[dict]] = field(default_factory=dict)
    processed: list[ProcessedSource] = field(default_factory=list)
```

Update `load_session` to rebuild `ProcessedSource` objects:

```python
def load_session(path: Path) -> Session:
    """Load a session YAML written by :func:`save_session`."""
    cfg = OmegaConf.load(path)
    container = OmegaConf.to_container(cfg, resolve=True)
    assert isinstance(container, dict)
    processed = [ProcessedSource(**ps) for ps in container.get("processed", [])]
    return Session(
        block=container["block"],
        attachments=container["attachments"],
        processed=processed,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_session.py -v`
Expected: PASS (existing round-trip + new processed tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/session.py tests/test_session.py
git commit -m "feat(session): ProcessedSource and Session.processed persistence"
```

---

## Task 8: `plan_views` realizes processed sources

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/launcher.py:43-82` (`plan_views`)
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `session.processed` (`ProcessedSource`); `processed.{ProcessedInfo, classify, build_processed_source, from_stored_path}`; `builders._attachment_from_dict` (already local).
- Produces: `plan_views` appends one `ViewPlan` per processed attachment after the TDT ones. Helper `_processed_info(ps, tank_dir, cfg) -> ProcessedInfo`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher.py`:

```python
def test_plan_views_includes_processed_sources(tmp_path, monkeypatch) -> None:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import json

    from tdt_ephyviewer_explorer.processed import CONTRACT_KEY
    from tdt_ephyviewer_explorer.session import ProcessedSource

    # A tagged timeseries parquet under the tank.
    block = "blk"
    pdir = tmp_path / "torpedo" / "preprocessed" / block
    pdir.mkdir(parents=True)
    ppath = pdir / "raw_data_mep.parquet"
    table = pa.Table.from_pandas(pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]}))
    md = dict(table.schema.metadata or {})
    md[CONTRACT_KEY] = json.dumps({"contract_version": 1, "kind": "timeseries",
                                   "sampling_rate": 1000.0, "t_start": 0.0,
                                   "channel_names": ["a", "b"]}).encode()
    pq.write_table(table.replace_schema_metadata(md), ppath)

    # No TDT stores referenced; scan_block/read_headers are unused for a processed-only session.
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block=block,
        processed=[ProcessedSource(
            path="torpedo/preprocessed/blk/raw_data_mep.parquet",
            kind="timeseries", name="raw_data_mep",
            attachments=[{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}],
        )],
    )
    plans = plan_views(tmp_path / block, session, load_config())
    assert len(plans) == 1
    assert plans[0].name == "raw_data_mep:trace"
    assert plans[0].source.signals.shape == (2, 2)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_launcher.py::test_plan_views_includes_processed_sources -v`
Expected: FAIL — processed sources are ignored (0 plans).

- [ ] **Step 3: Implement processed realization in `plan_views`**

In `src/tdt_ephyviewer_explorer/launcher.py`, add imports at top:

```python
from tdt_ephyviewer_explorer.processed import (
    ProcessedInfo,
    build_processed_source,
    classify,
    from_stored_path,
)
```

Add a helper above `plan_views`:

```python
def _processed_info(ps: Any, tank_dir: Path, cfg: DictConfig) -> ProcessedInfo:
    """Resolve a :class:`~session.ProcessedSource` to a :class:`~processed.ProcessedInfo`.

    Classifies the file at its stored path; applies any blob-less overrides carried
    on the source.

    :param ps: The session's ProcessedSource.
    :param tank_dir: Tank directory (for relative-path resolution).
    :param cfg: Composed config.
    :raises FileNotFoundError: If the stored parquet no longer exists.
    """
    path = from_stored_path(ps.path, tank_dir)
    if not path.exists():
        raise FileNotFoundError(f"processed source {ps.path!r} not found under {tank_dir}")
    info = classify(path, cfg)
    if info is None:
        from tdt_ephyviewer_explorer.stores import VALID_VIEWERS
        info = ProcessedInfo(
            path=path, kind=ps.kind, role=ps.kind, name=ps.name,
            sampling_rate=ps.sampling_rate, t_start=ps.t_start or 0.0,
            channel_names=None, time_column=ps.time_column,
            time_units=ps.time_units or "seconds", label_column=ps.label_column,
            schema=None, units=None, viewers=VALID_VIEWERS[ps.kind],
        )
    return info
```

At the end of `plan_views`, before `return plans`, add the processed loop (`block_path.parent` is the tank dir):

```python
    tank_dir = block_path.parent
    for ps in session.processed:
        info = _processed_info(ps, tank_dir, cfg)
        for d in ps.attachments:
            attachment = _attachment_from_dict(d)
            source = build_processed_source(info, attachment, cfg)
            name = f"{ps.name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            plans.append(ViewPlan(name, attachment.viewer_type, params, source))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: PASS (existing launcher tests + new processed test).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/launcher.py tests/test_launcher.py
git commit -m "feat(launcher): realize processed sources in plan_views"
```

---

## Task 9: Control-tree spec + `spec_to_session`/`_apply_session` for processed sources

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/control_window.py` (`build_processed_param_spec`, `spec_to_session`, `_apply_session`)
- Test: `tests/test_control_window.py`

**Interfaces:**
- Consumes: `processed.ProcessedInfo`; `session.{Session, ProcessedSource}`.
- Produces:
  - `build_processed_param_spec(infos: list[ProcessedInfo], viewer_defaults: dict) -> list[dict]` — one group per processed source, each with readonly `source_path`, `source_kind`, `source_name`, plus `delay_ms`, optional `probe_file`/`reorder` (timeseries), and a `Viewers` subgroup.
  - `spec_to_session(block, param_state)` now returns a `Session` whose `processed` list is built from groups carrying `source_path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_control_window.py`:

```python
def test_build_processed_param_spec_group() -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer.control_window import build_processed_param_spec
    from tdt_ephyviewer_explorer.processed import ProcessedInfo
    from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

    info = ProcessedInfo(
        path=Path("torpedo/preprocessed/blk/raw_data_mep.parquet"),
        kind="timeseries", role="timeseries", name="raw_data_mep",
        sampling_rate=24414.0625, t_start=0.0, channel_names=["a", "b"],
        time_column=None, time_units="seconds", label_column=None, schema=None,
        units="uV", viewers=VALID_VIEWERS["timeseries"],
    )
    spec = build_processed_param_spec([info], {"trace": {}})
    grp = spec[0]
    assert grp["name"] == "raw_data_mep"
    names = {c["name"]: c for c in grp["children"]}
    assert names["source_path"]["readonly"] is True
    assert names["source_kind"]["value"] == "timeseries"
    assert "probe_file" in names  # timeseries -> probe controls
    viewers = next(c for c in grp["children"] if c["name"] == "Viewers")
    assert "trace" in {c["name"] for c in viewers["children"]}


def test_spec_to_session_emits_processed() -> None:
    from tdt_ephyviewer_explorer.control_window import spec_to_session

    state = {
        "raw_data_mep": {
            "source_path": "torpedo/preprocessed/blk/raw_data_mep.parquet",
            "source_kind": "timeseries",
            "source_name": "raw_data_mep",
            "delay_ms": 0.0, "probe_file": "", "reorder": False,
            "Viewers": {"trace": {"_enabled": True}},
        },
        "Wav1": {  # a normal TDT store still becomes an attachment
            "delay_ms": 5.0, "Viewers": {"trace": {"_enabled": True}},
        },
    }
    session = spec_to_session("blk", state)
    assert list(session.attachments) == ["Wav1"]
    assert len(session.processed) == 1
    ps = session.processed[0]
    assert ps.name == "raw_data_mep" and ps.kind == "timeseries"
    assert ps.path == "torpedo/preprocessed/blk/raw_data_mep.parquet"
    assert ps.attachments[0]["viewer_type"] == "trace"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_control_window.py -k "processed" -v`
Expected: FAIL — `cannot import name 'build_processed_param_spec'`; `spec_to_session` has no `processed`.

- [ ] **Step 3: Implement the processed spec builder**

In `src/tdt_ephyviewer_explorer/control_window.py`, add imports and a new function after `build_param_tree_spec`:

```python
from tdt_ephyviewer_explorer.processed import ProcessedInfo
from tdt_ephyviewer_explorer.session import ProcessedSource


def build_processed_param_spec(
    infos: list[ProcessedInfo], viewer_defaults: dict
) -> list[dict]:
    """Build parametertree groups for processed-parquet sources.

    Each group carries readonly ``source_path``/``source_kind``/``source_name`` so
    :func:`spec_to_session` can round-trip it into a :class:`~session.ProcessedSource`.

    :param infos: Classified processed sources.
    :param viewer_defaults: Per-viewer default params.
    :returns: A list of group-parameter dicts.
    """
    groups: list[dict] = []
    for info in infos:
        children: list[dict] = [
            {"name": "source_path", "type": "str", "value": str(info.path), "readonly": True},
            {"name": "source_kind", "type": "str", "value": info.kind, "readonly": True},
            {"name": "source_name", "type": "str", "value": info.name, "readonly": True},
            {"name": "fs", "type": "float", "value": info.sampling_rate or 0.0, "readonly": True},
            {"name": "delay_ms", "type": "float", "value": 0.0},
        ]
        if info.role == "timeseries":
            children.append({"name": "probe_file", "type": "str", "value": ""})
            children.append({"name": "reorder", "type": "bool", "value": False})
        viewer_children = [
            {"name": vt, "type": "bool", "value": False,
             "children": _params_children(viewer_defaults.get(vt, {}))}
            for vt in info.viewers
        ]
        children.append({"name": "Viewers", "type": "group", "children": viewer_children})
        groups.append({"name": info.name, "type": "group", "children": children})
    return groups
```

- [ ] **Step 4: Update `spec_to_session` to split TDT vs processed groups**

Replace the body of `spec_to_session` in `control_window.py` with:

```python
def spec_to_session(block: str, param_state: dict) -> Session:
    """Convert a saved parametertree state into a :class:`Session`.

    Groups carrying ``source_path`` become :class:`~session.ProcessedSource` entries;
    all others are TDT store attachments.

    :param block: Block name.
    :param param_state: Per-group tree state.
    :returns: The composition session (only enabled viewers included).
    """
    attachments: dict[str, list[dict]] = {}
    processed: list[ProcessedSource] = []
    for name, state in param_state.items():
        entries = _enabled_attachments(state)
        if not entries:
            continue
        if "source_path" in state:
            processed.append(
                ProcessedSource(
                    path=str(state["source_path"]),
                    kind=str(state.get("source_kind", "")),
                    name=str(state.get("source_name", name)),
                    attachments=entries,
                )
            )
        else:
            attachments[name] = entries
    return Session(block=block, attachments=attachments, processed=processed)


def _enabled_attachments(state: dict) -> list[dict]:
    """Extract enabled viewer attachments from one group's tree state."""
    viewers = state.get("Viewers", {})
    probe = state.get("probe_file") or None
    entries: list[dict] = []
    for vt, vstate in viewers.items():
        if not vstate.get("_enabled"):
            continue
        params = {k: v for k, v in vstate.items() if k != "_enabled"}
        entries.append(
            {
                "viewer_type": vt,
                "delay_ms": float(state.get("delay_ms", 0.0)),
                "probe_path": probe if state.get("reorder") else None,
                "params": params,
            }
        )
    return entries
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_control_window.py -v`
Expected: PASS (existing tree/session tests + new processed tests).

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/control_window.py tests/test_control_window.py
git commit -m "feat(control): processed tree groups and spec_to_session split"
```

---

## Task 10: Auto-scan on block select + "Add processed…" button

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/control_window.py` (`set_block`, `__init__`, `_apply_session`, new `_scan_processed`/`_add_processed_dialog`)
- Test: `tests/test_control_window.py`

**Interfaces:**
- Consumes: `processed.{scan_preprocessed, classify, to_stored_path}`; `cfg.processed.auto_scan`.
- Produces: `ControlWindow.set_block` appends processed groups after the TDT groups when `auto_scan`; a "Add processed…" button calls `add_processed_paths(paths: list[Path])`; `_apply_session` restores processed groups.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_control_window.py` (uses the existing `qapp` fixture):

```python
def test_set_block_auto_scans_processed(qapp, monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.processed import ProcessedInfo
    from tdt_ephyviewer_explorer.stores import StoreInfo, VALID_VIEWERS

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(cw_mod, "scan_block", lambda p, headers=None:
                        [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)])
    fake = ProcessedInfo(
        path=Path("torpedo/preprocessed/blk/raw_data_mep.parquet"),
        kind="timeseries", role="timeseries", name="raw_data_mep",
        sampling_rate=1000.0, t_start=0.0, channel_names=["a"], time_column=None,
        time_units="seconds", label_column=None, schema=None, units="uV",
        viewers=VALID_VIEWERS["timeseries"],
    )
    monkeypatch.setattr(cw_mod, "scan_preprocessed", lambda tank, block, cfg: [fake])

    cw = ControlWindow(load_config())
    cw._tank_dir = tmp_path
    cw.set_block(tmp_path / "blk")
    group_names = {g.name() for g in cw._root.children()}
    assert "Wav1" in group_names
    assert "raw_data_mep" in group_names
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_control_window.py::test_set_block_auto_scans_processed -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'scan_preprocessed'` / group absent.

- [ ] **Step 3: Wire auto-scan into `set_block`**

In `control_window.py`, add imports:

```python
from tdt_ephyviewer_explorer.processed import (
    classify,
    scan_preprocessed,
    to_stored_path,
)
```

Extend `set_block` (append processed groups after the TDT spec is added). Replace the tail of `set_block` with:

```python
        resolved = [resolve_role(i, self._rules) for i in scan_block(block_path, headers=self._headers)]
        spec = build_param_tree_spec(resolved, self._viewer_defaults)
        self._root.clearChildren()
        self._root.addChildren(spec)
        self._append_processed_groups(block_path)

    def _append_processed_groups(self, block_path: Path) -> None:
        """Auto-scan the preprocessed dir for this block and add processed groups."""
        if not self._cfg.processed.auto_scan or self._tank_dir is None:
            return
        infos = scan_preprocessed(self._tank_dir, block_path.name, self._cfg)
        if infos:
            self._root.addChildren(build_processed_param_spec(infos, self._viewer_defaults))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_control_window.py -v`
Expected: PASS.

- [ ] **Step 5: Add the "Add processed…" button and manual-add flow**

In `ControlWindow.__init__`, after the load button, add:

```python
        add_btn = QtWidgets.QPushButton("Add processed…")
        add_btn.clicked.connect(self._on_add_processed)
        layout.addWidget(add_btn)
```

Add these methods to `ControlWindow`:

```python
    def _on_add_processed(self) -> None:
        """Prompt for parquet files and add them as processed groups."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add processed parquet(s)", "", "Parquet (*.parquet)"
        )
        if paths:
            self.add_processed_paths([Path(p) for p in paths])

    def add_processed_paths(self, paths: list[Path]) -> None:
        """Classify each parquet and append it as a processed group.

        Files that classify (via contract or heuristic) are added directly. A file
        that cannot be classified as a timeseries for lack of a sample rate prompts
        for one; unrecognizable files are skipped.

        :param paths: Parquet file paths (any location).
        """
        infos = []
        for path in paths:
            info = classify(path, self._cfg)
            if info is None:
                info = self._prompt_processed_info(path)
            if info is not None:
                infos.append(info)
        if infos:
            self._root.addChildren(build_processed_param_spec(infos, self._viewer_defaults))

    def _prompt_processed_info(self, path: Path) -> ProcessedInfo | None:
        """Ask for a sampling rate and treat a blob-less file as a timeseries.

        :param path: The parquet path.
        :returns: A timeseries :class:`ProcessedInfo`, or ``None`` if cancelled.
        """
        from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

        rate, ok = QtWidgets.QInputDialog.getDouble(
            self, "Sampling rate", f"{path.name}: sampling rate (Hz)",
            float(self._cfg.processed.default_sampling_rate), 0.0, 1e9, 4,
        )
        if not ok:
            return None
        return ProcessedInfo(
            path=path, kind="timeseries", role="timeseries", name=path.stem,
            sampling_rate=rate, t_start=0.0, channel_names=None, time_column=None,
            time_units="seconds", label_column=None, schema=None, units=None,
            viewers=VALID_VIEWERS["timeseries"],
        )
```

Also make processed groups store tank-relative paths when added from under the tank: in `build_processed_param_spec` the `source_path` uses `str(info.path)`. Update `_append_processed_groups` and `add_processed_paths` to normalize the path via `to_stored_path` before building the spec by rewriting each `info` with a stored path. Add this helper and use it in both call sites:

```python
    def _with_stored_paths(self, infos: list[ProcessedInfo]) -> list[ProcessedInfo]:
        """Return copies of ``infos`` whose ``path`` is the stored (rel/abs) form."""
        from dataclasses import replace

        if self._tank_dir is None:
            return infos
        return [replace(i, path=Path(to_stored_path(i.path, self._tank_dir))) for i in infos]
```

Then in `_append_processed_groups` and `add_processed_paths`, wrap: `build_processed_param_spec(self._with_stored_paths(infos), self._viewer_defaults)`.

- [ ] **Step 6: Update `_apply_session` to restore processed groups**

`_apply_session` currently only restores TDT store groups. Processed groups are rebuilt from the session before applying viewer state. Add at the start of `_apply_session`, before the existing loop:

```python
        # Rebuild processed groups from the session so their viewer state can be applied.
        existing = {g.name() for g in self._root.children()}
        new_infos = []
        for ps in session.processed:
            if ps.name in existing:
                continue
            from tdt_ephyviewer_explorer.processed import ProcessedInfo
            from tdt_ephyviewer_explorer.stores import VALID_VIEWERS
            new_infos.append(ProcessedInfo(
                path=Path(ps.path), kind=ps.kind, role=ps.kind, name=ps.name,
                sampling_rate=ps.sampling_rate, t_start=ps.t_start or 0.0,
                channel_names=None, time_column=ps.time_column,
                time_units=ps.time_units or "seconds", label_column=ps.label_column,
                schema=None, units=None, viewers=VALID_VIEWERS[ps.kind],
            ))
        if new_infos:
            self._root.addChildren(build_processed_param_spec(new_infos, self._viewer_defaults))
```

Then extend the existing `_apply_session` viewer-restore loop to also handle processed groups: the loop keys off `session.attachments.get(store.name(), [])`; add a lookup into processed sources so their viewers are enabled too. Replace the `entries` lookup line:

```python
        by_name_processed = {ps.name: ps.attachments for ps in session.processed}
        for store in self._root.children():
            entries = session.attachments.get(store.name(), []) or by_name_processed.get(store.name(), [])
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (whole suite; the one real-`tdt` test remains skipped without `TDT_EXPLORE_TEST_BLOCK`).

- [ ] **Step 8: Commit**

```bash
git add src/tdt_ephyviewer_explorer/control_window.py tests/test_control_window.py
git commit -m "feat(control): auto-scan processed dir + Add processed button"
```

---

## Task 11: Optional real-data smoke test (env-gated)

**Files:**
- Test: `tests/test_processed.py`

**Interfaces:**
- Consumes: `scan_preprocessed`, `build_processed_source`. Gated on env var `TDT_EXPLORE_PREPROCESSED_BLOCK=<tank>|<block>` so it never runs in CI/headless-by-default.

- [ ] **Step 1: Add the gated test**

Append to `tests/test_processed.py`:

```python
import os

import pytest


@pytest.mark.skipif(
    "TDT_EXPLORE_PREPROCESSED_BLOCK" not in os.environ,
    reason="set TDT_EXPLORE_PREPROCESSED_BLOCK=<tank>|<block> to run against real parquets",
)
def test_scan_and_build_on_real_block() -> None:
    tank_str, block = os.environ["TDT_EXPLORE_PREPROCESSED_BLOCK"].split("|")
    tank = Path(tank_str)
    infos = scan_preprocessed(tank, block, load_config())
    assert infos, "expected at least one tagged parquet"
    for info in infos:
        vt = info.viewers[0]
        src = build_processed_source(info, Attachment(vt), load_config())
        assert src is not None
```

- [ ] **Step 2: Run it (gated — expect skip by default)**

Run: `uv run pytest tests/test_processed.py::test_scan_and_build_on_real_block -v`
Expected: SKIPPED.

Optional manual verification against real data (blocks with `raw_data_mep`):

Run: `TDT_EXPLORE_PREPROCESSED_BLOCK="C:/TDT/Synapse/Tanks/cnn_gp_mep_all_udp_v2-260626-115952|rRew03-260626-131130" uv run pytest tests/test_processed.py::test_scan_and_build_on_real_block -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_processed.py
git commit -m "test(processed): env-gated real-data smoke test"
```

---

## Task 12: Docs — README ingestion note

**Files:**
- Modify: `README.md`

**Interfaces:** none.

- [ ] **Step 1: Add a "Processed parquet ingestion" subsection**

Add to `README.md` a short subsection documenting: auto-discovery of `<tank>/torpedo/preprocessed/<block>/*.parquet` (contract-tagged files only), the "Add processed…" button for arbitrary files, the `processed:` config keys, and the env var `TDT_EXPLORE_PREPROCESSED_BLOCK` for the smoke test. Reference the contract brief at `docs/notes/2026-07-23-tss-pipeline-metadata-contract-brief.md`.

- [ ] **Step 2: Run the full suite once more**

Run: `uv run pytest`
Expected: PASS (Qt-free suite green; real-`tdt` and real-parquet tests skipped).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document processed-parquet ingestion"
```

---

## Self-Review notes (for the executor)

- **Spec coverage:** contract read (T1), config (T2), classify/heuristics (T3), scan + path rule (T4), builder reuse + event builder (T5), load/build (T6), Session model (T7), plan_views (T8), tree + session split (T9), auto-scan + Add button + apply_session (T10), real-data smoke (T11), docs (T12). All spec §§2–8 map to tasks.
- **Type consistency:** `ProcessedInfo` field order is fixed in T3 and reused positionally in T8/T9/T10 — keep the 13-field order (`path, kind, role, name, sampling_rate, t_start, channel_names, time_column, time_units, label_column, schema, units, viewers`). `build_event_source_from_frame` is keyword-only; callers in T6 pass all keywords.
- **No hardcoded values:** rates/paths/candidates come from `cfg.processed`; the only literal `24414.0625` in code is the config default (T2).
```
