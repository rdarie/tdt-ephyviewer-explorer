# tdt-metadata — design

**Date:** 2026-07-29
**Status:** approved, ready for implementation planning

## Purpose

A second app in this repo that answers "what happened in this recording session?" without
opening any viewers. Point it at a tank; get a browsable tree of blocks showing duration,
active gizmos, notes, and — for eStim gizmos — how many pulses were delivered under how many
distinct parameter settings. Adds a post-hoc annotation file the explorer has no place for.

## Scope

In scope for v1:

- Tank picker plus an expanding tree of blocks with per-block metadata.
- eStim summary: pulse count and unique-parameter-combination count.
- Read-only view of `Notes.txt` in a side panel.
- Editable `analysis_notes.txt`, written into the block directory.
- "Open in tdt-explore" action on a block row.
- `--tank` made optional in the existing `tdt-explore`, which gains the same shared picker.

Out of scope for v1: clipboard copy of a block summary, whole-tank CSV/Markdown export,
a drill-down table of individual stim parameter combinations.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Packaging | New subpackage in this repo, second console script | Tank discovery, `.tsq` header reuse, and the stim column schema already live here |
| Read strategy | Text metadata eagerly for all blocks; headers and stim data lazily on expand | `eS1p` costs ~1.7 s/block; a 25-block tank would stall for a minute if eager |
| Stim summary depth | Two headline numbers only | Explicitly chosen over a constant/varying breakdown or a combo table |
| Voice activity test | `chan > 0` | `chan = 0` is a dummy value meaning "no stimulation" |
| Analysis notes location | `<block>/analysis_notes.txt` | Notes travel with the data folder; a documented one-time exception to the no-writes rule |
| Analysis note timestamps | Wall clock at time of typing | Honest provenance for the annotation |
| Block list UI | Expanding tree, notes in a side panel | Several blocks comparable at once |

## Architecture

A Qt-free core that does all parsing and computation, and a thin Qt shell — the split the
existing app already uses, so every parser is unit-testable headless.

### Module tree

```
src/tdt_ephyviewer_explorer/
  tank_picker.py     # NEW shared Qt widget: path field + Browse… + tank_changed signal
  app.py             # MODIFIED: --tank optional; reads tank from the control window
  control_window.py  # MODIFIED: hosts a TankPicker; owns tank_dir
  metadata/
    __init__.py
    listing.py       # StoresListing.txt  -> list[Gizmo]
    notes.py         # Notes.txt / analysis_notes.txt <-> list[Note]  (read + write)
    stim.py          # eS1p data          -> StimSummary
    summary.py       # BlockSummary + the three read tiers, with caching
    window.py        # Qt: MetadataWindow — picker, block tree, side panel
    notes_panel.py   # Qt: side-panel notes tables (read-only + editable)
    app.py           # `tdt-metadata` console script
  config/
    metadata/default.yaml   # NEW Hydra group
```

### Dependency direction

`metadata/` imports from `tank`, `stores`, `config_schema`, and `tank_picker`. Nothing
existing imports from `metadata/`. The single exception is the "Open in tdt-explore" action,
which constructs the existing `App` and calls its public `open_tank(tank, block)`.

`tank_picker.py` lives at package top level, not inside `metadata/`, precisely so that
`control_window.py` can import it without depending on the new subpackage.

### Reuse

- `tank.list_blocks` — block discovery
- `tank.read_headers` — the tier-1 header parse
- `stores.load_store` — loading `eS1p`
- `config_schema.load_config` — the composed Hydra config
- `schemas.iz_param_names` — stim column names

### Configuration

A new `config/metadata/default.yaml` group (`# @package _global_`, added to `config.yaml`'s
`defaults`) holds what would otherwise be hardcoded: the stim store pattern (`eS?p`), the
schema naming its columns (`iz_param_names`), the voice suffixes (`A`–`D`), the `chan` and
`count` column prefixes, and the analysis-notes filename.

### Entry points

`pyproject.toml` gains `tdt-metadata = "tdt_ephyviewer_explorer.metadata.app:main"`.
It takes an optional `--tank`; with none, the window opens with an empty picker. There is no
`--block` — browsing the whole tank is the point, and preselecting one block is the
explorer's job.

## Data model

Five frozen dataclasses, all Qt-free:

```python
Gizmo(object_id: str, kind: str | None, stores: tuple[str, ...])
Note(index: int, timestamp: datetime, text: str)
StimSummary(store: str, n_pulses: int, n_combinations: int)
BlockSummary(name, path, experiment, subject, user, start, stop,
             duration_s, gizmos, notes, stim, warnings)
BlockCache  # name -> BlockSummary, plus a per-block "details loaded" flag
```

## The three read tiers

Measured on `Epi_02_Green-260727-152924`: header parse 0.05 s, `eS1p` load 1.74 s.

### T0 — `read_text_metadata(block_path) -> BlockSummary`

Pure text, no `tdt`, instant. Populates the whole collapsed tree.

- `Notes.txt` → Experiment / Subject / User / Start / Stop, and the
  `Note-N: <time> "<text>"` lines. Duration = Stop − Start.
- `StoresListing.txt` → gizmos. Parse the **`Object ID :` blocks**, not the `Flat Listing`
  table: only the blocks carry the human-readable kind ("Electrical Stim Driver").

### T1 — `augment_with_headers(summary, headers) -> BlockSummary`

`tank.read_headers`, ~0.05 s. Supplies the authoritative store list, and a duration from
`stop_time - start_time` when `Notes.txt` is absent or has no `Stop` line. Stores present in
the headers but missing from `StoresListing.txt` are appended under a synthetic `(unlisted)`
gizmo rather than dropped.

### T2 — `read_stim_summaries(block_path, cfg, headers) -> tuple[StimSummary, ...]`

For each header store matching the configured pattern, `stores.load_store`, then:

- Column names come from the configured schema. If the store's row count does not match the
  schema length, warn and skip that store — never mislabel columns.
- **Active voices** = suffixes where `chan{V} > 0` for *any* event in the block.
- **`n_combinations`** = number of unique rows over the columns belonging to active voices.
  Restricting to active voices stops an idle voice's constant-but-nonzero junk from
  inflating the count.
- **`n_pulses`** = Σ over events of the maximum `count{V}` across that event's active voices.
  Voices fire concurrently, so a 3-pulse train on two voices is 3 pulses, not 6. Events with
  no active voice contribute 0.

T1 and T2 run together on a `QThreadPool` worker keyed by block name. The expanded row shows
`loading…` until it returns. Results are cached for the session; re-picking the same tank
reuses the cache, picking a different tank clears it.

### Reference values

`Epi_02_Green-260727-154827`, 15999 events over t = 9.4–543.7 s:

| voice | per | count | amp | dur | chan |
|---|---|---|---|---|---|
| A | 0.983 | 1 | −150 | 0.8 | 51 distinct values in 1–63 |
| B | 0.983 | 0 | 0 | 0.8 | 51 distinct values in 1–63 |
| C, D | — | — | — | — | `chan = 0` throughout → inactive |

B is the return/anode electrode, never a current source: `chanB` sweeps but `countB` is `0`
for every event, so B never contributes a pulse. 438 of the 15999 events have `chanA == 0`
(no stimulating cathode) while `chanB > 0`; since B's count is always zero, those events
deliver nothing. Active voices `{A, B}` → **15561 pulses · 1881 unique combinations**. This is
the integration test's expected output.

## The window

`QSplitter`: block tree left, notes side panel right, hidden until the first **Expand**.
`TankPicker` spans the top.

```
┌─ [ C:/TDT/Synapse/Tanks/cnn_gp_mep_all_udp_v2-260610-173723 ] [Browse…] ──────────────────┐
│                                                                                            │
│  Block                          Start     Duration  ┃  Epi_02_Green-260727-154827          │
│  ▸ Epi_02_Green-260727-152924   15:29:27   3m57s    ┃  Notes.txt · read-only               │
│  ▾ Epi_02_Green-260727-154827   15:48:30   9m08s    ┃  ──────────────────────────────────  │
│      Experiment  cnn_gp_mep_all_udp_v2              ┃  # Timestamp  Note                   │
│      Subject     Epi_02_Green                       ┃  1 15:49:37   first run should be    │
│      User        User                               ┃               chan 5 but is chan 4   │
│      ▾ Gizmos                                       ┃  2 15:50:16   will correctly set     │
│          eStim1   Electrical Stim Driver  eS1p eS1r ┃               chan 6 to 6 to avoid   │
│          Wave1    Stream Data Storage     Wav1      ┃               confusion              │
│          NPro1    Neural Stream Processor SU_1      ┃                                      │
│          IZVn(1)  IZV                     MonA      ┃                                      │
│          …                                          ┃                                      │
│      ▾ Stimulation                                  ┃                                      │
│          eS1p   15561 pulses · 1881 combinations    ┃                                      │
│      Notes            2 notes       [ Expand ]      ┃                                      │
│      Analysis notes   0 notes       [ Expand ]      ┃                                      │
│  ▸ Epi_02_Green-260727-155924   15:59:24  10m24s    ┃                                      │
└────────────────────────────────────────────────────────────────────────────────────────────┘

Values above are the real contents of that block, not illustrative placeholders.
```

- **Collapsed row** = name, start, duration. Blocks sort by name, which is chronological.
- **Expanding** triggers the T1+T2 worker; `Gizmos` and `Stimulation` show `loading…` until it
  lands. Several blocks may stay expanded at once.
- **Notes / Analysis notes** rows show a count and an `Expand` button. Clicking either opens
  the side panel on that table, swapping its content if something else was showing. The panel
  header names the block and the file, so an open panel is never ambiguous while several
  blocks are expanded. (Accepted trade-off: with several blocks open, the notes on screen may
  belong to a block scrolled out of view. The header line is the mitigation.)
- **Open in tdt-explore** — right-click action on a block row, and the double-click default.
- Blocks that fail to parse still appear, marked `⚠`, with the reason as a child node.

### TankPicker

Surface: a `tank_dir` property and a `tank_changed(Path)` signal. It validates that the chosen
directory contains at least one block before emitting, and shows an inline message when it
does not.

### Changes to tdt-explore

1. `--tank` becomes optional. With no tank, the Control Window opens with an empty tree and
   the launch button disabled.
2. `ControlWindow` hosts a `TankPicker` at the top, wired to its existing `set_tank`.
3. `ControlWindow` becomes the single owner of the current tank via a `tank_dir` attribute set
   by `set_tank`. `App._tank_dir` is deleted; `App._on_launch` reads
   `self.control_window.tank_dir`. Without this, picking a new tank in the GUI would leave
   `App` launching blocks from the previous one — so it is part of the change, not a drive-by
   refactor.

## Analysis notes

### Location

`<block>/analysis_notes.txt`, alongside `Notes.txt`. This is a deliberate, documented
exception to the project rule that raw block directories are never written to; CLAUDE.md's
Session bullet gets a note recording the exception. `Notes.txt` is opened read-only and is
never written by any code path.

### Format

The `Notes.txt` shape, with one necessary extension:

```
Experiment: cnn_gp_mep_all_udp_v2
Subject: Epi_02_Green
User: User
Start: 3:48:30pm 07/27/2026

Note-1: 2:02:14pm 07/29/2026 "EMG saturated"
Note-2: 2:05:31pm 07/29/2026 "check ch 34"

Stop: 3:57:38pm 07/27/2026
```

The header block above is copied verbatim from the reference block's `Notes.txt`; only the
`Note-N:` entries are authored here.

`Notes.txt` writes `Note-N: <time> "<text>"` — time only, because its notes are same-day as
`Start`. An analysis note authored days later needs the date, so entries carry
`<time> <date>`. **One parser reads both forms**: the date is optional and inferred from
`Start` when absent. The header block is copied from `Notes.txt` so the file identifies its
recording standalone; with no `Notes.txt`, it is derived from T1 headers and the block name.

### Editing

- The panel's last row is always a blank entry row. Typing text and pressing Enter stamps it
  with the current wall clock, appends it, writes the file, and opens a fresh blank row. A
  block with no `analysis_notes.txt` shows `0 notes`, and expanding it opens a panel holding
  only that blank row — the file is created by the first save.
- Existing rows are editable in place and deletable via `Delete` or right-click; notes
  renumber `1..N` afterwards.
- **The timestamp column is read-only.** The chosen semantics are wall-clock-at-typing, and a
  hand-editable timestamp would quietly destroy that provenance.

### Writing

Whole-file and atomic: build the full text, write a temp file in the same directory,
`os.replace`. These files are a few hundred bytes, so incremental appends buy nothing, and a
crash mid-write cannot truncate existing notes.

Before each write, the file's mtime is compared against what was loaded; if it changed
underneath, the write is refused with a message rather than clobbering. An unwritable block
directory surfaces the error in the panel. The file is created on the first saved note, not
while browsing.

Files are read as UTF-8, falling back to latin-1, and always written as UTF-8.

## Error handling

Every degraded path records a string in `BlockSummary.warnings` and renders as a `⚠` child
node on the block row. Nothing is dropped silently; nothing crashes the window.

| Situation | Behaviour |
|---|---|
| Tank has no block dirs | Picker refuses the path, inline message, tree unchanged |
| Block dir unreadable | Row present, `⚠` + reason |
| `Notes.txt` absent | Header and duration from T1 headers; Notes row reads `none` |
| A `Note-N:` line will not parse | That line skipped and warned; the rest still shown |
| `StoresListing.txt` absent | Gizmos from T1 headers under `(unlisted)` |
| `eS1p` absent | No Stimulation row at all |
| Store rows ≠ schema length | Stim store skipped and warned — never mislabel columns |
| Zero stim events | `0 pulses · 0 combinations` |
| Worker raises | Error text on the row; other blocks unaffected |
| Block dir not writable | Analysis-notes save fails loudly in the panel |

Note that a missing `.tev` is *not* an error case: scalars are stored in the `.tsq`, so
`eS1p` still loads. Verified on `Mickey-260610-173723`, which has no `.tev` and still yields
500 events.

## Testing

Following the existing convention: pure functions tested directly, Qt paths behind
`pytest.importorskip("ephyviewer")` with a module-scoped `qapp` fixture, real-`tdt` work
gated on `TDT_EXPLORE_TEST_BLOCK`.

- **`test_metadata_listing.py`** — the real `StoresListing.txt` copied to
  `tests/fixtures/metadata/`, plus a truncated one and one with no `Flat Listing` section.
- **`test_metadata_notes.py`** — the heaviest. Parse the real `Notes.txt`; round-trip identity
  (parse → render → parse); both the time-only and time-plus-date entry forms; append, edit,
  and delete with renumbering; atomic write via `tmp_path`; the mtime-changed-underneath
  refusal; an unwritable directory.
- **`test_metadata_stim.py`** — pure `numpy`, no `tdt`. Synthetic arrays covering active-voice
  detection via `chan > 0`; `count > 1` yielding more pulses than events; an idle voice with
  wobbling non-`chan` columns not inflating the combination count; zero active voices;
  schema-length mismatch.
- **`test_metadata_summary.py`** — the tiers over fixtures and a stub headers object; T1
  filling in a duration `Notes.txt` did not supply; caching (a second expand does not re-read).
- **`test_metadata_window.py`** — `importorskip` plus `qapp`; construct with no tank, switch
  tanks, expand a block with a monkeypatched loader.

Extended: `test_app.py` and `test_control_window.py` gain no-tank-startup and tank-switch
cases. `test_integration_tdt.py` gains an env-gated case asserting the reference block yields
15561 pulses and 1881 combinations.

No test reaches a real tank path unless `TDT_EXPLORE_TEST_BLOCK` is set; all fixtures are
copies checked into the repo.

## Documentation

- `README.md` — a `tdt-metadata` section, and the now-optional `--tank` for `tdt-explore`.
- `.claude/CLAUDE.md` — add `tdt-metadata` to Commands; add `metadata/` and `tank_picker.py`
  to the Codebase Map; record the `analysis_notes.txt` exception to the no-writes rule.
