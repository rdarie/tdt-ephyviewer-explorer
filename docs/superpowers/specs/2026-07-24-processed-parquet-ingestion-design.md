# Design — ingest tss-pipeline processed parquets into tdt-explore

**Date:** 2026-07-24
**Status:** design, ready for implementation planning
**Companion:** producer contract shipped in tss-pipeline (`feat/tdt-explore-contract`,
`contract_version` 1). Writer brief: `docs/notes/2026-07-23-tss-pipeline-metadata-contract-brief.md`.

## 1. Goal

Let tdt-explore ingest tss-pipeline preprocessed parquets — **timeseries** and **event**
streams — alongside the raw TDT stores it already handles, via (a) auto-discovery of a block's
`torpedo/preprocessed/<block>/` directory and (b) a manual "Add processed…" button for
arbitrary files. Parquets are self-describing through an embedded `tdt_explore` JSON contract;
untagged/external files fall back to structural heuristics.

## 2. The shipped contract (authoritative facts the reader depends on)

Embedded in parquet **schema metadata** under key `b"tdt_explore"`, UTF-8 JSON.

**Common:** `contract_version` (int, =1), `kind` (`"timeseries" | "event"`), `data_source`
(optional).

**`kind == "timeseries"`** — always carries: `sampling_rate` (float Hz, effective),
`t_start` (float seconds, block-relative time of sample 0), `channel_names`
(`list[str]` = the DataFrame columns), optional `units` (e.g. `"uV"`). Index is `RangeIndex`
0..N-1 (sample number). Includes multi-channel **boolean** series (`stim_synch` → 3 cols
`pulse`/`blanking`/`manual_blanking`; `*_blank_mask` → one bool col per site).

**`kind == "event"`** — `time_column` (=`"timestamp_sample"`), `time_units` (=`"samples"`;
absent-default `"seconds"`), `sampling_rate` (required when samples), `label_column`
(=`"stim_site"`), optional `schema` (=`"iz_param_names"`). One row per event.

**Observed values** (full example session, 2026-07-24): `t_start == 0.0` and
`sampling_rate == 24414.0625` for all tagged files (no decimation, `stream_delay == 0`);
the reader nonetheless reads the fields rather than assuming. Untagged on purpose: OpenEphys
raw, window-info/epoch tables, MultiIndex feature tables, spikes/spectral/kinematics.

## 3. Architecture

Preserve the existing Qt-free core / two-window split. Add one Qt-free module and extend the
data model; **reuse the TDT builders** where the duck-typed interface already matches.

```
src/tdt_ephyviewer_explorer/
  processed.py        # NEW — Qt-free: contract read, classification, discovery, load, adapters
  stores.py           # (unchanged) role/viewer maps reused for processed kinds
  builders.py         # small additive extensions (channel names; frame-based event builder)
  session.py          # + ProcessedSource, Session.processed list
  launcher.py         # plan_views also realizes processed sources
  control_window.py   # auto-scan on block select; single "Add processed…" button
  config/processed/default.yaml   # NEW config group
```

### 3.1 `processed.py` (new, Qt-free, mirrors tank.py/stores.py)

- `read_contract(path: Path) -> dict | None` — read `b"tdt_explore"` from parquet schema
  metadata (via pyarrow, header-only), parse JSON; `None` if absent/invalid.
- `ProcessedInfo` dataclass — `path`, `kind`, `role`, `name` (default = file stem), plus
  resolved contract fields (`sampling_rate`, `t_start`, `channel_names`, `time_column`,
  `time_units`, `label_column`, `schema`, `units`). Analogous to `StoreInfo`/`ResolvedStore`.
- `classify(path, cfg) -> ProcessedInfo | None` — **blob first** (contract → fully specified);
  else **heuristic fallback** (see 3.2); `None` = skip. Reads only parquet schema + pandas/
  contract metadata (no bulk load), mirroring the header-only TDT scan.
- `scan_preprocessed(tank_dir, block, cfg) -> list[ProcessedInfo]` — resolve
  `tank_dir / cfg.processed.preprocessed_subpath / block`, glob `*.parquet`, `classify` each,
  drop `None`, apply `ignore_globs`, sort. **Auto-scan is blob-only by default** (the producer
  tags everything we want; untagged files are exactly what we skip). Heuristics apply only via
  the manual Add path.
- `load_processed(info) -> ProcessedStore` — read the DataFrame once; return a small adapter
  (see 3.3).
- Role mapping: `kind == "timeseries"` → role `timeseries`; `kind == "event"` → role `event`.
  Reuse `VALID_VIEWERS` (`timeseries` → trace/timefreq/spectrogram; `event` → eventlist/
  spiketrain). No new roles.

### 3.2 Heuristic fallback (untagged/external files only)

- **event**: a recognized seconds time-column present (`cfg.processed.time_column_candidates`,
  default `["timestamp"]`) → event, `time_units="seconds"`, label from
  `cfg.processed.default_label_column` if present.
- **timeseries**: all-numeric (incl. bool) columns + plain `RangeIndex` → timeseries; rate from
  `attrs['sampling_rate']` if present, else prompt (manual Add) or skip (auto-scan, though
  auto-scan is blob-only so this is a manual-path concern).
- **skip**: MultiIndex index/columns (feature tables); nothing matches.

### 3.3 Loading & source building

Reuse builders via thin adapters + one new builder:

- **Timeseries** → reuse `build_analog_source`. Adapter presents `.data` (n_channels ×
  n_samples = `df.to_numpy().T`, boolean cast to float), `.fs = sampling_rate`,
  `.start_time = t_start`. **Builder extension:** `build_analog_source` currently names channels
  `ch{k}` unless a probe is given; extend it to accept source-provided `channel_names` so the
  parquet columns (`"0"…`, `"Voice A - 01"`, `"pulse"/"blanking"/…`) are used. Probe reorder
  stays optional and timeseries-only, as today.
- **Event** → **new** `build_event_source_from_frame(df, info, attachment)`:
  `ts = df[time_column].to_numpy(float64); if time_units == "samples": ts /= sampling_rate`,
  then `ts += delay_ms/1000`; labels from `df[label_column]` (precedence) else the
  `schema`+formatter path (reuse `GenericFormatter`/configured formatter over schema columns)
  else generic. Returns an `InMemoryEventSource`. (Event parquets are mixed-dtype tables, so the
  numeric `scalar_rows` path is not reused.)
- `delay_ms` alignment (`apply_delay`) applies uniformly, as for TDT stores.

## 4. Data model — `Session` gains `processed`

TDT `attachments` unchanged (existing sessions keep loading). Add a parallel list:

```python
@dataclass
class ProcessedSource:
    path: str            # tank-relative when under tank, else absolute (portability)
    kind: str            # "timeseries" | "event"
    name: str            # display / dock prefix; default = file stem
    attachments: list[dict]     # same shape as TDT attachments (viewer_type, delay_ms, probe_path, params)
    # captured only when a blob-less file was resolved manually:
    sampling_rate: float | None = None
    t_start: float | None = None
    time_column: str | None = None
    time_units: str | None = None
    label_column: str | None = None

@dataclass
class Session:
    block: str
    attachments: dict[str, list[dict]] = field(default_factory=dict)
    processed: list[ProcessedSource] = field(default_factory=list)   # NEW
```

`plan_views` (Qt-free) realizes TDT stores as today, then loads each `ProcessedSource` once and
builds one source per attachment; view names `f"{name}:{viewer_type}"`. Path resolution:
tank-relative paths resolved against `tank_dir`; absolute used as-is.

**Path storage rule:** if the file is under `tank_dir`, store `path` relative to `tank_dir`
(portable); else store absolute. No hardcoded paths.

## 5. GUI (`control_window.py`)

- **Auto-scan on block select:** `set_block` also calls `scan_preprocessed`; results appear as
  groups under a top-level **"Processed"** section in the tree, each carrying readonly
  `source_path` + `kind` params so `spec_to_session` round-trips them into `ProcessedSource`.
  `build_param_tree_spec` is reused by adapting `ProcessedInfo` into the same group shape (role,
  fs, channels, delay_ms, optional probe, Viewers subgroup). Feature/unclassifiable files are
  skipped; a count is logged. Config toggle `processed.auto_scan` (default true) short-circuits
  the scan for tanks without a preprocessed tree.
- **Single "Add processed…" button** at the bottom: multi-select file dialog → `classify` each
  chosen file → add to the "Processed" section. If a file lacks the blob **and** can't be
  inferred (e.g. timeseries with no discoverable rate), a small dialog prompts for the missing
  `kind`/`sampling_rate`/`t_start`; the entered values populate the `ProcessedSource` override
  fields so the session round-trips without re-prompting.
- `spec_to_session` distinguishes processed groups (presence of `source_path`) from TDT store
  groups and emits `Session.processed`. `_apply_session` restores processed groups from a loaded
  session (re-classifying by stored path, applying overrides).

## 6. Config — `config/processed/default.yaml` (`# @package _global_`)

```yaml
processed:
  preprocessed_subpath: torpedo/preprocessed
  auto_scan: true
  default_sampling_rate: 24414.0625     # fallback for blob-less manual-add timeseries
  time_column_candidates: ["timestamp"] # heuristic event detection
  default_label_column: stim_site
  ignore_globs: []                      # untagged files to skip in the (blob-only) scan; reserved
```

Add `processed` to the `defaults` list in `config.yaml`. No magic numbers in code.

## 7. Dependencies

Add **`pyarrow`** to `pyproject.toml` (`pandas` already present) — required to read schema-
metadata blobs and for the parquet engine.

## 8. Testing (mirror `tests/test_processed.py`, Qt-free & headless)

Generate fixture parquets in-test (write a DataFrame, embed a `tdt_explore` blob with pyarrow;
also blob-less variants). Cover:
- `read_contract` (present / absent / malformed).
- `classify`: blob timeseries, blob event, heuristic event (`timestamp` col), heuristic
  timeseries (numeric + RangeIndex), skip (MultiIndex), `ignore_globs`.
- `scan_preprocessed` on a temp tree (blob-only default; count of skipped).
- Source building: multi-channel float + **boolean** timeseries (channel names honored);
  event via frame builder with `time_units="samples"` → seconds (float64), label precedence
  (`label_column` vs `schema`+formatter), `delay_ms` shift.
- Path rule (relative-under-tank vs absolute); `Session` round-trip with `processed`;
  `plan_views` mixing TDT + processed sources.
- Optional real-data smoke (env-gated like the existing `tdt` test): point at blocks
  `rRew03-260626-131130` / `-131254` for the `raw_data_mep` (uV) timeseries; the nominal
  example block `rRew03-260626-130955` has events/`stim_synch` but no `raw_data_mep`.

## 9. Decisions baked in

- **All-in on the contract**, heuristics as fallback only; **auto-scan is blob-only**.
- **Event label precedence:** `label_column` → `schema`+formatter → generic.
- **Time:** events convert `timestamp_sample / sampling_rate` in float64; timeseries axis is
  `index / sampling_rate` offset by `t_start`.
- **Session** back-compat preserved (new `processed` list; TDT path untouched).
- **Path portability:** relative-under-tank else absolute.

## 10. Open items (confirm at review)

- Whether to surface a per-channel subset selector for wide timeseries now or defer (default:
  defer; show all channels, reuse existing probe reorder only).
- Whether the "Processed" tree section should visually separate discovered vs manually-added
  sources (default: one section, order = discovered then added).
```
