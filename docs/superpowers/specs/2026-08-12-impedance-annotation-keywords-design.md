# Impedance viewer: keyword-driven cell annotations

**Date:** 2026-08-12
**Status:** Approved (design)

## Problem

The impedance heatmap (`viewers/impedance_view.py`) annotates each cell with only
the impedance value, via a single positional format string
(`annotation_format`, default `"{:.0f}"`, applied as `template.format(value)`).
Users want the channel number shown alongside the impedance, and more generally
want a small set of keywords — drawn from the impedance CSV and, when present,
the probe file — that can be composed freely through the GUI format string.

Note: `build_grid_source` already computes a per-cell `labels` array (probe names,
or `R<n>` without a probe) on `ImpedanceGridSource`, but the viewer never renders
it. This feature supersedes that unused array.

## Approach

Switch the annotation format from a single positional value to **named fields**
(`{channel}`, `{impedance:.0f}`, `{region}`, …) resolved with `str.format_map`.

The impedance value changes with the selected frequency, but channel/probe
metadata does not. So the Qt-free source carries a per-cell dict of *static*
fields; the viewer injects `impedance` (the current grid cell value) at draw
time, then formats. A Qt-free `format_cell` helper does the substitution so it is
unit-testable headless.

Rejected alternative — positional tuple `(channel, impedance)`: positional slots
cannot express "region only when a probe exists," do not scale to a keyword set,
and are worse to edit in a GUI field.

## Keyword set

Always available (from the impedance CSV):

- `channel` — the `R<n>` acquisition channel number (int).
- `impedance` — the averaged impedance for the cell at the selected frequency
  (float, raw averaged value, same units as the colorbar). Injected at render.
- `units` — impedance units parsed from the CSV header, e.g. `"kOhm"`.
- `name` — display label; `R<n>` without a probe, or the composed probe label
  (`"<region> <id>"`, else `<id>`) when a probe is attached; preserves what the
  old `labels` array carried.

Available only when a probe file is attached (omitted otherwise):

- `contact_id` — probeinterface `contact_id`.
- `region` — the `brain_region` contact annotation.

## Behavior

- **Default cell:** `annotation_format = "R{channel}\n{impedance:.0f}"` — channel
  number on the first line, impedance below. Works with no probe.
- **Missing/unknown field:** substitute empty string and keep drawing the rest of
  the cell. `{region}` on a probe-less block, or a typo like `{impdance}`, yields
  empty rather than crashing. A format spec applied to a missing (empty) value
  (e.g. `{impdance:.0f}`) also degrades to empty instead of raising. The same
  format string therefore works across blocks with and without probes.
- **Blank cells:** a cell whose formatted text is entirely blank draws no
  `TextItem` (no change for NaN/empty grid cells, which are already skipped).
- Text color (dark/light by luminance) and centered anchor are unchanged;
  multi-line text renders in the existing `TextItem`.

## Component changes

### `probe.py`
`ProbeMap` gains two optional fields populated by `load_probe` from data it
already reads:

- `contact_ids: list[str] | None`
- `regions: list[str] | None`

`names` and `order` are unchanged. No change to `reorder_channels`,
`probe_layout`, or the timeseries path.

### `impedance.py`
- `ImpedanceGridSource`: **replace** `labels: np.ndarray` with
  `fields: np.ndarray` — a `(n_rows, n_cols)` object array. Each occupied cell
  holds a dict `{"channel", "units", "name", "contact_id", "region"}` (probe keys
  present only when a probe was supplied); empty cells hold `None`.
- `build_grid_source`: build the `fields` array in the same loop that fills the
  old `cell_labels` today. `channel` = the wanted `R<n>` number; `units` =
  `data.units`; probe keys from the extended `ProbeMap`. The `name` value equals
  the old label (probe name, or `R<n>` without a probe).
- New Qt-free helper `format_cell(template: str, fields: Mapping[str, Any]) -> str`:
  a `string.Formatter` subclass whose `get_value` returns `""` for missing keys
  and whose `format_field` returns `""` when a spec fails on an empty value.

### `viewers/impedance_view.py`
- `_default_params`: `annotation_format` default becomes
  `"R{channel}\n{impedance:.0f}"`.
- `_refresh_annotations`: for each occupied cell build
  `merged = {**(source.fields[row, col] or {}), "impedance": value}`, call
  `format_cell(template, merged)`, and skip the cell if the result is blank.

## Non-goals

- Not moving impedance viewer defaults into Hydra config. `vmin`/`vmax`/`cmap`/
  `annotate`/`annotation_format` all live in the viewer's `_default_params`
  today; this stays consistent. (A later change could seed all of them from
  `config/impedance/` uniformly.)
- No change to the footer, the frequency selector, or the averaged metadata
  columns.

## Tests

- `tests/test_probe.py`: `load_probe` populates `contact_ids`/`regions` when the
  probe has them, and leaves them `None`/name-fallback when it does not.
- `tests/test_impedance.py`:
  - `build_grid_source` produces a `fields` array of the right shape; occupied
    cells carry the expected keys with and without a probe; empty cells are
    `None`; probe keys are absent without a probe.
  - `format_cell`: named substitution; missing key → empty; format spec on a
    missing value → empty; multi-line output; numeric spec on `impedance`.
