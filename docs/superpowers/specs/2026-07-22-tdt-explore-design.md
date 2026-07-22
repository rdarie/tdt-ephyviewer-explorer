# tdt-explore — Design Spec

**Date:** 2026-07-22
**Status:** Approved for planning
**Entry point:** `tdt-explore`

## 1. Purpose

A modular desktop app for quickly exploring **raw** TDT (Synapse) recordings with the
[`ephyviewer`](https://github.com/rdarie/ephyviewer) fork. The user points the app at a
tank, picks a block, composes exactly the viewers they want from that block's data
structures, and launches a synchronized display window. Composition is driven by
pyqtgraph parameter trees seeded from Hydra config presets.

### Goals

- Two-part GUI: one **Control Window** per tank; one **Block Window** per opened block.
- Modular composition: attach one or more ephyviewer viewers to each data store.
- Config-driven defaults (viewer params, store roles, schemas, stim formatters) via Hydra.
- Handle real-world alignment concerns: per-store **delays** (in ms), probe-native channel
  **reordering**, and stim-metadata → event-**label** formatting.
- Lazy loading so multi-GB blocks list instantly and load only what is viewed.
- Per-tank session persistence without polluting raw data directories.

### Non-goals (v1)

- No preprocessing / `.parquet` derivatives (raw data only).
- No writing back to Hydra preset YAMLs from the GUI (presets are read-only).
- No persistence of live ephyviewer window state (geometry, zoom, colors) — deferred.
- No special ingestion of `MonA` (stim current monitor) or `eS1r` — treated generically,
  awaiting channel-mapping notes.
- No in-GUI column renaming — schemas come from config only.

## 2. Architecture

**Single process, single `QApplication`.** `tdt-explore` boots one Qt event loop hosting:

- **one Control Window** (per tank): a `pyqtgraph.parametertree.ParameterTree` plus
  tank/block pickers and Launch / Save session / Load session actions.
- **N Block Windows**: each an `ephyviewer.MainViewer` for one block, with its composed
  viewers docked/tabified and sharing one navigation timebase.

*Alternative considered:* launching each Block Window as a subprocess for crash isolation.
Rejected — overkill for a small-lab tool, and it forces data reloads and IPC. Single-process
keeps shared state and the Qt event loop simple.

### Data flow

```
tank dir ──scan──> [blocks]
   select block ──header scan (tdt.read_block headers=1)──> [StoreInfo...]
      apply store-roles config ──> per-store role + valid viewer types
         user composes in ParameterTree (viewers, delays, probe, schema)
            Launch ──> lazy-load each attached store ──> build Source+Viewer
               ──> dock into a new MainViewer
```

## 3. Module tree

```
src/tdt_ephyviewer_explorer/
  __init__.py
  app.py                 # tdt-explore entry point; QApplication + ControlWindow bootstrap
  tank.py                # tank/block discovery; header scan -> StoreInfo list
  stores.py              # StoreInfo dataclass; store-role resolution; lazy per-store loader
  probe.py               # probeinterface load -> (permutation indices, channel names)
  builders.py            # (role, viewer_type) -> ephyviewer Viewer factory; applies delay+probe
  control_window.py      # ParameterTree UI: block/store groups; launch/save/load actions
  session.py             # Session dataclass; save/load <tank>/tdt_explore/sessions/*.yaml
  config_schema.py       # OmegaConf structured-config dataclasses + Hydra compose helper
  formatters/
    __init__.py
    base.py              # StimFormatter protocol + GenericFormatter (name: value per column)
    iz_voice.py          # IZVoiceFormatter (chan_formatter port); instantiated via _target_
  config/                # packaged Hydra presets (committed)
    config.yaml          # top-level defaults + defaults list
    viewer/
      trace.yaml
      timefreq.yaml
      spectrogram.yaml
      eventlist.yaml
      spiketrain.yaml
      epoch.yaml
    roles/
      default.yaml       # store-name patterns -> role + schema + preferred viewers
    schema/
      iz_param_names.yaml
tests/
  test_stores.py
  test_probe.py
  test_formatters.py
  test_builders.py
  test_session.py
  test_config.py
  test_integration_tdt.py  # skipped unless TDT_EXPLORE_TEST_BLOCK is set
```

## 4. Data layer

### 4.1 Header scan

`tank.scan_block(block_path) -> list[StoreInfo]` uses `tdt.read_block(block_path, headers=1)`,
reading `hdr["stores"]` with **no bulk data**. Each store yields:

```python
@dataclass(frozen=True)
class StoreInfo:
    name: str                 # e.g. "Wav1"
    tdt_type: str             # tdt type_str: streams | scalars | epocs | snips
    fs: float | None          # sample rate (streams/snips)
    n_channels: int | None    # channel count where known
    n_samples: int | None     # sample count where known
    t_start: float            # store start time (s)
    duration: float | None    # seconds, where derivable
```

### 4.2 Store roles

Raw tdt type is a starting point, not the final word. `stores.resolve_role(info, roles_cfg)`
maps a store to a **semantic role** via name-pattern rules from the roles config, falling
back to the tdt type. Roles and their valid viewer types:

| Role         | Valid viewers                              | Notes |
|--------------|--------------------------------------------|-------|
| `timeseries` | TraceViewer, TimeFreqViewer, SpectrogramViewer | probe-aware; delay-aware |
| `stim`       | EventList, SpikeTrainViewer                | schema + formatter applied |
| `event`      | EventList, SpikeTrainViewer                | generic; schema optional |
| `epoch`      | EpochViewer, SpikeTrainViewer              | onset/offset (SpikeTrainViewer uses onsets); EventList dropped in v1 (needs scalar schema) |
| `snip`       | SpikeTrainViewer                           | raster by chan/sortcode; waveform overlay deferred |

Observed mapping for the reference block (`rRew03-260626-131743`):
`Wav1/SU_1 → timeseries`, `MonA → timeseries` (generic; special handling deferred),
`eS1p → stim`, `eS1r → event` (generic; deferred), `UDP1 → event` (unknown columns),
`StS1 → event`, `Tick → epoch`.

> **Resolved (2026-07-22):** tdt tags `StS1` as `scalars`; loading it from the real block
> showed 1-D `data`, `ts`, a single `chan` value, and `sortcode=None` — a scalar/event
> store, not a snip. It is classified as `event`. The `snip` role and spike builder remain
> for genuine snip stores.

### 4.3 Lazy loading

Stores load only on **Launch**. `stores.load_store(block_path, name) ->` raw tdt store,
via `tdt.read_block(block_path, store=[name])`. One store per attached viewer group;
nothing bulk loads during browsing/composition.

## 5. Config layer (Hydra)

Structured configs via OmegaConf dataclasses in `config_schema.py`; presets are read-only
YAML under the packaged `config/` dir. Config groups:

- `viewer/*` — default params per viewer type, keyed by ephyviewer's own param names
  (e.g. `scale_mode`, `display_labels`, `antialias`).
- `roles/*` — ordered list of `{pattern, role, schema, viewers}` rules.
- `schema/*` — column-name lists for scalar/event stores (e.g. `iz_param_names`).

A selected preset **seeds** the parameter tree. The GUI never writes back to these files.
No hardcoded hyperparameters: all viewer defaults, patterns, and schemas live in config.

## 6. Control Window

`ParameterTree` layout:

- **Global group:** preset selector; tank dir (readonly); block selector.
- **Per-store group** (one per store in the selected block):
  - readonly info: role, tdt type, fs, channels, duration.
  - `delay_ms` (float ms; 0 = time reference). Unit-agnostic so it applies to every store
    type without needing a sample rate.
  - **timeseries only:** `probe_file` (file picker, optional) + `reorder` (bool).
  - **stim/event only:** `schema` (dropdown from `schema/*`; else placeholder `col00…`
    read-only) + `formatter` (dropdown from formatter registry).
  - **Viewers** subgroup: a checkbox per valid viewer type; each expands to that viewer's
    params seeded from the preset.
- **Actions:** Launch window · Save session · Load session.

## 7. Viewer builders

`builders.build(role, viewer_type, raw_store, attach_cfg) -> ephyviewer viewer`. Registry
keyed `(role, viewer_type)`. Each builder:

1. **Delay:** shift `t_start` by `delay_ms / 1000` seconds (same for all store types).
2. **Probe (timeseries + probe set):** load probe; permute channels into contact order —
   `data_reordered = data[device_channel_indices, :]` (source expects samples × channels, so
   transpose as in the reference) — and set channel names from `brain_region` + `contact_id`.
   Fail loud if probe contact count ≠ stream channel count.
3. **Source:** wrap in the matching `InMemory*Source`
   (`InMemoryAnalogSignalSource`, `InMemoryEventSource`, `InMemorySpikeSource`,
   `InMemoryEpochSource`).
4. **Viewer:** construct and apply seeded params.

The launcher docks builders' outputs via `MainViewer.add_view` (first bare, rest tabified).

### 7.1 Probe reordering

`probe.load_probe(path) -> ProbeMap` returns `device_channel_indices` (contact order → raw
acquisition channel) and per-contact names. "Probe-native order" means displayed channel
`k` = raw channel `device_channel_indices[k]`.

### 7.2 Stim / event formatting

`formatters/`: a `StimFormatter` protocol (`format_row(row: Mapping[str, Any]) -> str`).
`IZVoiceFormatter` ports the reference `chan_formatter` (iterate A/B/C/D voices, skip
inactive channels `chan <= 0`, render amplitude + units). `GenericFormatter` renders
`name: value` per column and is the fallback when no schema is configured. Formatters are
selected/instantiated via Hydra `_target_`. Labels feed `InMemoryEventSource`
(`{label, time, name}`); times come from the store's `ts`.

## 8. Persistence

Sessions save to `<tank>/tdt_explore/sessions/<name>.yaml` — an OmegaConf dump of the
resolved control-tree state: block id, per-store attachments, delays, probe paths, schema +
formatter selections, and viewer params. Load reconstructs the tree. Raw block dirs are
never written to.

## 9. Error handling

Per the project's "no silent failures" rule, fail loud with actionable messages, surfaced as
Qt dialogs in the GUI and raised exceptions in the logic layer:

- probe contact count ≠ stream channel count;
- schema/formatter referencing an absent column;
- unreadable block or a store requested but absent;
- viewer type incompatible with a store's role.

## 10. Testing (TDD)

Logic is Qt-free and unit-tested first:

- `test_stores` — role resolution from fake `StoreInfo` + roles config; classification.
- `test_probe` — permutation + naming from a probeinterface JSON fixture; count-mismatch raises.
- `test_formatters` — `IZVoiceFormatter` / `GenericFormatter` row → string.
- `test_builders` — delay math; source/viewer selection per (role, viewer_type) with fakes.
- `test_session` — save/load round-trip equality.
- `test_config` — Hydra compose + structured-config validation.
- `test_integration_tdt` — real `tdt.read_block` smoke test, **skipped** unless env var
  `TDT_EXPLORE_TEST_BLOCK` points at a block dir.

GUI code is kept thin; all decision logic lives in testable pure functions.

## 11. Dependencies

Add `probeinterface` to `pyproject.toml`. Existing: ephyviewer fork, `tdt`, `PySide6`,
`numpy`, `pandas`, `hydra-core`.

## 12. Deferred / future

- `MonA` current-monitor and `eS1r` special ingestion (await channel-mapping notes).
- Snip waveform overlay (v1 is raster-only).
- Persisting live ephyviewer window state via QSettings.
- Promoting in-GUI column naming to reusable schema presets.
- Combining multiple stores into a single viewer (v1 is one store per viewer).
