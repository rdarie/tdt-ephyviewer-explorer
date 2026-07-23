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
