# Impedance Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an impedance heatmap viewer to `tdt-explore` that reads the per-block impedance CSV sidecars, averages rows per stimulation frequency, and lays contacts out in probe topology.

**Architecture:** Impedance CSVs become a third source category beside TDT stores and processed parquets, following the repo's Qt-free-core rule: a new `impedance.py` does all discovery, parsing, averaging, and grid building with no Qt import, and a thin `viewers/impedance_view.py` renders it. Session persistence, the Control Window parameter tree, and `plan_views` each gain a small impedance branch mirroring their existing processed-parquet branch.

**Tech Stack:** Python 3.12+, `uv`, Hydra/OmegaConf, pandas, NumPy, probeinterface, pyqtgraph 0.14, PySide6, the `ephyviewer` fork at `../ephyviewer`.

**Spec:** `docs/superpowers/specs/2026-07-30-impedance-viewer-design.md`

## Global Constraints

- Python 3.12+. Always run through the venv: `uv run pytest`, `uv run python`. Never bare `python`/`pytest`/`pip`.
- Strict type hints on every function signature. reST (`:param:`/`:returns:`/`:raises:`) docstrings.
- No hardcoded absolute paths anywhere in `src/` or `tests/`. Test data goes in `tests/fixtures/`.
- No magic numbers: every tunable value lives in `src/tdt_ephyviewer_explorer/config/`, never inline in code.
- No silent failures: a malformed probe, a channel/contact count mismatch, or a missing file raises with a message naming the offender. Skipping a file is allowed only where the spec says so, and must be logged.
- Raw block directories are read-only. This feature only ever **reads** the CSVs.
- The test suite is Qt-free and headless except for the handful of `qapp`-fixture smoke tests already in `tests/test_launcher.py`. Do not add Qt to any other test module.
- Every task ends with `uv run pytest` fully green before committing.
- Commit messages: conventional-commit prefix, extremely concise, no trailing attribution.

## Deviation from the spec (deliberate)

The spec placed `build_impedance_source` in `builders.py`. This plan puts it in `impedance.py` instead, mirroring `processed.build_processed_source`, so `builders.py` changes only to register the viewer class. Same behaviour, better symmetry with the existing parquet path.

---

### Task 1: Config group

Adds the `impedance` discovery settings and the `viewers.impedance` defaults. Everything downstream reads these, so it lands first.

**Files:**
- Create: `src/tdt_ephyviewer_explorer/config/impedance/default.yaml`
- Modify: `src/tdt_ephyviewer_explorer/config/config.yaml`
- Modify: `src/tdt_ephyviewer_explorer/config/viewer/default.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `cfg.impedance.{auto_scan, globs, channel_regex, frequency_column, min_channels}` and `cfg.viewers.impedance.{vmin, vmax, annotate, annotation_format, cmap}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_load_config_has_impedance_group() -> None:
    cfg = load_config()
    assert cfg.impedance.auto_scan is True
    assert list(cfg.impedance.globs) == ["*.csv"]
    assert cfg.impedance.frequency_column == "FREQUENCY (Hz)"
    assert cfg.impedance.min_channels == 4


def test_load_config_has_impedance_viewer_defaults() -> None:
    cfg = load_config()
    assert cfg.viewers.impedance.vmin == 0.0
    assert cfg.viewers.impedance.vmax == 200.0
    assert cfg.viewers.impedance.annotate is True
    assert cfg.viewers.impedance.annotation_format == "{:.0f}"
    assert cfg.viewers.impedance.cmap == "viridis"


def test_impedance_channel_regex_matches_rig_headers() -> None:
    # The rig writes "R1 (kOhm)" ... "R64 (kOhm)"; TIME/FREQUENCY/TARGET/REF are metadata.
    import re

    rx = re.compile(load_config().impedance.channel_regex)
    match = rx.match("R12 (kOhm)")
    assert match is not None
    assert match.group(1) == "12"
    assert match.group(2) == "kOhm"
    assert rx.match("REF (kOhm)") is None
    assert rx.match("TIME (S)") is None
    assert rx.match("TARGET (uA)") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ConfigAttributeError: Key 'impedance' is not in struct`

- [ ] **Step 3: Create the impedance config group**

Create `src/tdt_ephyviewer_explorer/config/impedance/default.yaml`:

```yaml
# @package _global_
# Impedance CSV sidecars written by the rig into the block directory.
impedance:
  auto_scan: true                        # scan the block dir on block select
  globs: ["*.csv"]                       # block-dir globs; non-impedance CSVs fail the sniff
  channel_regex: '^R(\d+)\s*\((\w+)\)$'  # group 1 = channel number, group 2 = units
  frequency_column: "FREQUENCY (Hz)"     # absent from a file -> a single frequency group
  min_channels: 4                        # header-sniff threshold
```

The regex is single-quoted so YAML keeps the backslashes literal.

- [ ] **Step 4: Compose the group**

In `src/tdt_ephyviewer_explorer/config/config.yaml`, add `- impedance: default` to the
defaults list, immediately after `- processed: default` and before `- metadata: default`.

- [ ] **Step 5: Add the viewer defaults**

In `src/tdt_ephyviewer_explorer/config/viewer/default.yaml`, append under `viewers:`:

```yaml
  impedance:
    vmin: 0.0                  # kOhm
    vmax: 200.0                # kOhm; values outside [vmin, vmax] clamp to the end colors
    annotate: true
    annotation_format: "{:.0f}"
    cmap: viridis
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 7: Commit**

```bash
git add src/tdt_ephyviewer_explorer/config tests/test_config.py
git commit -m "feat(impedance): config group for CSV discovery and viewer defaults"
```

---

### Task 2: Probe grid layout

Turns a probeinterface file into 2D grid coordinates, from `topo_x`/`topo_y` when present and from `contact_positions` otherwise.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/probe.py`
- Create: `tests/fixtures/probe_topo_4ch.json`
- Create: `tests/fixtures/probe_dup_topo_2ch.json`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Layout(col: np.ndarray, row: np.ndarray, n_cols: int, n_rows: int)` — frozen dataclass; `col`/`row` are per-contact 0-based grid indices, `row=0` is the top row when rendered.
  - `probe_layout(path: Path) -> Layout` — raises `ValueError` if two contacts land in the same cell.

**Design note for the implementer:** `probe_layout` reads the probeinterface file itself rather than extending `ProbeMap`. That is deliberate: computing a layout inside `load_probe` would make a duplicate-cell probe raise for the *timeseries* viewers too, which do not need a layout and work fine with such a probe. Probe JSONs are a few kilobytes, so the extra read is free.

Coordinates are **ranked**, not used raw: the sorted unique `topo_x` values map to columns 0..n-1. For `tdt_64ch.json` (complete 0..7) the rank equals the value, but ranking also handles sparse or micron-valued annotations, and it is the same code path the `contact_positions` fallback needs.

- [ ] **Step 1: Create the two probe fixtures**

Create `tests/fixtures/probe_topo_4ch.json` — carries `topo_x`/`topo_y` describing a 2×2 grid:

```json
{
  "specification": "probeinterface",
  "version": "0.3.2",
  "probes": [
    {
      "ndim": 2,
      "si_units": "um",
      "annotations": {},
      "contact_annotations": {
        "brain_region": ["A", "B", "C", "D"],
        "topo_x": [1, 0, 1, 0],
        "topo_y": [0, 0, 1, 1]
      },
      "contact_positions": [[0, 0], [0, 100], [0, 200], [0, 300]],
      "contact_plane_axes": [[0, 1], [0, 1], [0, 1], [0, 1]],
      "contact_shapes": ["circle", "circle", "circle", "circle"],
      "contact_shape_params": [{"radius": 5}, {"radius": 5}, {"radius": 5}, {"radius": 5}],
      "device_channel_indices": [3, 2, 1, 0],
      "contact_ids": ["00", "01", "02", "03"],
      "shank_ids": ["0", "0", "0", "0"]
    }
  ]
}
```

Note the `contact_positions` here are a 1×4 strip that *disagrees* with the topo grid — that is
intentional, so the test proves the topo annotations win.

Create `tests/fixtures/probe_dup_topo_2ch.json` — two contacts annotated into the same cell:

```json
{
  "specification": "probeinterface",
  "version": "0.3.2",
  "probes": [
    {
      "ndim": 2,
      "si_units": "um",
      "annotations": {},
      "contact_annotations": {
        "topo_x": [0, 0],
        "topo_y": [0, 0]
      },
      "contact_positions": [[0, 0], [0, 100]],
      "contact_plane_axes": [[0, 1], [0, 1]],
      "contact_shapes": ["circle", "circle"],
      "contact_shape_params": [{"radius": 5}, {"radius": 5}],
      "device_channel_indices": [0, 1],
      "contact_ids": ["00", "01"],
      "shank_ids": ["0", "0"]
    }
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_probe.py` (and extend the existing import line to bring in `Layout`
and `probe_layout`):

```python
TOPO_FIXTURE = Path(__file__).parent / "fixtures" / "probe_topo_4ch.json"
DUP_FIXTURE = Path(__file__).parent / "fixtures" / "probe_dup_topo_2ch.json"


def test_probe_layout_uses_topo_annotations() -> None:
    # topo_x [1,0,1,0] / topo_y [0,0,1,1] -> a 2x2 grid, overriding the 1x4
    # arrangement that contact_positions alone would imply.
    layout = probe_layout(TOPO_FIXTURE)
    assert (layout.n_cols, layout.n_rows) == (2, 2)
    assert list(layout.col) == [1, 0, 1, 0]
    assert list(layout.row) == [0, 0, 1, 1]


def test_probe_layout_infers_from_contact_positions() -> None:
    # probe_4ch.json has no topo annotations: x is constant, y is 0/100/200/300,
    # so the contacts infer to a single column of four rows.
    layout = probe_layout(FIXTURE)
    assert (layout.n_cols, layout.n_rows) == (1, 4)
    assert list(layout.col) == [0, 0, 0, 0]
    assert list(layout.row) == [0, 1, 2, 3]


def test_probe_layout_duplicate_cell_raises() -> None:
    with pytest.raises(ValueError, match="both map to grid cell"):
        probe_layout(DUP_FIXTURE)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_probe.py -v`
Expected: FAIL with `ImportError: cannot import name 'probe_layout'`

- [ ] **Step 4: Implement `Layout` and `probe_layout`**

Append to `src/tdt_ephyviewer_explorer/probe.py` (and add `from typing import Sequence` to
the imports):

```python
@dataclass(frozen=True)
class Layout:
    """2D grid placement of probe contacts.

    :param col: Column index per contact.
    :param row: Row index per contact; ``0`` is the top row when rendered.
    :param n_cols: Number of grid columns.
    :param n_rows: Number of grid rows.
    """

    col: np.ndarray
    row: np.ndarray
    n_cols: int
    n_rows: int


def _rank(values: np.ndarray) -> tuple[np.ndarray, int]:
    """Map values onto 0-based ranks of their sorted unique values.

    Ranking (rather than using coordinates directly) lets the same code handle
    integer topo annotations, sparse annotations, and micron positions.

    :param values: One coordinate per contact.
    :returns: The per-contact rank and the number of distinct values.
    """
    unique = np.unique(values)
    return np.searchsorted(unique, values), int(unique.size)


def _check_unique_cells(col: np.ndarray, row: np.ndarray, ids: Sequence[str]) -> None:
    """Raise if two contacts resolve to the same grid cell.

    :param col: Per-contact column index.
    :param row: Per-contact row index.
    :param ids: Per-contact identifiers, used to name the offenders.
    :raises ValueError: If any cell is claimed twice.
    """
    seen: dict[tuple[int, int], str] = {}
    for k, cell in enumerate(zip(col.tolist(), row.tolist())):
        if cell in seen:
            raise ValueError(
                f"contacts {seen[cell]!r} and {ids[k]!r} both map to grid cell "
                f"(col={cell[0]}, row={cell[1]}); check topo_x/topo_y or contact_positions"
            )
        seen[cell] = ids[k]


def probe_layout(path: Path) -> Layout:
    """Derive a 2D contact grid from a probeinterface JSON file.

    Uses the ``topo_x``/``topo_y`` contact annotations when both are present, since
    they express the intended anatomical arrangement; otherwise infers the grid by
    ranking the distinct ``contact_positions`` coordinates.

    Reads the file independently of :func:`load_probe` on purpose: a probe whose
    contacts collide in grid space is still perfectly usable for trace reordering,
    so that failure must not be raised on the timeseries path.

    :param path: Path to the ``.json`` probe file.
    :returns: The per-contact grid placement.
    :raises ValueError: If two contacts resolve to the same grid cell.
    """
    probe = read_probeinterface(str(path)).probes[0]
    annotations = probe.contact_annotations
    topo_x, topo_y = annotations.get("topo_x"), annotations.get("topo_y")
    if topo_x is not None and topo_y is not None:
        col, n_cols = _rank(np.asarray(topo_x))
        row, n_rows = _rank(np.asarray(topo_y))
    else:
        positions = np.asarray(probe.contact_positions, dtype=float)
        col, n_cols = _rank(positions[:, 0])
        row, n_rows = _rank(positions[:, 1])
    ids = probe.contact_ids
    labels = [str(i) for i in ids] if ids is not None else [str(k) for k in range(col.size)]
    _check_unique_cells(col, row, labels)
    return Layout(col=col, row=row, n_cols=n_cols, n_rows=n_rows)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_probe.py -v`
Expected: PASS (6 tests — the 3 new ones plus the 3 existing, unchanged)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tdt_ephyviewer_explorer/probe.py tests/test_probe.py tests/fixtures/probe_topo_4ch.json tests/fixtures/probe_dup_topo_2ch.json
git commit -m "feat(impedance): derive a 2D contact grid from a probe file"
```

---

### Task 3: Impedance CSV discovery and parsing

The Qt-free core: recognize impedance CSVs by header shape, and average their rows within each stimulation frequency.

**Files:**
- Create: `src/tdt_ephyviewer_explorer/impedance.py`
- Create: `tests/fixtures/impedance_1row.csv`
- Create: `tests/fixtures/impedance_2freq.csv`
- Create: `tests/fixtures/impedance_nofreq.csv`
- Create: `tests/fixtures/impedance_empty.csv`
- Create: `tests/fixtures/not_impedance.csv`
- Test: `tests/test_impedance.py`

**Interfaces:**
- Consumes: `cfg.impedance.*` (Task 1).
- Produces:
  - `ImpedanceInfo(path: Path, name: str, frequencies: tuple[float, ...], channel_numbers: tuple[int, ...], units: str)`
  - `FrequencyGroup(frequency: float | None, values: np.ndarray, metadata: dict[str, float])`
  - `ImpedanceData(name: str, channel_numbers: tuple[int, ...], units: str, groups: tuple[FrequencyGroup, ...])`
  - `classify_impedance_csv(path: Path, cfg: Any) -> ImpedanceInfo | None`
  - `scan_impedance(block_path: Path, cfg: Any) -> list[ImpedanceInfo]`
  - `read_impedance(path: Path, cfg: Any) -> ImpedanceData`

- [ ] **Step 1: Create the CSV fixtures**

These mirror the real rig files (`spinal.csv`, `EMG.csv`) at 4 channels instead of 64/16.

`tests/fixtures/impedance_1row.csv` — the `spinal.csv` shape, one data row:

```
TIME (S),FREQUENCY (Hz),TARGET (uA),R1 (kOhm),R2 (kOhm),R3 (kOhm),R4 (kOhm)
4,1000,5,10.0,20.0,30.0,40.0
```

`tests/fixtures/impedance_2freq.csv` — two frequencies, two rows at 1000 Hz to average, plus a `REF` metadata column:

```
TIME (S),FREQUENCY (Hz),R1 (kOhm),R2 (kOhm),R3 (kOhm),R4 (kOhm),REF (kOhm)
1,1000,10.0,20.0,30.0,40.0,5.0
2,1000,20.0,30.0,40.0,50.0,7.0
3,5000,100.0,200.0,300.0,400.0,9.0
```

`tests/fixtures/impedance_nofreq.csv` — no frequency column, so all rows form one group:

```
TIME (S),R1 (kOhm),R2 (kOhm),R3 (kOhm),R4 (kOhm)
1,10.0,20.0,30.0,40.0
2,20.0,30.0,40.0,50.0
```

`tests/fixtures/impedance_empty.csv` — the `EMG.csv` case: a valid header and **zero** data rows:

```
TIME (S),FREQUENCY (Hz),R1 (kOhm),R2 (kOhm),R3 (kOhm),R4 (kOhm),REF (kOhm)
```

`tests/fixtures/not_impedance.csv` — an unrelated CSV that must not be picked up:

```
timestamp,stim_site,amplitude
0.5,A,100
1.5,B,200
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_impedance.py`:

```python
"""Tests for impedance CSV discovery, parsing, and per-frequency averaging."""
import shutil
from pathlib import Path

import numpy as np
import pytest

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.impedance import (
    classify_impedance_csv,
    read_impedance,
    scan_impedance,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_classify_reads_channels_and_units(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_1row.csv", cfg)
    assert info is not None
    assert info.name == "impedance_1row"
    assert info.channel_numbers == (1, 2, 3, 4)
    assert info.units == "kOhm"


def test_classify_collects_distinct_frequencies(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_2freq.csv", cfg)
    assert info is not None
    assert info.frequencies == (1000.0, 5000.0)  # sorted, deduplicated


def test_classify_reports_no_frequencies_without_the_column(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_nofreq.csv", cfg)
    assert info is not None
    assert info.frequencies == ()


def test_classify_rejects_non_impedance_csv(cfg) -> None:
    assert classify_impedance_csv(FIXTURES / "not_impedance.csv", cfg) is None


def test_classify_skips_header_only_file(cfg) -> None:
    # The real EMG.csv has a valid impedance header but no data rows.
    assert classify_impedance_csv(FIXTURES / "impedance_empty.csv", cfg) is None


def test_scan_impedance_finds_only_impedance_csvs(tmp_path, cfg) -> None:
    for name in ("impedance_1row.csv", "impedance_2freq.csv",
                 "impedance_empty.csv", "not_impedance.csv"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    (tmp_path / "Notes.txt").write_text("not a csv")

    infos = scan_impedance(tmp_path, cfg)
    assert [i.name for i in infos] == ["impedance_1row", "impedance_2freq"]


def test_scan_impedance_respects_auto_scan_false(tmp_path) -> None:
    shutil.copy(FIXTURES / "impedance_1row.csv", tmp_path / "impedance_1row.csv")
    cfg = load_config(overrides=["impedance.auto_scan=false"])
    assert scan_impedance(tmp_path, cfg) == []


def test_read_impedance_averages_rows_within_frequency(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_2freq.csv", cfg)
    assert [g.frequency for g in data.groups] == [1000.0, 5000.0]
    # 1000 Hz: mean of [10,20,30,40] and [20,30,40,50]
    assert list(data.groups[0].values) == [15.0, 25.0, 35.0, 45.0]
    assert list(data.groups[1].values) == [100.0, 200.0, 300.0, 400.0]


def test_read_impedance_single_group_without_frequency_column(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_nofreq.csv", cfg)
    assert len(data.groups) == 1
    assert data.groups[0].frequency is None
    assert list(data.groups[0].values) == [15.0, 25.0, 35.0, 45.0]


def test_read_impedance_carries_metadata_columns(cfg) -> None:
    # REF is not a numbered channel, so it must not become a grid cell; it is
    # averaged per frequency and surfaced for the viewer footer instead.
    data = read_impedance(FIXTURES / "impedance_2freq.csv", cfg)
    assert data.groups[0].metadata["REF (kOhm)"] == 6.0  # mean of 5.0 and 7.0
    assert data.groups[1].metadata["REF (kOhm)"] == 9.0
    assert "R1 (kOhm)" not in data.groups[0].metadata


def test_read_impedance_reports_units_and_channels(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    assert data.units == "kOhm"
    assert data.channel_numbers == (1, 2, 3, 4)
    assert list(data.groups[0].values) == [10.0, 20.0, 30.0, 40.0]


def test_read_impedance_coerces_unmeasured_cells_to_nan(cfg, tmp_path) -> None:
    # A rig that fails to measure a contact writes a blank or a marker string.
    # That column must become NaN (an empty cell) rather than crashing the mean.
    csv = tmp_path / "gappy.csv"
    csv.write_text(
        "TIME (S),R1 (kOhm),R2 (kOhm),R3 (kOhm),R4 (kOhm)\n"
        "1,10.0,,30.0,OL\n"
        "2,20.0,,50.0,OL\n"
    )
    values = read_impedance(csv, cfg).groups[0].values
    assert values[0] == 15.0
    assert np.isnan(values[1])  # entirely blank column
    assert values[2] == 40.0
    assert np.isnan(values[3])  # non-numeric column
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_impedance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.impedance'`

- [ ] **Step 4: Implement the module**

Create `src/tdt_ephyviewer_explorer/impedance.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_impedance.py -v`
Expected: PASS (12 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tdt_ephyviewer_explorer/impedance.py tests/test_impedance.py tests/fixtures/impedance_*.csv tests/fixtures/not_impedance.csv
git commit -m "feat(impedance): discover and parse block impedance CSVs"
```

---

### Task 4: Grid building and the viewer source

Maps channels onto probe contacts and builds the `(n_rows, n_cols)` arrays the viewer renders.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/impedance.py`
- Modify: `src/tdt_ephyviewer_explorer/stores.py:67-73` (the `VALID_VIEWERS` dict)
- Test: `tests/test_impedance.py`
- Test: `tests/test_stores.py`

**Interfaces:**
- Consumes: `Layout`, `probe_layout` (Task 2); `ImpedanceData`, `read_impedance`, `ImpedanceInfo` (Task 3); `ProbeMap`, `load_probe` (existing); `Attachment` from `builders` (existing).
- Produces:
  - `ImpedanceGridSource(name: str, units: str, frequencies: tuple[float | None, ...], grids: tuple[np.ndarray, ...], labels: np.ndarray, metadata: tuple[dict[str, float], ...])` — the ephyviewer-style source object; deliberately has **no** `t_start`.
  - `build_grid_source(data: ImpedanceData, probe: ProbeMap | None, layout: Layout | None) -> ImpedanceGridSource`
  - `build_impedance_source(info: ImpedanceInfo, attachment: Attachment, cfg: Any) -> ImpedanceGridSource`
  - `VALID_VIEWERS["impedance"] == ("impedance",)`

**Mapping rule (the crux of this task):** contact *k* is wired to acquisition channel
`probe.order[k]` (probeinterface's `device_channel_indices`), and the CSV numbers its
channels from 1 — so contact *k*'s value comes from the column named
`R{probe.order[k] + 1}`. With no probe, the grid is a 1×N strip in CSV column order.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_impedance.py` (extend the existing import to add `build_grid_source`,
`build_impedance_source`, and `read_impedance`):

```python
from tdt_ephyviewer_explorer.builders import Attachment
from tdt_ephyviewer_explorer.impedance import build_grid_source, build_impedance_source
from tdt_ephyviewer_explorer.probe import load_probe, probe_layout

PROBE_4CH = FIXTURES / "probe_4ch.json"
PROBE_TOPO = FIXTURES / "probe_topo_4ch.json"


def test_build_grid_source_no_probe_is_a_strip(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    source = build_grid_source(data, probe=None, layout=None)
    assert source.grids[0].shape == (1, 4)
    assert list(source.grids[0][0]) == [10.0, 20.0, 30.0, 40.0]
    assert list(source.labels[0]) == ["R1", "R2", "R3", "R4"]


def test_build_grid_source_maps_via_device_channel_indices(cfg) -> None:
    # probe_4ch.json: device_channel_indices [3,2,1,0], positions a 1x4 column.
    # Contact 0 is wired to acquisition channel 3, i.e. CSV column R4 = 40.0,
    # and sits at row 0 -> the column reads bottom-up relative to the CSV.
    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    source = build_grid_source(data, load_probe(PROBE_4CH), probe_layout(PROBE_4CH))
    assert source.grids[0].shape == (4, 1)
    assert [row[0] for row in source.grids[0]] == [40.0, 30.0, 20.0, 10.0]
    assert [row[0] for row in source.labels] == ["A 00", "B 01", "C 02", "D 03"]


def test_build_grid_source_uses_topo_grid(cfg) -> None:
    # probe_topo_4ch.json: topo (col,row) = (1,0),(0,0),(1,1),(0,1);
    # device_channel_indices [3,2,1,0] -> contacts take R4,R3,R2,R1.
    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    source = build_grid_source(data, load_probe(PROBE_TOPO), probe_layout(PROBE_TOPO))
    assert source.grids[0].shape == (2, 2)
    assert source.grids[0].tolist() == [[30.0, 40.0], [10.0, 20.0]]


def test_build_grid_source_keeps_one_grid_per_frequency(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_2freq.csv", cfg)
    source = build_grid_source(data, probe=None, layout=None)
    assert source.frequencies == (1000.0, 5000.0)
    assert len(source.grids) == 2
    assert list(source.grids[0][0]) == [15.0, 25.0, 35.0, 45.0]
    assert source.metadata[0]["REF (kOhm)"] == 6.0


def test_build_grid_source_count_mismatch_raises(cfg) -> None:
    from tdt_ephyviewer_explorer.probe import Layout

    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    two_contacts = load_probe(FIXTURES / "probe_dup_topo_2ch.json")  # 2 vs 4 channels
    layout = Layout(col=np.zeros(2, dtype=int), row=np.arange(2), n_cols=1, n_rows=2)
    with pytest.raises(ValueError, match="2 contacts but"):
        build_grid_source(data, two_contacts, layout)


def test_build_grid_source_missing_channel_column_raises(cfg, tmp_path) -> None:
    # A probe wired to acquisition channel 9 needs a column R10, which this CSV lacks.
    csv = tmp_path / "gap.csv"
    csv.write_text(
        "TIME (S),R1 (kOhm),R2 (kOhm),R3 (kOhm),R9 (kOhm)\n1,10.0,20.0,30.0,40.0\n"
    )
    data = read_impedance(csv, cfg)
    with pytest.raises(ValueError, match="no column for channel"):
        build_grid_source(data, load_probe(PROBE_4CH), probe_layout(PROBE_4CH))


def test_build_impedance_source_reads_csv_and_applies_probe(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_1row.csv", cfg)
    attachment = Attachment("impedance", probe_path=PROBE_TOPO)
    source = build_impedance_source(info, attachment, cfg)
    assert source.name == "impedance_1row"
    assert source.units == "kOhm"
    assert source.grids[0].shape == (2, 2)


def test_impedance_source_has_no_t_start(cfg) -> None:
    # MainViewer.add_view keys off hasattr(source, 't_start'); impedance is not a
    # signal, so it must not widen the navigation range.
    info = classify_impedance_csv(FIXTURES / "impedance_1row.csv", cfg)
    source = build_impedance_source(info, Attachment("impedance"), cfg)
    assert not hasattr(source, "t_start")
```

Append to `tests/test_stores.py`:

```python
def test_impedance_role_allows_only_the_impedance_viewer() -> None:
    from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

    assert VALID_VIEWERS["impedance"] == ("impedance",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_impedance.py tests/test_stores.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_grid_source'`

- [ ] **Step 3: Add the role entry**

In `src/tdt_ephyviewer_explorer/stores.py`, add to the `VALID_VIEWERS` dict:

```python
    "impedance": ("impedance",),
```

Leave `TDT_TYPE_TO_ROLE` untouched — impedance is never a TDT store type.

- [ ] **Step 4: Implement grid building**

Append to `src/tdt_ephyviewer_explorer/impedance.py`, and extend its imports with:

```python
from tdt_ephyviewer_explorer.probe import Layout, ProbeMap, load_probe, probe_layout
```

Then:

```python
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
    :param labels: ``(n_rows, n_cols)`` object array of per-cell contact labels,
        ``""`` for empty cells.
    :param metadata: Averaged metadata columns, one dict per grid.
    """

    name: str
    units: str
    frequencies: tuple[float | None, ...]
    grids: tuple[np.ndarray, ...]
    labels: np.ndarray
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

    cell_labels = np.full((n_rows, n_cols), "", dtype=object)
    for k in range(len(wanted)):
        cell_labels[row[k], col[k]] = labels[k]
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
        labels=cell_labels,
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
```

`Attachment` must be imported lazily inside `build_impedance_source`'s module scope
without creating a cycle. `builders.py` does not import `impedance.py` at this stage, so a
top-level `from tdt_ephyviewer_explorer.builders import Attachment` is safe — add it to the
imports. (Task 8 makes `builders.py` import the *viewer* module, not this one, so no cycle
appears later either.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_impedance.py tests/test_stores.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/tdt_ephyviewer_explorer/impedance.py src/tdt_ephyviewer_explorer/stores.py tests/test_impedance.py tests/test_stores.py
git commit -m "feat(impedance): map channels onto a probe-topology grid"
```

---

### Task 5: Session persistence

Lets an impedance CSV be saved into and restored from a session YAML.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ImpedanceSource(path: str, name: str, attachments: list[dict])` and
  `Session.impedance: list[ImpedanceSource]`, defaulting to `[]` and tolerated as absent
  in pre-existing session YAMLs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py` (extend the existing import to add `ImpedanceSource`):

```python
def test_session_impedance_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        impedance=[
            ImpedanceSource(
                path="Epi_02_Green/spinal.csv",
                name="spinal",
                attachments=[{
                    "viewer_type": "impedance",
                    "delay_ms": 0.0,
                    "probe_path": "probes/tdt_64ch.json",
                    "params": {"vmax": 300.0},
                }],
            )
        ],
    )
    out = save_session(session, tmp_path, "imp")
    loaded = load_session(out)
    assert loaded == session
    assert isinstance(loaded.impedance[0], ImpedanceSource)


def test_session_defaults_empty_impedance() -> None:
    assert Session(block="b").impedance == []


def test_load_session_without_impedance_key(tmp_path: Path) -> None:
    # Sessions written before this feature have no 'impedance' key and must still load.
    path = tmp_path / "old.yaml"
    path.write_text(
        "block: rRew03-1\n"
        "attachments:\n"
        "  Wav1:\n"
        "  - viewer_type: trace\n"
        "    delay_ms: 0.0\n"
        "    probe_path: null\n"
        "    params: {}\n"
        "processed: []\n"
    )
    loaded = load_session(path)
    assert loaded.impedance == []
    assert loaded.block == "rRew03-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py -v`
Expected: FAIL with `ImportError: cannot import name 'ImpedanceSource'`

- [ ] **Step 3: Implement**

In `src/tdt_ephyviewer_explorer/session.py`, add above `Session`:

```python
@dataclass
class ImpedanceSource:
    """An impedance CSV composed into a session.

    :param path: Stored path (tank-relative when under the tank, else absolute).
    :param name: Display / dock-prefix name.
    :param attachments: Serialized attachment dicts (same shape as TDT attachments).
    """

    path: str
    name: str
    attachments: list[dict] = field(default_factory=list)
```

Add to `Session`:

```python
    impedance: list[ImpedanceSource] = field(default_factory=list)
```

and extend its docstring with
`:param impedance: Impedance CSV sidecars composed into this session.`

In `load_session`, before the `return`:

```python
    impedance = [ImpedanceSource(**i) for i in container.get("impedance", [])]
```

and pass `impedance=impedance` to the `Session(...)` call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/session.py tests/test_session.py
git commit -m "feat(impedance): persist impedance sources in sessions"
```

---

### Task 6: Control Window integration

Surfaces discovered CSVs as parameter-tree groups and round-trips them through a `Session`.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/control_window.py`
- Test: `tests/test_control_window.py`

**Interfaces:**
- Consumes: `ImpedanceInfo`, `scan_impedance`, `classify_impedance_csv` (Tasks 3); `ImpedanceSource` (Task 5); `to_stored_path` (existing, from `processed.py`).
- Produces: `build_impedance_param_spec(infos: list[ImpedanceInfo], viewer_defaults: dict) -> list[dict]`, and `spec_to_session` emitting `Session.impedance` entries.

**Key difference from store/parquet groups:** an impedance group has **no** `reorder`
checkbox, because for this viewer a probe is the layout source rather than an optional
reordering — a non-empty `probe_file` is used directly. `_enabled_attachments` is amended
to honour that while leaving store and parquet behaviour byte-for-byte identical. It also
has no `delay_ms` field; `_enabled_attachments` already defaults that to `0.0`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_control_window.py`:

```python
from pathlib import Path

from tdt_ephyviewer_explorer.control_window import (
    _enabled_attachments,
    build_impedance_param_spec,
    spec_to_session,
)
from tdt_ephyviewer_explorer.impedance import ImpedanceInfo
from tdt_ephyviewer_explorer.session import ImpedanceSource


def _info() -> ImpedanceInfo:
    return ImpedanceInfo(
        path=Path("spinal.csv"), name="spinal", frequencies=(1000.0, 5000.0),
        channel_numbers=(1, 2, 3, 4), units="kOhm",
    )


def test_build_impedance_param_spec_group() -> None:
    spec = build_impedance_param_spec([_info()], {"impedance": {"vmax": 200.0}})
    assert spec[0]["name"] == "spinal"
    children = {c["name"]: c for c in spec[0]["children"]}
    assert children["impedance_path"]["value"] == "spinal.csv"
    assert children["impedance_name"]["value"] == "spinal"
    assert children["channels"]["value"] == 4
    assert children["frequencies"]["value"] == "1000, 5000"
    assert children["probe_file"]["value"] == ""
    assert "reorder" not in children  # probe IS the layout, not an optional reorder
    viewers = children["Viewers"]["children"]
    assert [v["name"] for v in viewers] == ["impedance"]
    assert {c["name"] for c in viewers[0]["children"]} == {"vmax"}


def test_build_impedance_param_spec_reports_no_frequencies() -> None:
    info = ImpedanceInfo(Path("x.csv"), "x", (), (1, 2, 3, 4), "kOhm")
    children = {c["name"]: c for c in build_impedance_param_spec([info], {})[0]["children"]}
    assert children["frequencies"]["value"] == "n/a"


def test_spec_to_session_makes_impedance_source() -> None:
    state = {
        "spinal": {
            "impedance_path": "spinal.csv",
            "impedance_name": "spinal",
            "probe_file": "probes/tdt_64ch.json",
            "Viewers": {"impedance": {"_enabled": True, "vmax": 300.0}},
        }
    }
    session = spec_to_session("blk", state)
    assert session.attachments == {}
    assert session.processed == []
    assert session.impedance == [
        ImpedanceSource(
            path="spinal.csv", name="spinal",
            attachments=[{
                "viewer_type": "impedance", "delay_ms": 0.0,
                "probe_path": "probes/tdt_64ch.json", "params": {"vmax": 300.0},
            }],
        )
    ]


def test_enabled_attachments_uses_probe_without_a_reorder_key() -> None:
    state = {"probe_file": "p.json", "Viewers": {"impedance": {"_enabled": True}}}
    assert _enabled_attachments(state)[0]["probe_path"] == "p.json"


def test_enabled_attachments_still_gates_probe_behind_reorder() -> None:
    # Store and parquet groups keep their explicit opt-in checkbox.
    state = {"probe_file": "p.json", "reorder": False,
             "Viewers": {"trace": {"_enabled": True}}}
    assert _enabled_attachments(state)[0]["probe_path"] is None
    state["reorder"] = True
    assert _enabled_attachments(state)[0]["probe_path"] == "p.json"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_control_window.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_impedance_param_spec'`

- [ ] **Step 3: Add the param spec builder**

In `src/tdt_ephyviewer_explorer/control_window.py`, add after `build_processed_param_spec`:

```python
def build_impedance_param_spec(
    infos: list[ImpedanceInfo], viewer_defaults: dict
) -> list[dict]:
    """Build parametertree groups for impedance CSV sources.

    Each group carries readonly ``impedance_path``/``impedance_name`` so
    :func:`spec_to_session` can round-trip it into a
    :class:`~session.ImpedanceSource`. Unlike store and parquet groups there is no
    ``reorder`` checkbox: here the probe file *is* the grid layout, so a non-empty
    ``probe_file`` is used directly.

    :param infos: Classified impedance CSVs.
    :param viewer_defaults: Per-viewer default params.
    :returns: A list of group-parameter dicts.
    """
    groups: list[dict] = []
    for info in infos:
        frequencies = ", ".join(f"{f:g}" for f in info.frequencies) or "n/a"
        children: list[dict] = [
            {"name": "impedance_path", "type": "str", "value": str(info.path), "readonly": True},
            {"name": "impedance_name", "type": "str", "value": info.name, "readonly": True},
            {"name": "channels", "type": "int", "value": len(info.channel_numbers), "readonly": True},
            {"name": "frequencies", "type": "str", "value": frequencies, "readonly": True},
            {"name": "probe_file", "type": "str", "value": ""},
            {
                "name": "Viewers",
                "type": "group",
                "children": [
                    {
                        "name": "impedance",
                        "type": "bool",
                        "value": False,
                        "children": _params_children(viewer_defaults.get("impedance", {})),
                    }
                ],
            },
        ]
        groups.append({"name": info.name, "type": "group", "children": children})
    return groups
```

Extend the module imports:

```python
from tdt_ephyviewer_explorer.impedance import (
    ImpedanceInfo,
    classify_impedance_csv,
    scan_impedance,
)
from tdt_ephyviewer_explorer.session import (
    ImpedanceSource,
    ProcessedSource,
    Session,
    load_session,
    save_session,
)
```

- [ ] **Step 4: Teach `spec_to_session` and `_enabled_attachments` about impedance**

In `spec_to_session`, add an `impedance` accumulator and branch before the `source_path`
check, so the returned `Session` carries it:

```python
    attachments: dict[str, list[dict]] = {}
    processed: list[ProcessedSource] = []
    impedance: list[ImpedanceSource] = []
    for name, state in param_state.items():
        entries = _enabled_attachments(state)
        if not entries:
            continue
        if "impedance_path" in state:
            impedance.append(
                ImpedanceSource(
                    path=str(state["impedance_path"]),
                    name=str(state.get("impedance_name", name)),
                    attachments=entries,
                )
            )
        elif "source_path" in state:
            # ... the existing ProcessedSource branch, unmodified ...
        else:
            attachments[name] = entries
    return Session(
        block=block, attachments=attachments, processed=processed, impedance=impedance
    )
```

Concretely: the current `if "source_path" in state:` becomes `elif "source_path" in state:`
with its body untouched, the new impedance branch goes above it, and the `return` gains the
`impedance=impedance` keyword. Nothing else in the function changes.

Update its docstring to mention that groups carrying `impedance_path` become
`ImpedanceSource` entries.

In `_enabled_attachments`, replace the probe line:

```python
    probe = state.get("probe_file") or None
    if "reorder" in state and not state["reorder"]:
        probe = None  # store/parquet groups gate the probe behind an explicit checkbox
```

and change the entry dict's probe field to `"probe_path": probe`. Update the docstring to
note that groups without a `reorder` key (impedance) use `probe_file` directly.

- [ ] **Step 5: Wire discovery, the add button, and session restore**

In `set_block`, after the `self._append_processed_groups(block_path)` line, add:

```python
        self._append_impedance_groups(block_path)
```

Add these methods after `_with_stored_paths`:

```python
    def _append_impedance_groups(self, block_path: Path) -> None:
        """Auto-scan the block dir for impedance CSVs and add their groups."""
        infos = scan_impedance(block_path, self._cfg)
        if infos:
            self._root.addChildren(
                build_impedance_param_spec(
                    self._with_stored_impedance(infos), self._viewer_defaults
                )
            )

    def _with_stored_impedance(self, infos: list[ImpedanceInfo]) -> list[ImpedanceInfo]:
        """Return copies of ``infos`` whose ``path`` is the stored (rel/abs) form."""
        from dataclasses import replace

        if self._tank_dir is None:
            return infos
        return [replace(i, path=Path(to_stored_path(i.path, self._tank_dir))) for i in infos]

    def _on_add_impedance(self) -> None:
        """Prompt for impedance CSVs and add them as groups."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add impedance CSV(s)", "", "CSV (*.csv)"
        )
        if paths:
            self.add_impedance_paths([Path(p) for p in paths])

    def add_impedance_paths(self, paths: list[Path]) -> None:
        """Classify each CSV and append it as an impedance group.

        A file that is not an impedance CSV, or that has a valid header but no data
        rows, is reported rather than silently dropped.

        :param paths: CSV file paths (any location).
        """
        infos: list[ImpedanceInfo] = []
        for path in paths:
            info = classify_impedance_csv(path, self._cfg)
            if info is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Not an impedance CSV",
                    f"{path.name} has no R<n> impedance columns, or no data rows.",
                )
                continue
            infos.append(info)
        if infos:
            self._root.addChildren(
                build_impedance_param_spec(
                    self._with_stored_impedance(infos), self._viewer_defaults
                )
            )
```

Add the button in `__init__`, after the "Add processed…" button:

```python
        add_imp_btn = QtWidgets.QPushButton("Add impedance CSV…")
        add_imp_btn.clicked.connect(self._on_add_impedance)
        layout.addWidget(add_imp_btn)
```

In `_apply_session`, rebuild missing impedance groups alongside the processed ones. After
the `if new_infos:` block, add:

```python
        new_impedance = [
            ImpedanceInfo(path=Path(i.path), name=i.name, frequencies=(),
                          channel_numbers=(), units="")
            for i in session.impedance
            if i.name not in existing
        ]
        if new_impedance:
            self._root.addChildren(
                build_impedance_param_spec(new_impedance, self._viewer_defaults)
            )
```

and extend the entries lookup so impedance groups find their attachments:

```python
        by_name_impedance = {i.name: i.attachments for i in session.impedance}
        for store in self._root.children():
            entries = (
                session.attachments.get(store.name(), [])
                or by_name_processed.get(store.name(), [])
                or by_name_impedance.get(store.name(), [])
            )
```

The existing `probe_file` branch already restores the probe path, and the `reorder` branch
is naturally skipped because impedance groups have no such child.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_control_window.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/tdt_ephyviewer_explorer/control_window.py tests/test_control_window.py
git commit -m "feat(impedance): compose impedance CSVs in the control window"
```

---

### Task 7: Launcher planning

Resolves session impedance entries into `ViewPlan`s at launch time.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `ImpedanceInfo`, `classify_impedance_csv`, `build_impedance_source` (Tasks 3–4); `Session.impedance` (Task 5); `from_stored_path` (existing).
- Produces: `plan_views` emitting a `ViewPlan(name=f"{source.name}:impedance", viewer_type="impedance", ...)` per impedance attachment.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_launcher.py`:

```python
def test_plan_views_includes_impedance_sources(tmp_path, monkeypatch) -> None:
    import shutil

    from tdt_ephyviewer_explorer.session import ImpedanceSource

    block = "blk"
    block_dir = tmp_path / block
    block_dir.mkdir()
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copy(fixtures / "impedance_2freq.csv", block_dir / "spinal.csv")

    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block=block,
        impedance=[ImpedanceSource(
            path="blk/spinal.csv", name="spinal",
            attachments=[{"viewer_type": "impedance", "delay_ms": 0.0,
                          "probe_path": None, "params": {"vmax": 300.0}}],
        )],
    )
    plans = plan_views(block_dir, session, load_config())
    assert len(plans) == 1
    assert plans[0].name == "spinal:impedance"
    assert plans[0].viewer_type == "impedance"
    assert plans[0].params["vmax"] == 300.0        # attachment override wins
    assert plans[0].params["cmap"] == "viridis"    # config default still merged in
    assert plans[0].source.frequencies == (1000.0, 5000.0)


def test_plan_views_missing_impedance_file_raises(tmp_path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.session import ImpedanceSource

    block_dir = tmp_path / "blk"
    block_dir.mkdir()
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block="blk",
        impedance=[ImpedanceSource(
            path="blk/gone.csv", name="gone",
            attachments=[{"viewer_type": "impedance", "delay_ms": 0.0,
                          "probe_path": None, "params": {}}],
        )],
    )
    with pytest.raises(FileNotFoundError, match="gone.csv"):
        plan_views(block_dir, session, load_config())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_launcher.py -k impedance -v`
Expected: FAIL. `Session.impedance` already exists (Task 5) but `plan_views` ignores it, so
the first test fails on `assert len(plans) == 1` with `plans == []`, and the second fails
because no `FileNotFoundError` is raised.

- [ ] **Step 3: Implement**

In `src/tdt_ephyviewer_explorer/launcher.py`, extend the imports:

```python
from tdt_ephyviewer_explorer.impedance import (
    ImpedanceInfo,
    build_impedance_source,
    classify_impedance_csv,
)
```

Add after `_processed_info`:

```python
def _impedance_info(source: Any, tank_dir: Path, cfg: DictConfig) -> ImpedanceInfo:
    """Resolve a :class:`~session.ImpedanceSource` to an :class:`~impedance.ImpedanceInfo`.

    :param source: The session's ImpedanceSource.
    :param tank_dir: Tank directory (for relative-path resolution).
    :param cfg: Composed config.
    :raises FileNotFoundError: If the stored CSV no longer exists.
    :raises ValueError: If the file is no longer a readable impedance CSV.
    """
    path = from_stored_path(source.path, tank_dir)
    if not path.exists():
        raise FileNotFoundError(f"impedance source {source.path!r} not found under {tank_dir}")
    info = classify_impedance_csv(path, cfg)
    if info is None:
        raise ValueError(
            f"impedance source {source.path!r} is not a readable impedance CSV "
            "(no R<n> columns, or no data rows)"
        )
    return info
```

In `plan_views`, after the `for ps in session.processed:` loop and before `return plans`:

```python
    for isource in session.impedance:
        info = _impedance_info(isource, tank_dir, cfg)
        for d in isource.attachments:
            attachment = _attachment_from_dict(d)
            source = build_impedance_source(info, attachment, cfg)
            name = f"{isource.name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            plans.append(ViewPlan(name, attachment.viewer_type, params, source))
```

Extend the `plan_views` docstring to mention impedance sources.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/launcher.py tests/test_launcher.py
git commit -m "feat(impedance): plan impedance views at launch"
```

---

### Task 8: The viewer widget, registration, and docs

The Qt half: a pyqtgraph heatmap with a frequency selector, optional per-cell annotations, and a metadata footer.

**Files:**
- Create: `src/tdt_ephyviewer_explorer/viewers/__init__.py`
- Create: `src/tdt_ephyviewer_explorer/viewers/impedance_view.py`
- Modify: `src/tdt_ephyviewer_explorer/builders.py:238-245` (the `_VIEWER_CLASSES` dict)
- Modify: `README.md`
- Modify: `.claude/CLAUDE.md`
- Test: `tests/test_launcher.py` (the existing `qapp`-fixture smoke tests)

**Interfaces:**
- Consumes: `ImpedanceGridSource` (Task 4) — duck-typed, so the viewer module does **not** import `impedance.py` and no cycle can form.
- Produces: `ImpedanceViewer(ViewerBase)` with a `params` group whose child names are exactly `vmin`, `vmax`, `annotate`, `annotation_format`, `cmap`, and `_VIEWER_CLASSES["impedance"]`.

**API notes (verified against the installed versions — pyqtgraph 0.14.0, matplotlib 3.11.1):**
- `pg.colormap.getFromMatplotlib(name)` returns a `pg.ColorMap`.
- `pg.ImageItem.setColorMap(cmap)` exists.
- `pg.ColorBarItem(values=..., colorMap=..., label=..., interactive=False)`, then `.setImageItem(image, insert_in=plot)`.
- `ColorMap.map(x, mode='float')` returns RGBA floats — used to pick legible annotation text colour.
- `ImageItem` treats array axis 0 as **x**, so the `(n_rows, n_cols)` grid is passed transposed.
- `params.sigTreeStateChanged` emits `(param, changes)`, so it must connect to a `*args`-tolerant slot, not directly to `refresh()` (which `ViewerBase.seek` calls with no arguments).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_launcher.py`, next to the other `qapp` smoke tests:

```python
def _grid_source(n_freq: int = 1):
    from tdt_ephyviewer_explorer.impedance import ImpedanceGridSource

    grid = np.array([[10.0, 20.0], [30.0, np.nan]])
    return ImpedanceGridSource(
        name="spinal", units="kOhm",
        frequencies=tuple(1000.0 * (k + 1) for k in range(n_freq)),
        grids=tuple(grid + 100.0 * k for k in range(n_freq)),
        labels=np.array([["A 00", "B 01"], ["C 02", ""]], dtype=object),
        metadata=tuple({"REF (kOhm)": 5.0} for _ in range(n_freq)),
    )


def test_build_viewer_returns_impedance_viewer(qapp) -> None:
    view = build_viewer("impedance", _grid_source(), name="spinal:impedance",
                        params={"vmax": 50.0, "annotate": True})
    assert view.name == "spinal:impedance"
    assert view.params["vmax"] == 50.0
    assert view.combo_freq.count() == 1
    assert view.combo_freq.isHidden()  # single frequency -> selector hidden


def test_impedance_viewer_shows_selector_for_multiple_frequencies(qapp) -> None:
    view = build_viewer("impedance", _grid_source(n_freq=2), name="s:impedance", params={})
    assert view.combo_freq.count() == 2
    assert not view.combo_freq.isHidden()
    view.combo_freq.setCurrentIndex(1)
    assert view.footer.text().startswith("spinal")
    assert "2000 Hz" in view.footer.text()


def test_impedance_viewer_annotates_only_non_nan_cells(qapp) -> None:
    view = build_viewer("impedance", _grid_source(), name="s:impedance",
                        params={"annotate": True, "vmin": 0.0, "vmax": 40.0})
    assert len(view._texts) == 3  # the NaN cell gets no label
    view.params["annotate"] = False
    assert view._texts == []


def test_impedance_viewer_rejects_inverted_levels(qapp) -> None:
    # Set the params with the refresh slot detached, then refresh explicitly: an
    # exception raised inside a Qt slot is not reliably propagated to the caller.
    view = build_viewer("impedance", _grid_source(), name="s:impedance", params={})
    view.params.sigTreeStateChanged.disconnect(view._on_change)
    view.params["vmin"] = 100.0
    view.params["vmax"] = 10.0
    with pytest.raises(ValueError, match="must exceed"):
        view.refresh()


def test_impedance_viewer_seek_is_inert(qapp) -> None:
    # Impedance is not a signal: seeking must not raise and must not change the grid.
    view = build_viewer("impedance", _grid_source(), name="s:impedance", params={})
    before = view.footer.text()
    view.seek(12.5)
    assert view.footer.text() == before
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_launcher.py -k impedance -v`
Expected: FAIL with `KeyError: 'impedance'` from `_VIEWER_CLASSES`

- [ ] **Step 3: Create the viewers package**

Create `src/tdt_ephyviewer_explorer/viewers/__init__.py`:

```python
"""Viewers written for this app, for data ephyviewer has no viewer for."""
```

- [ ] **Step 4: Implement the viewer**

Create `src/tdt_ephyviewer_explorer/viewers/impedance_view.py`:

```python
"""A probe-layout electrode-impedance heatmap viewer."""
from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from ephyviewer.base import ViewerBase
from ephyviewer.myqt import QT


class ImpedanceViewer(ViewerBase):
    """Heatmap of per-contact impedance, laid out in probe topology.

    Impedance is a per-block property rather than a signal, so :meth:`seek` is
    inert and the source exposes no ``t_start`` — which is what keeps
    ``MainViewer`` from widening the navigation range for this dock.

    The source is duck-typed (see :class:`~impedance.ImpedanceGridSource`): it must
    expose ``name``, ``units``, ``frequencies``, ``grids``, ``labels``, and
    ``metadata``.
    """

    _default_params = [
        {"name": "vmin", "type": "float", "value": 0.0},
        {"name": "vmax", "type": "float", "value": 200.0},
        {"name": "annotate", "type": "bool", "value": True},
        {"name": "annotation_format", "type": "str", "value": "{:.0f}"},
        {"name": "cmap", "type": "str", "value": "viridis"},
    ]

    def __init__(self, **kargs: Any) -> None:
        """Build the heatmap, frequency selector, and metadata footer.

        :param kargs: Passed to :class:`~ephyviewer.base.ViewerBase` (``name``,
            ``source``).
        """
        ViewerBase.__init__(self, **kargs)

        self.params = pg.parametertree.Parameter.create(
            name="Global options", type="group", children=self._default_params
        )

        self.mainlayout = QT.QVBoxLayout()
        self.setLayout(self.mainlayout)

        self.combo_freq = QT.QComboBox()
        for frequency in self.source.frequencies:
            self.combo_freq.addItem("all" if frequency is None else f"{frequency:g} Hz")
        self.combo_freq.setVisible(len(self.source.frequencies) > 1)
        self.mainlayout.addWidget(self.combo_freq)

        self.graphicsview = pg.GraphicsView()
        self.mainlayout.addWidget(self.graphicsview)
        self.plot = pg.PlotItem()
        self.plot.hideButtons()
        self.plot.setAspectLocked(True)
        self.plot.invertY(True)  # grid row 0 renders at the top
        self.graphicsview.setCentralItem(self.plot)

        self.image = pg.ImageItem()
        self.plot.addItem(self.image)
        # Give the bar real levels and a colormap up front: it is attached before the
        # first refresh, when the ImageItem still holds no data to derive them from.
        self.colorbar = pg.ColorBarItem(
            values=(float(self.params["vmin"]), float(self.params["vmax"])),
            colorMap=pg.colormap.getFromMatplotlib(str(self.params["cmap"])),
            label=self.source.units,
            interactive=False,
        )
        self.colorbar.setImageItem(self.image, insert_in=self.plot)

        self.footer = QT.QLabel("")
        self.mainlayout.addWidget(self.footer)

        self._texts: list[pg.TextItem] = []
        self.refresh()

        self.params.sigTreeStateChanged.connect(self._on_change)
        self.combo_freq.currentIndexChanged.connect(self._on_change)

    def _on_change(self, *args: Any) -> None:
        """Re-render after a parameter edit or a frequency change.

        Both signals carry arguments that :meth:`refresh` does not take, hence
        this adapter.
        """
        self.refresh()

    def refresh(self) -> None:
        """Redraw the heatmap for the selected frequency and current params.

        :raises ValueError: If ``vmax`` does not exceed ``vmin``, or ``cmap`` is
            not a known matplotlib colormap.
        """
        index = max(self.combo_freq.currentIndex(), 0)
        grid = self.source.grids[index]
        vmin, vmax = float(self.params["vmin"]), float(self.params["vmax"])
        if vmax <= vmin:
            raise ValueError(
                f"impedance viewer vmax ({vmax:g}) must exceed vmin ({vmin:g})"
            )
        colormap = pg.colormap.getFromMatplotlib(str(self.params["cmap"]))
        self.image.setImage(grid.T, levels=(vmin, vmax))  # ImageItem axis 0 is x
        self.image.setColorMap(colormap)
        self.colorbar.setColorMap(colormap)
        self.colorbar.setLevels((vmin, vmax))
        self._refresh_annotations(grid, vmin, vmax, colormap)
        self._refresh_footer(index)
        self.plot.setRange(
            xRange=(0, grid.shape[1]), yRange=(0, grid.shape[0]), padding=0.02
        )

    def _refresh_annotations(
        self, grid: np.ndarray, vmin: float, vmax: float, colormap: Any
    ) -> None:
        """Rebuild the per-cell numeric labels.

        Empty (NaN) cells are skipped. Text is dark on light cells and light on
        dark ones, by Rec. 709 luminance, so it stays legible at both ends of the
        colormap.

        :param grid: The ``(n_rows, n_cols)`` values being displayed.
        :param vmin: Lower colour level.
        :param vmax: Upper colour level.
        :param colormap: The active pyqtgraph colormap.
        """
        for item in self._texts:
            self.plot.removeItem(item)
        self._texts.clear()
        if not self.params["annotate"]:
            return
        template = str(self.params["annotation_format"])
        for row in range(grid.shape[0]):
            for col in range(grid.shape[1]):
                value = grid[row, col]
                if np.isnan(value):
                    continue
                fraction = float(np.clip((value - vmin) / (vmax - vmin), 0.0, 1.0))
                red, green, blue = colormap.map(fraction, mode="float")[:3]
                luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                item = pg.TextItem(
                    template.format(value), color="k" if luminance > 0.5 else "w",
                    anchor=(0.5, 0.5),
                )
                item.setPos(col + 0.5, row + 0.5)
                self.plot.addItem(item)
                self._texts.append(item)

    def _refresh_footer(self, index: int) -> None:
        """Show the source name, frequency, and averaged metadata columns.

        This is where non-channel columns such as ``REF (kOhm)`` surface, since
        they are not grid cells.

        :param index: The selected frequency index.
        """
        parts = [self.source.name]
        frequency = self.source.frequencies[index]
        if frequency is not None:
            parts.append(f"{frequency:g} Hz")
        parts += [
            f"{key}: {value:g}"
            for key, value in sorted(self.source.metadata[index].items())
            if not np.isnan(value)
        ]
        self.footer.setText("   |   ".join(parts))
```

- [ ] **Step 5: Register the viewer**

In `src/tdt_ephyviewer_explorer/builders.py`, add the import:

```python
from tdt_ephyviewer_explorer.viewers.impedance_view import ImpedanceViewer
```

and add to `_VIEWER_CLASSES`:

```python
    "impedance": ImpedanceViewer,
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 8: Update the docs**

In `README.md`, add a section after the existing viewer/composition documentation:

```markdown
### Impedance CSVs

The rig writes an impedance sidecar per electrode array into the block directory (e.g.
`spinal.csv`, `EMG.csv`), with one `R<n> (kOhm)` column per acquisition channel. On block
select these are discovered automatically and appear in the tree as their own groups; use
**Add impedance CSV…** for files kept elsewhere. Files with a valid header but no data rows
are skipped.

Point a group's `probe_file` at a probeinterface JSON to lay the contacts out in probe
topology. The `topo_x`/`topo_y` contact annotations are used when present; otherwise the
grid is inferred from `contact_positions`. Contact *k* takes the CSV column
`R{device_channel_indices[k] + 1}`. Without a probe the contacts render as a single row in
CSV column order. A probe whose contact count differs from the CSV's channel count is an
error, not a silent truncation.

Rows are averaged within each distinct `FREQUENCY (Hz)`; when a file holds several
frequencies the viewer shows a selector to switch between them. Colour limits, the
colormap, and the per-cell numeric annotations are configured under `viewers.impedance`
and editable per attachment in the tree.
```

In `.claude/CLAUDE.md`, under **The pipeline (store → viewer)**, add after the existing
step list:

```markdown
* **Impedance CSVs** (`impedance.py`, Qt-free + `viewers/impedance_view.py`, Qt): a third
  source category beside TDT stores and processed parquets. `scan_impedance` header-sniffs
  the block dir's CSVs, `read_impedance` averages rows within each frequency, and
  `build_grid_source` places channels onto the probe grid from `probe.probe_layout`
  (`topo_x`/`topo_y`, else inferred from `contact_positions`). Not time-synced: the source
  has no `t_start`, which is what keeps `MainViewer` from widening the nav range.
```

Also add `impedance` to the config-group list in the **Config** bullet.

- [ ] **Step 9: Run the full suite one final time**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/tdt_ephyviewer_explorer/viewers src/tdt_ephyviewer_explorer/builders.py tests/test_launcher.py README.md .claude/CLAUDE.md
git commit -m "feat(impedance): heatmap viewer with frequency selector and annotations"
```

---

## Manual verification

After Task 8, confirm against real data (this is the only step that touches the rig files, and it only reads them):

```bash
uv run tdt-explore --tank "/c/TDT/Synapse/Tanks/Rodent_123P_bipolar_64ch-260727-151729" --block "Epi_02_Green-260727-151729"
```

Expected:
1. `spinal` appears as a tree group; `EMG` does **not** (header-only file).
2. Setting `spinal`'s `probe_file` to `/c/Users/MBO/.torpedo/probe_maps/tdt_64ch.json`, ticking `impedance`, and launching yields an 8×8 heatmap.
3. The two right-hand columns read ~545 kΩ and saturate at the top of the colour scale; the rest sit around 50–100 kΩ.
4. The frequency selector is hidden (the file has a single 1000 Hz row) and the footer reads `spinal   |   1000 Hz   |   TARGET (uA): 5   |   TIME (S): 4` — every numeric non-channel column, sorted by name.
5. Toggling `annotate` off and on removes and restores the numbers; raising `vmax` to 600 redistributes the colours.
