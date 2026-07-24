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

- `--tank` (required): a Synapse tank directory (contains block subfolders).
- `--block` (optional): preselect a block; otherwise the first block is auto-selected.
  You can switch blocks from the Control Window's block selector.

Per-tank sessions (your composed viewer layouts) are saved under
`<tank>/tdt_explore/sessions/` — raw block directories are never modified.

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
