# Impedance viewer — design

**Date:** 2026-07-30
**Status:** approved, ready for implementation planning

## Purpose

Electrode impedance is measured per block and written by the rig as a sidecar CSV in the
block directory (`spinal.csv`, `EMG.csv`). Today it is invisible to `tdt-explore`. This
feature adds an impedance heatmap viewer: one cell per electrode contact, laid out in probe
topology, colored by impedance, so a bad shank or a broken contact is obvious at a glance
next to the traces it contaminates.

The viewer does not exist in `ephyviewer`, so it is written here.

## Scope

In scope:

- Auto-discovery of impedance CSVs in the block directory, by header shape.
- Per-frequency row averaging; a frequency selector inside the viewer.
- Probe-driven 2D layout via `topo_x`/`topo_y`, with inference from `contact_positions`.
- A heatmap viewer with configurable `vmin`/`vmax`, colormap, and optional per-cell numeric
  annotations.
- Session persistence and round-trip, alongside TDT stores and processed parquets.

Out of scope:

- An `auto_range` toggle (explicitly deferred; `vmin`/`vmax` are editable per attachment in
  the Control Window tree, which covers the immediate need).
- Time-synchronized behavior. Impedance is a per-block property, not a signal.
- Writing to or editing impedance CSVs. Raw block dirs stay read-only, as everywhere else
  except `tdt-metadata`'s `analysis_notes.txt`.
- Comparing impedance across blocks or across time.
- Clicking a cell to select or highlight the corresponding channel in other viewers.

## Reference data

`/c/TDT/Synapse/Tanks/Rodent_123P_bipolar_64ch-260727-151729/Epi_02_Green-260727-151729/`

- `spinal.csv` — header `TIME (S), FREQUENCY (Hz), TARGET (uA), R1 (kOhm) … R64 (kOhm)`,
  one data row. Values ~46–103 kΩ with a cluster of ~545 kΩ contacts.
- `EMG.csv` — header `TIME (S), FREQUENCY (Hz), R1 (kOhm) … R16 (kOhm), REF (kOhm)`, and
  **zero data rows**. The empty-file path is therefore a real case, not a hypothetical.

Probe: `/c/Users/MBO/.torpedo/probe_maps/tdt_64ch.json` — 64 contacts,
`device_channel_indices` identity, `contact_annotations` carrying `topo_x`/`topo_y` that
form a complete 8×8 grid. Mapping `spinal.csv` through it in CSV order yields a spatially
coherent picture (the two right-hand topo columns are uniformly ~545 kΩ), which confirms
the layout convention.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Discovery | Auto-scan block dir + header sniff | Both CSVs appear without user action; mirrors `processed.auto_scan`. A manual add button covers files elsewhere |
| Channel → contact | `R<n>` is acquisition channel *n* (1-based) | Matches the existing timeseries reorder path; correct for remapped probes. Identity for `tdt_64ch.json`, so indistinguishable there, but not in general |
| Viewer home | This repo, not the ephyviewer fork | No cross-repo commit and dependency-revision bump; the logic is TDT-CSV-specific rather than generic ephys |
| Multi-row files | Group by frequency, average within group | A frequency sweep must not be blended into one meaningless mean |
| Multi-frequency UI | One dock, combo box inside it | Leaves the session/attachment model (keyed by viewer type) untouched; avoids dock clutter |
| Session model | New `Session.impedance` list | `processed.py` is parquet-specific (pyarrow contracts, sampling rates); branching it on CSVs would blur its purpose |
| Row 0 orientation | Top | Matches the numpy grid convention; requires explicitly inverting the pyqtgraph y axis |
| Out-of-range values | Clamp to end colors | The ~545 kΩ contacts would otherwise crush the scale for the ~50–100 kΩ majority |
| Cell/probe count mismatch | `ValueError` | Consistent with `reorder_channels`; no silent truncation |
| Empty CSV | Skipped by scan, message box on manual add | No silent failures, but a header-only file must not break block selection |

## Architecture

A Qt-free core that parses and computes, and a thin Qt viewer — the split the app already
uses everywhere.

### Module tree

```
src/tdt_ephyviewer_explorer/
  impedance.py                   # NEW  Qt-free: discovery, parse, average, grid build
  viewers/__init__.py            # NEW
  viewers/impedance_view.py      # NEW  Qt: ImpedanceViewer(ViewerBase)
  probe.py                       # MODIFIED: + topo_layout()
  builders.py                    # MODIFIED: + build_impedance_source(); register viewer class
  stores.py                      # MODIFIED: + VALID_VIEWERS["impedance"]
  session.py                     # MODIFIED: + ImpedanceSource, Session.impedance
  control_window.py              # MODIFIED: + impedance param groups, scan hook, round-trip
  launcher.py                    # MODIFIED: + impedance branch in plan_views()
  config/
    config.yaml                  # MODIFIED: compose the impedance group
    impedance/default.yaml       # NEW  discovery settings
    viewer/default.yaml          # MODIFIED: + viewers.impedance defaults
```

### Data flow

```
scan_impedance(block, cfg)  ->  list[ImpedanceInfo]        (header-only, eager)
        |
        v
build_impedance_param_spec  ->  Control Window tree group  (one per CSV)
        |
        v
spec_to_session             ->  Session.impedance          (persisted YAML)
        |
        v
plan_views                  ->  build_impedance_source()   (reads the CSV, Qt-free)
        |
        v
build_viewer("impedance")   ->  ImpedanceViewer docked in MainViewer
```

## Components

### `impedance.py` (Qt-free)

```python
@dataclass(frozen=True)
class ImpedanceInfo:
    path: Path
    name: str                    # file stem, the dock-name prefix
    frequencies: tuple[float, ...]
    channel_numbers: tuple[int, ...]   # the n of each R<n> column, in file order
    units: str                         # regex capture, e.g. "kOhm"
```

- `classify_impedance_csv(path, cfg) -> ImpedanceInfo | None` — a file qualifies when at
  least `cfg.impedance.min_channels` header columns match `cfg.impedance.channel_regex`.
  Columns that do not match are metadata. Returns `None` for non-impedance CSVs and for
  files with zero data rows. Populating `frequencies` requires reading the frequency
  column, so this is a full read rather than a header-only one — but these sidecars are a
  handful of rows, so the cost is negligible and the eager block-select path stays fast.
  (Contrast `.tsq` headers and `eS1p`, which are genuinely expensive and stay lazy.)
- `scan_impedance(block_path, cfg) -> list[ImpedanceInfo]` — globs `cfg.impedance.globs`
  in the block directory and classifies each hit, sorted by name. Skipped files are logged,
  never silent.
- `read_impedance(path, cfg) -> ImpedanceData` — the launch-time read. Groups rows by
  `cfg.impedance.frequency_column` and column-wise averages within each group. Absent
  frequency column means a single group. Carries per-group averaged metadata columns
  (`TARGET (uA)`, `REF (kOhm)`, …) for the viewer footer.
- `build_grid(values, layout) -> np.ndarray` — places values into a `(n_rows, n_cols)`
  float array filled with NaN. NaN cells render transparent.

### `probe.py` — `topo_layout`

```python
@dataclass(frozen=True)
class Layout:
    col: np.ndarray    # per contact
    row: np.ndarray    # per contact
    n_cols: int
    n_rows: int
```

`topo_layout(probe) -> Layout` uses `contact_annotations["topo_x"]`/`["topo_y"]` when both
are present. Otherwise it infers: rank the unique `contact_positions` x values ascending to
get columns, unique y values to get rows. For `tests/fixtures/probe_4ch.json` (all x = 0,
y = 0/100/200/300) that yields a 4×1 strip.

Two contacts resolving to the same cell raises `ValueError` naming both contact ids. Silent
overwrite would hide a real probe-file error.

The grid is filled using the acquisition-channel convention: the cell for contact *k* takes
the value from the CSV column named `R{device_channel_indices[k] + 1}` — that is, contact
*k* is wired to acquisition channel `device_channel_indices[k]`, and the CSV numbers its
channels from 1.

With no probe file the layout is a 1×N strip in CSV column order. If a probe *is* given and
its contact count differs from the CSV channel count, `build_impedance_source` raises
`ValueError` — so `EMG.csv` (16 channels) is used either with no probe or with a 16-channel
probe, never with `tdt_64ch.json`.

### `viewers/impedance_view.py` — `ImpedanceViewer(ViewerBase)`

A pyqtgraph `ImageItem` plus a `ColorBarItem`. `refresh()` redraws from the current params
and selected frequency; `seek()` is inherited and inert, since impedance is not a signal.

The source deliberately exposes **no** `t_start`, so `MainViewer.add_view` leaves the
navigation range alone — the same guard that already accommodates `DataFrameView`.

- A `QComboBox` above the plot selects frequency, **hidden** when the file has only one.
- A footer `QLabel` shows the frequency, `TARGET (uA)`, and any remaining numeric metadata
  columns. This is where `REF (kOhm)` surfaces, since it is not a grid cell.
- Annotations are per-cell `TextItem`s, created once and toggled by the `annotate` param.
  Text is black or white per cell luminance, so it stays legible at both ends of the
  colormap.
- The y axis is inverted so `topo_y = 0` renders at the top.
- `self.params` is a pyqtgraph `Parameter` group whose child names match the config keys, so
  the existing `build_viewer` (`view.params[key] = value`) and the Control Window's
  per-viewer param children work unchanged, and edits re-render live via
  `sigTreeStateChanged`.

`startup.trace_color_scheme` skips this viewer automatically: `_apply_trace_color_scheme`
returns early when a viewer has no `params_controller.combo_cmap`. No launcher change needed
for that path.

### Session

```python
@dataclass
class ImpedanceSource:
    path: str          # stored form: tank-relative when under the tank, else absolute
    name: str
    attachments: list[dict]
```

`Session` gains `impedance: list[ImpedanceSource]`. `load_session` reads the key with a `[]`
default, so session YAMLs written before this feature still load.

Path storage reuses `to_stored_path`/`from_stored_path` from `processed.py`.

### Control Window

`build_impedance_param_spec(infos, viewer_defaults)` emits one group per CSV with readonly
`impedance_path`, `impedance_name`, and `frequencies`, plus an editable `probe_file` and a
`Viewers` subgroup containing the single `impedance` entry.

Impedance groups carry **no** `reorder` checkbox — for this viewer a probe is the layout
source, not an optional reordering, so a non-empty `probe_file` is used directly.
`_enabled_attachments` is amended to: take `probe_file` when non-empty, and suppress it only
when a `reorder` key is present and false. This preserves existing store/parquet behavior
exactly while giving impedance groups the simpler semantics.

`delay_ms` is omitted from impedance groups; `_enabled_attachments` already defaults it
to `0.0`.

### Launcher

`plan_views` gains a loop over `session.impedance` mirroring the processed-parquet loop:
resolve the stored path (`FileNotFoundError` if the CSV is gone), re-classify it, build the
source, and emit a `ViewPlan` named `f"{name}:impedance"`.

## Configuration

```yaml
# config/impedance/default.yaml
# @package _global_
impedance:
  auto_scan: true
  globs: ["*.csv"]                      # block-dir glob; non-impedance CSVs fail the sniff
  channel_regex: '^R(\d+)\s*\((\w+)\)$' # capture 1 = channel number, capture 2 = units
  frequency_column: "FREQUENCY (Hz)"    # absent -> a single frequency group
  min_channels: 4                       # header-sniff threshold
```

```yaml
# config/viewer/default.yaml (added)
viewers:
  impedance:
    vmin: 0.0
    vmax: 200.0
    annotate: true
    annotation_format: "{:.0f}"
    cmap: viridis
```

`config.yaml` composes the new `impedance` group.

## Error handling

| Condition | Behavior |
|---|---|
| CSV header has no `R<n>` columns | Not an impedance file; skipped by the scan |
| CSV has a valid header but zero data rows | Skipped by the scan (logged); message box on manual add |
| Probe contact count ≠ CSV channel count | `ValueError` from `build_impedance_source` |
| Two contacts map to the same grid cell | `ValueError` naming both contact ids |
| Session references a CSV that no longer exists | `FileNotFoundError` from `plan_views` |
| A channel column is non-numeric or blank | Parsed as NaN; the cell renders transparent |
| Value outside `[vmin, vmax]` | Clamped to the end color, not dropped |

## Testing

`tests/test_impedance.py`, Qt-free like the rest of the suite:

- header sniffing accepts `spinal.csv`/`EMG.csv` shapes and rejects an unrelated CSV
- metadata columns are separated from channel columns, including `REF (kOhm)`
- per-frequency grouping and averaging, including the single-group (no frequency column) case
- the `device_channel_indices` mapping, using `probe_4ch.json`'s non-identity `[3, 2, 1, 0]`
- topo grid construction from `topo_x`/`topo_y`
- layout inference from `contact_positions` when topo fields are absent
- the no-probe 1×N strip
- the count-mismatch `ValueError`
- the duplicate-cell `ValueError`
- the header-only file is skipped by the scan

New fixtures: a two-frequency CSV, a single-row CSV, a header-only CSV, an unrelated CSV,
and `probe_topo_4ch.json`. The existing `probe_4ch.json` already has non-identity
`device_channel_indices` and no topo fields, so it exercises both the mapping and the
inference fallback unchanged.

Extensions: `test_probe.py` (`topo_layout`), `test_session.py` (`ImpedanceSource` round-trip
and the backward-compatible default), `test_control_window.py`
(`build_impedance_param_spec`, `spec_to_session` producing an `ImpedanceSource`),
`test_launcher.py` (an impedance `ViewPlan` and the missing-file error).

The Qt viewer class itself is not unit-tested, matching current practice — the suite tests
pure functions and never instantiates widgets.

## Documentation

`README.md` gains a short impedance section; `.claude/CLAUDE.md`'s codebase map gains
`impedance.py` and `viewers/` to the pipeline description.
