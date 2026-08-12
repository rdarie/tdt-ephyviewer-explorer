# tdt-ephyviewer-explorer

Python GUI for quick exploration of TDT (Tucker-Davis Technologies) data, built on a
custom [`ephyviewer`](https://github.com/rdarie/ephyviewer) fork.

Point it at a Synapse **tank**, pick a **block**, compose exactly the viewers you want per
data store (continuous streams, stim/event scalars, epochs, snips), and launch a
synchronized display window.

## Requirements

- Python **3.12+**
- [`uv`](https://docs.astral.sh/uv/) for environment/dependency management
- A Qt platform (PySide6 is installed as a dependency)
- *(dev mode only)* a local checkout of the ephyviewer fork — see below

## Installation

Clone this repo and choose one of the two dependency modes.

### Standard install (ephyviewer from the pinned git fork)

No local ephyviewer checkout needed — `--no-sources` ignores the local dev override and
pulls ephyviewer straight from the git fork declared in `pyproject.toml`:

```bash
git clone https://github.com/<you>/tdt-ephyviewer-explorer.git
cd tdt-ephyviewer-explorer
uv sync --no-sources
```

### Dev mode (editable local ephyviewer)

For hacking on the ephyviewer fork alongside this app, check the fork out **as a sibling
directory** (`../ephyviewer`) and run a plain `uv sync`:

```bash
# side-by-side layout:
#   <parent>/ephyviewer                 (the fork, editable)
#   <parent>/tdt-ephyviewer-explorer    (this repo)
git clone https://github.com/rdarie/ephyviewer.git       # -> ../ephyviewer
cd tdt-ephyviewer-explorer
uv sync
```

`uv sync` installs ephyviewer **editable** from `../ephyviewer`, so your edits to the fork
take effect immediately.

## Running

```bash
uv run tdt-explore --tank "C:/TDT/Synapse/Tanks/<tank>" [--block <block-name>]
```

Or activate the environment first:

```bash
# Windows
.venv\Scripts\activate
# POSIX
source .venv/bin/activate

tdt-explore --tank "/path/to/tank" --block "<block-name>"
```

- `--tank` (optional): a Synapse tank directory (contains block subfolders).
- `--block` (optional): preselect a block; otherwise the first block is auto-selected.
  You can switch blocks from the Control Window's block selector.

`--tank` is optional for both apps; without it the window opens empty and you pick a
tank with the in-window Browse button.

Per-tank sessions (your composed viewer layouts) are saved under
`<tank>/tdt_explore/sessions/` — raw block directories are never modified.

### Desktop shortcuts (Windows)

Create Desktop shortcuts for the two GUIs (run once, per machine):

    uv run tdt-install-shortcuts

This drops **TDT Explore** and **TDT Metadata** on your Desktop. They launch the
apps with no console window; pick a tank with the in-window picker. Re-run the
command after moving the project or recreating the virtual environment.

## Session metadata browser

```bash
uv run tdt-metadata [--tank "C:/TDT/Synapse/Tanks/<tank>"]
```

Lists every block in the tank with its start time and duration. Expanding a block shows
its experiment/subject/user, the gizmos that were active and the stores they wrote, and —
for eStim gizmos — how many pulses were delivered under how many distinct parameter
combinations. The **Expand** buttons open two tables in a side panel:

- **Notes** — the recording's `Notes.txt`, read-only.
- **Analysis notes** — post-hoc annotations you can add, edit, and delete. Each is stamped
  with the wall clock at the time you type it and saved to `<block>/analysis_notes.txt`, in
  the same format Synapse uses for `Notes.txt`. This is the only file either app writes into
  a raw block directory.

Right-click (or double-click) a block to open it in `tdt-explore`.

Reads are tiered so a large tank stays responsive: the block list comes from the text
sidecars alone, while the `.tsq` index and the stim parameter store are read only when you
expand a block, then cached.

## Processed parquet ingestion

Beyond TDT stores, the app loads timeseries and event tables from parquets output by preprocessing
pipelines (e.g., tss-pipeline). Parquets must carry metadata embedded in their schema describing
their contents — see the [contract brief](docs/notes/2026-07-23-tss-pipeline-metadata-contract-brief.md).

**Auto-discovery:** On block select, the app scans `<tank>/torpedo/preprocessed/<block>/` for tagged
parquets (files with the `tdt_explore` contract in their schema metadata). Only contract-tagged files
are loaded; untagged parquets are skipped. Disable auto-scan via `processed.auto_scan`.

**Manual addition:** The **"Add processed…"** button in the Control Window loads a parquet from any
location. Blob-less (untagged) files are accepted; supply a sampling rate interactively.

**Config keys** (`src/tdt_ephyviewer_explorer/config/processed/default.yaml`):
- `preprocessed_subpath` — relative path under `<tank>` for auto-scan (default: `torpedo/preprocessed`)
- `auto_scan` — enable auto-discovery on block select (default: `true`)
- `default_sampling_rate` — fallback rate (Hz) for untagged blob-less timeseries (default: `24414.0625`)
- `time_column_candidates` — heuristic event detection: column names to probe for timestamps in untagged
  event tables (default: `["timestamp"]`)
- `default_label_column` — heuristic event label: column name for per-row labels in untagged event
  tables (default: `stim_site`)
- `ignore_globs` — filename patterns to exclude from auto-scan (default: empty)

**Smoke test against real parquets:**

```bash
# Windows (PowerShell)
$env:TDT_EXPLORE_PREPROCESSED_BLOCK = "<tank>|<block>"; uv run pytest tests/test_processed.py::test_scan_and_build_on_real_block
# POSIX
TDT_EXPLORE_PREPROCESSED_BLOCK="<tank>|<block>" uv run pytest tests/test_processed.py::test_scan_and_build_on_real_block
```

Note the `|` separator in the env var.

## Impedance CSVs

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

## Configuration

Viewer defaults, store-role patterns, column schemas, and stim-label formatters are Hydra
presets under `src/tdt_ephyviewer_explorer/config/`. They are read-only at runtime; the GUI
seeds its parameter tree from them and saves any tweaks to per-tank session files.

## Tests

```bash
uv run pytest
```

The suite is Qt-free and headless. One real-`tdt` integration test is skipped unless you
point it at a real block:

```bash
# Windows (PowerShell)
$env:TDT_EXPLORE_TEST_BLOCK = "C:/TDT/Synapse/Tanks/<tank>/<block>"; uv run pytest tests/test_integration_tdt.py
# POSIX
TDT_EXPLORE_TEST_BLOCK="/path/to/tank/block" uv run pytest tests/test_integration_tdt.py
```
