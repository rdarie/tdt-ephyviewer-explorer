# EpochEncoder annotation support — design

**Date:** 2026-08-28
**Status:** Approved (design), pending implementation plan

## 1. Goal

Add ephyviewer's `EpochEncoder` to every launched Block Window as an always-on,
writable annotation track. Annotations persist to `<block>/tdt_explore/annotations.csv`,
created empty on first launch if absent. The list of possible labels is loaded from a
YAML file whose path is shown in an editable text box in the Control Window, defaulting
to a shipped file containing `['exclude_from_analysis']`.

## 2. Decisions (locked)

- **Enablement:** always-on and automatic. Every launched block gets exactly one
  encoder; there is no per-block on/off toggle.
- **Labels file format:** a standalone YAML file with a top-level list of strings.
- **Labels path persistence:** the chosen path round-trips through the saved Session.
  Enablement is not stored (always-on); only the labels-file path is.
- **Layout:** the encoder is tabified with the first viewer, consistent with every other
  viewer (no split/bottom-strip docking).
- **GUI control:** a plain editable text box for the labels path — no browse button.

## 3. ephyviewer reuse

ephyviewer ships the machinery; no upstream changes:

- `CsvEpochSource(filename, possible_labels, channel_name, restrict_to_possible_labels)`
  — a `WritableEpochSource` that reads/writes CSV columns `time,duration,label`. Its
  `load()` returns an empty epoch dict when the file is missing; `save()` writes the CSV.
- `EpochEncoder` — the viewer; asserts its source is a `WritableEpochSource`, provides
  the add/delete/merge/split UI and a Save action that calls `source.save()`.

Both are re-exported at the `ephyviewer` top level (`from .datasource import *`), so they
import the same way as the existing sources/viewers.

## 4. New Qt-free module: `annotations.py`

Mirrors `impedance.py` — all data logic, unit-testable headless. Qt-free because
`CsvEpochSource` depends only on numpy/pandas/matplotlib, not Qt.

```python
DEFAULT_CHANNEL_NAME = "annotations"

def load_labels(path: Path) -> list[str]:
    """Load the possible-labels YAML list. Raises ValueError on a malformed file
    (not a list, or non-string entries) — no silent failure."""

def resolve_labels_path(cfg) -> Path:
    """Resolve cfg.annotations.labels_path. Absolute paths are used as-is; a relative
    path is resolved against config_schema.CONFIG_DIR so the shipped default is found
    without any hardcoded absolute path."""

def annotations_csv_path(block_path: Path, cfg) -> Path:
    """block_path / notes.BLOCK_SUBDIR / cfg.annotations.filename."""

def build_annotation_source(block_path: Path, labels_path: Path, cfg) -> CsvEpochSource:
    """Resolve the CSV path, mkdir the tdt_explore/ subfolder, build the CsvEpochSource
    with possible_labels=load_labels(labels_path) and
    restrict_to_possible_labels=cfg.annotations.restrict_to_possible_labels. If the CSV
    does not yet exist, call source.save() to create it empty."""
```

Notes:
- `restrict_to_possible_labels` defaults to `false` so labels already present in an
  existing CSV are never rejected.
- `build_annotation_source` reuses `notes.BLOCK_SUBDIR` for the subfolder name.

## 5. Config: new Hydra `annotations` group

`config/annotations/default.yaml` (`# @package _global_`), added to the `config.yaml`
defaults list:

```yaml
# @package _global_
# Writable epoch-encoder annotations, one CSV per block under tdt_explore/.
annotations:
  labels_path: annotations/labels.yaml   # package-relative -> resolved against CONFIG_DIR
  filename: annotations.csv              # written under <block>/tdt_explore/
  restrict_to_possible_labels: false     # keep labels found in an existing CSV
```

Shipped default labels file `config/annotations/labels.yaml`:

```yaml
- exclude_from_analysis
```

`config.yaml` `defaults:` gains `- annotations: default` (before `_self_`).

No hardcoded absolute path: the default is package-relative and resolved via
`resolve_labels_path` against `config_schema.CONFIG_DIR`.

## 6. `builders.py`

- Register `"epochencoder": EpochEncoder` in `_VIEWER_CLASSES`. `build_viewer` already
  constructs `cls(source=..., name=...)` and applies param overrides generically, so no
  other change is needed there.

## 7. `launcher.py`

- `plan_views`: after the store, processed, and impedance plans, **unconditionally
  append one** `ViewPlan`:
  - `name = annotations.DEFAULT_CHANNEL_NAME` (`"annotations"`)
  - `viewer_type = "epochencoder"`
  - `source = build_annotation_source(block_path, labels_path, cfg)`
  - `params = viewer_defaults.get("epochencoder", {})`
  - where `labels_path = resolve_labels_path` applied to
    `session.annotations_labels_path or cfg.annotations.labels_path`. (A session value is
    typically already an absolute path from the GUI; `resolve_labels_path` still handles
    the relative fallback.)
- `launch_block`: no special-casing — the encoder plan flows through the existing
  first-bare / tabify-rest loop, so it tabifies with the first viewer.
- `config/viewer/default.yaml` gains an `epochencoder: {}` entry for symmetry (no
  overrides needed yet).

## 8. `session.py`

- Add `Session.annotations_labels_path: str | None = None`.
- `save_session` already serializes via `asdict`, so the field is written automatically.
- `load_session` passes `annotations_labels_path=container.get("annotations_labels_path")`
  into the `Session(...)` constructor.

## 9. `control_window.py`

- Add an editable `annotations_labels_path` child (type `"str"`) to the **global**
  parameter group (the one currently holding just `block`), seeded from
  `str(resolve_labels_path(cfg))` so the box shows a real, editable absolute path.
- `_on_launch` and `_on_save`: read the global field's value and set it on the built
  `Session` (extend `spec_to_session` call site, or set the attribute after construction).
- `_apply_session`: when a loaded session carries `annotations_labels_path`, write it back
  into the global field.
- `spec_to_session` itself stays per-store; the annotations path is threaded separately
  from the global group (it is not a store attachment).

## 10. Tests: `tests/test_annotations.py` (Qt-free)

- `load_labels`: valid YAML list; malformed (mapping / non-string entries) raises.
- `resolve_labels_path`: relative resolves against `CONFIG_DIR`; absolute is unchanged.
- `annotations_csv_path`: correct `<block>/tdt_explore/<filename>`.
- `build_annotation_source`: creates the empty CSV on first call (file exists afterward,
  with the `time,duration,label` header); a second call loads without clobbering; adding
  an epoch and calling `save()` round-trips through a fresh source.
- Session round-trip: `save_session` / `load_session` preserves `annotations_labels_path`.
- `plan_views` always yields an `"annotations"` / `"epochencoder"` plan, even for a
  session with no store attachments.

## 11. Edge cases / risks

- A block launched with no other viewers gives the encoder an empty time range
  (`t_stop = 0`). Acceptable for v1; the normal multi-viewer case is covered by
  `auto_scale`.
- Existing CSVs whose labels are not in the config list: kept, because
  `restrict_to_possible_labels` is false.
- The raw Synapse files are never touched; the only write is the CSV under
  `<block>/tdt_explore/`.

## 12. Module tree (changed/new)

```
src/tdt_ephyviewer_explorer/
  annotations.py                      # NEW: Qt-free labels/CSV/source logic
  builders.py                         # + "epochencoder" in _VIEWER_CLASSES
  launcher.py                         # + append encoder plan in plan_views
  session.py                          # + annotations_labels_path field
  control_window.py                   # + global labels-path text box
  config/
    config.yaml                       # + annotations in defaults
    viewer/default.yaml               # + epochencoder: {}
    annotations/
      default.yaml                    # NEW: annotations config group
      labels.yaml                     # NEW: shipped default labels list
tests/
  test_annotations.py                 # NEW
```
