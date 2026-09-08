# EpochEncoder Annotation Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ephyviewer's `EpochEncoder` to every launched Block Window as an always-on, writable annotation track persisting to `<block>/tdt_explore/annotations.csv`.

**Architecture:** A new Qt-free `annotations.py` module (mirroring `impedance.py`) owns all labels/CSV/source logic using ephyviewer's `CsvEpochSource` + `EpochEncoder`. `plan_views` unconditionally appends one encoder plan per launched block; the Control Window carries an editable labels-file path in its global group that round-trips through the saved Session.

**Tech Stack:** Python 3.12+, Hydra/OmegaConf configs, ephyviewer (custom fork), NumPy/Pandas, pytest (Qt-free headless core).

**Spec:** `docs/superpowers/specs/2026-08-28-epoch-encoder-design.md`

## Global Constraints

- **Package manager / runner:** `uv`. Always run via `uv run …` (venv-activated). Never call `python`/`pytest`/`pip` outside the venv.
- **No hardcoded absolute paths:** the default labels path is package-relative, resolved against `config_schema.CONFIG_DIR`.
- **No magic numbers / hyperparameters in code:** all tunables (`labels_path`, `filename`, `restrict_to_possible_labels`) live in the Hydra `annotations` config group.
- **No silent failures:** `load_labels` raises `ValueError` on a malformed labels file.
- **Block-dir writes stay under `<block>/tdt_explore/`:** the only write is the annotations CSV; raw Synapse files are never touched. Reuse `metadata.notes.BLOCK_SUBDIR` for the subfolder name.
- **Qt-free core:** `annotations.py` and its tests must import no Qt. `CsvEpochSource` depends only on numpy/pandas/matplotlib.
- **Types & docstrings:** strict `typing`; reST-style docstrings.
- **Tests:** each `src/` module has a mirror `tests/test_<module>.py`. Run the full suite with `uv run pytest`.

---

### Task 1: Hydra `annotations` config group

Adds the config group, the shipped default labels file, wires the group into the top-level defaults, and adds the `epochencoder` viewer-defaults entry. Deliverable: `load_config()` exposes `cfg.annotations` and `cfg.viewers.epochencoder`.

**Files:**
- Create: `src/tdt_ephyviewer_explorer/config/annotations/default.yaml`
- Create: `src/tdt_ephyviewer_explorer/config/annotations/labels.yaml`
- Modify: `src/tdt_ephyviewer_explorer/config/config.yaml` (defaults list)
- Modify: `src/tdt_ephyviewer_explorer/config/viewer/default.yaml` (add `epochencoder: {}`)
- Test: `tests/test_config.py` (create if absent)

**Interfaces:**
- Consumes: nothing.
- Produces: `cfg.annotations.labels_path` (str, `"annotations/labels.yaml"`), `cfg.annotations.filename` (str, `"annotations.csv"`), `cfg.annotations.restrict_to_possible_labels` (bool, `False`); `cfg.viewers.epochencoder` (`{}`). Consumed by Tasks 2, 3, 5.

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_config.py`:

```python
"""Tests that the composed Hydra config exposes the expected groups."""
from tdt_ephyviewer_explorer.config_schema import load_config


def test_config_has_annotations_group() -> None:
    cfg = load_config()
    assert cfg.annotations.labels_path == "annotations/labels.yaml"
    assert cfg.annotations.filename == "annotations.csv"
    assert cfg.annotations.restrict_to_possible_labels is False


def test_config_has_epochencoder_viewer_defaults() -> None:
    cfg = load_config()
    assert "epochencoder" in cfg.viewers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `omegaconf.errors.ConfigAttributeError` (no `annotations` key).

- [ ] **Step 3: Create the config files and wire them in**

Create `src/tdt_ephyviewer_explorer/config/annotations/default.yaml`:

```yaml
# @package _global_
# Writable epoch-encoder annotations, one CSV per block under tdt_explore/.
annotations:
  labels_path: annotations/labels.yaml   # package-relative -> resolved against CONFIG_DIR
  filename: annotations.csv              # written under <block>/tdt_explore/
  restrict_to_possible_labels: false     # keep labels found in an existing CSV
```

Create `src/tdt_ephyviewer_explorer/config/annotations/labels.yaml`:

```yaml
- exclude_from_analysis
```

Edit `src/tdt_ephyviewer_explorer/config/config.yaml` — add `- annotations: default` after `metadata` and before `_self_`:

```yaml
defaults:
  - viewer: default
  - roles: default
  - schema: default
  - startup: default
  - processed: default
  - impedance: default
  - metadata: default
  - annotations: default
  - _self_
```

Edit `src/tdt_ephyviewer_explorer/config/viewer/default.yaml` — add an `epochencoder` entry under `viewers:` (place after `epoch: {}`):

```yaml
  epoch: {}
  epochencoder: {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/config/annotations/ src/tdt_ephyviewer_explorer/config/config.yaml src/tdt_ephyviewer_explorer/config/viewer/default.yaml tests/test_config.py
git commit -m "feat(config): add annotations Hydra group and epochencoder viewer defaults"
```

---

### Task 2: `annotations.py` Qt-free module

The core: label loading, path resolution, CSV-path derivation, and the writable epoch source. Deliverable: `build_annotation_source` creates an empty CSV on first launch and round-trips added epochs.

**Files:**
- Create: `src/tdt_ephyviewer_explorer/annotations.py`
- Test: `tests/test_annotations.py`

**Interfaces:**
- Consumes: `cfg.annotations.*` (Task 1); `config_schema.CONFIG_DIR`; `metadata.notes.BLOCK_SUBDIR`; ephyviewer `CsvEpochSource`.
- Produces:
  - `DEFAULT_CHANNEL_NAME: str = "annotations"`
  - `load_labels(path: Path) -> list[str]`
  - `resolve_labels_path(cfg: Any, path: str | os.PathLike[str] | None = None) -> Path` — resolves `path` if given, else `cfg.annotations.labels_path`; absolute unchanged, relative resolved against `CONFIG_DIR`.
  - `annotations_csv_path(block_path: Path, cfg: Any) -> Path`
  - `build_annotation_source(block_path: Path, labels_path: Path, cfg: Any) -> CsvEpochSource`

  Consumed by Tasks 5 (launcher) and 6 (control window).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_annotations.py`:

```python
"""Qt-free tests for the epoch-encoder annotation logic."""
from pathlib import Path

import pytest

pytest.importorskip("ephyviewer")

from ephyviewer import CsvEpochSource

from tdt_ephyviewer_explorer.annotations import (
    DEFAULT_CHANNEL_NAME,
    annotations_csv_path,
    build_annotation_source,
    load_labels,
    resolve_labels_path,
)
from tdt_ephyviewer_explorer.config_schema import CONFIG_DIR, load_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_load_labels_valid_list(tmp_path: Path) -> None:
    p = _write(tmp_path / "l.yaml", "- a\n- b\n")
    assert load_labels(p) == ["a", "b"]


def test_load_labels_rejects_mapping(tmp_path: Path) -> None:
    p = _write(tmp_path / "m.yaml", "k: v\n")
    with pytest.raises(ValueError):
        load_labels(p)


def test_load_labels_rejects_non_string_entries(tmp_path: Path) -> None:
    p = _write(tmp_path / "n.yaml", "- a\n- 3\n")
    with pytest.raises(ValueError):
        load_labels(p)


def test_resolve_labels_path_relative_against_config_dir() -> None:
    cfg = load_config()
    resolved = resolve_labels_path(cfg)
    assert resolved == (CONFIG_DIR / "annotations/labels.yaml").resolve()
    assert resolved.is_absolute()


def test_resolve_labels_path_absolute_unchanged(tmp_path: Path) -> None:
    cfg = load_config()
    abs_path = tmp_path / "custom.yaml"
    assert resolve_labels_path(cfg, abs_path) == abs_path


def test_annotations_csv_path(tmp_path: Path) -> None:
    cfg = load_config()
    block = tmp_path / "blk"
    assert annotations_csv_path(block, cfg) == block / "tdt_explore" / "annotations.csv"


def test_build_annotation_source_creates_empty_csv(tmp_path: Path) -> None:
    cfg = load_config()
    block = tmp_path / "blk"
    block.mkdir()
    labels = resolve_labels_path(cfg)
    src = build_annotation_source(block, labels, cfg)
    csv = annotations_csv_path(block, cfg)
    assert isinstance(src, CsvEpochSource)
    assert csv.exists()
    assert csv.read_text().splitlines()[0] == "time,duration,label"


def test_build_annotation_source_second_call_does_not_clobber(tmp_path: Path) -> None:
    cfg = load_config()
    block = tmp_path / "blk"
    block.mkdir()
    labels = resolve_labels_path(cfg)
    src = build_annotation_source(block, labels, cfg)
    src.add_epoch(1.0, 2.0, "exclude_from_analysis")
    src.save()
    # A fresh source over the same CSV must load the saved epoch.
    reloaded = build_annotation_source(block, labels, cfg)
    ep = reloaded.get_chunk(chan=0)
    assert list(ep["label"]) == ["exclude_from_analysis"]


def test_default_channel_name() -> None:
    assert DEFAULT_CHANNEL_NAME == "annotations"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_annotations.py -v`
Expected: FAIL — `ModuleNotFoundError: tdt_ephyviewer_explorer.annotations`.

- [ ] **Step 3: Write the module**

Create `src/tdt_ephyviewer_explorer/annotations.py`:

```python
"""Writable epoch-encoder annotations for launched blocks (Qt-free).

Mirrors :mod:`impedance` — all data logic here is unit-testable headless.
ephyviewer's :class:`CsvEpochSource` and :class:`EpochEncoder` provide the
machinery; this module only resolves paths, loads the possible-labels list, and
builds the source. The only block-dir write is the annotations CSV under
``<block>/tdt_explore/``; raw Synapse files are never touched.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ephyviewer import CsvEpochSource
from omegaconf import OmegaConf

from tdt_ephyviewer_explorer.config_schema import CONFIG_DIR
from tdt_ephyviewer_explorer.metadata.notes import BLOCK_SUBDIR

DEFAULT_CHANNEL_NAME = "annotations"


def load_labels(path: Path) -> list[str]:
    """Load the possible-labels YAML list.

    :param path: A YAML file whose top level is a list of strings.
    :returns: The label strings, in file order.
    :raises ValueError: If the file is not a list, or has a non-string entry.
    """
    data = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise ValueError(
            f"labels file {path} must be a YAML list of strings, got {data!r}"
        )
    return list(data)


def resolve_labels_path(cfg: Any, path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve a possible-labels file path.

    Uses ``path`` when given (a session-carried value), else
    ``cfg.annotations.labels_path``. Absolute paths are returned as-is; a relative
    path is resolved against :data:`config_schema.CONFIG_DIR`, so the shipped
    default is found without any hardcoded absolute path.

    :param cfg: Composed config (uses ``cfg.annotations.labels_path`` as fallback).
    :param path: An explicit path override, or ``None`` to use the config default.
    :returns: An absolute path to the labels file.
    """
    raw = Path(path) if path else Path(str(cfg.annotations.labels_path))
    if raw.is_absolute():
        return raw
    return (CONFIG_DIR / raw).resolve()


def annotations_csv_path(block_path: Path, cfg: Any) -> Path:
    """Return the per-block annotations CSV path.

    :param block_path: Block directory.
    :param cfg: Composed config (uses ``cfg.annotations.filename``).
    :returns: ``<block>/tdt_explore/<filename>``.
    """
    return block_path / BLOCK_SUBDIR / str(cfg.annotations.filename)


def build_annotation_source(
    block_path: Path, labels_path: Path, cfg: Any
) -> CsvEpochSource:
    """Build the writable epoch source for a block, creating the CSV if absent.

    Resolves the CSV path under ``<block>/tdt_explore/``, ensures the subfolder
    exists, and builds a :class:`CsvEpochSource` with the possible labels loaded
    from ``labels_path``. When the CSV does not yet exist it is created empty via
    ``source.save()`` so first launch leaves a valid ``time,duration,label`` file.

    :param block_path: Block directory.
    :param labels_path: Resolved possible-labels YAML file.
    :param cfg: Composed config (uses ``cfg.annotations.restrict_to_possible_labels``).
    :returns: The writable epoch source.
    """
    csv = annotations_csv_path(block_path, cfg)
    csv.parent.mkdir(parents=True, exist_ok=True)
    existed = csv.exists()
    source = CsvEpochSource(
        str(csv),
        possible_labels=load_labels(labels_path),
        channel_name=DEFAULT_CHANNEL_NAME,
        restrict_to_possible_labels=bool(cfg.annotations.restrict_to_possible_labels),
    )
    if not existed:
        source.save()  # write an empty time,duration,label CSV
    return source
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_annotations.py -v`
Expected: PASS (all 9 tests). If `get_chunk`/`add_epoch` signatures differ in the fork, adjust the round-trip test to the fork's `WritableEpochSource` API — the source-creation and CSV-header assertions are the load-bearing checks.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/annotations.py tests/test_annotations.py
git commit -m "feat(annotations): Qt-free labels/CSV/CsvEpochSource logic"
```

---

### Task 3: Register `epochencoder` viewer in `builders.py`

Makes `build_viewer("epochencoder", …)` construct an `EpochEncoder`. Deliverable: the viewer registry resolves the new key.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/builders.py` (import + `_VIEWER_CLASSES`)
- Test: `tests/test_builders.py`

**Interfaces:**
- Consumes: `build_annotation_source` (Task 2) to make a real source in the test.
- Produces: `_VIEWER_CLASSES["epochencoder"] = EpochEncoder`; `build_viewer("epochencoder", source, name, params)` returns an `EpochEncoder`. Consumed by Task 5 (`launch_block`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_builders.py` (add the ephyviewer skip guard at top if not already present):

```python
def test_build_viewer_epochencoder(tmp_path) -> None:
    import pytest
    pytest.importorskip("ephyviewer")
    from ephyviewer import EpochEncoder, mkQApp

    from tdt_ephyviewer_explorer.annotations import build_annotation_source, resolve_labels_path
    from tdt_ephyviewer_explorer.builders import build_viewer
    from tdt_ephyviewer_explorer.config_schema import load_config

    mkQApp()
    cfg = load_config()
    block = tmp_path / "blk"
    block.mkdir()
    src = build_annotation_source(block, resolve_labels_path(cfg), cfg)
    view = build_viewer("epochencoder", src, name="annotations", params={})
    assert isinstance(view, EpochEncoder)
    assert view.name == "annotations"
```

Note: `EpochEncoder` needs a `QApplication`; `mkQApp()` provides it headlessly, consistent with `tests/test_launcher.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_builders.py::test_build_viewer_epochencoder -v`
Expected: FAIL — `KeyError: 'epochencoder'`.

- [ ] **Step 3: Register the viewer**

Edit `src/tdt_ephyviewer_explorer/builders.py`. Add `EpochEncoder` to the `ephyviewer` import block (alphabetical, before `EpochViewer`):

```python
from ephyviewer import (
    EpochEncoder,
    EpochViewer,
    EventList,
    ...
```

Add the registry entry in `_VIEWER_CLASSES` (after `"epoch": EpochViewer,`):

```python
    "epoch": EpochViewer,
    "epochencoder": EpochEncoder,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_builders.py::test_build_viewer_epochencoder -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/builders.py tests/test_builders.py
git commit -m "feat(builders): register epochencoder viewer"
```

---

### Task 4: `Session.annotations_labels_path` field

Adds the persisted labels-path to the session record. Deliverable: the field round-trips through `save_session`/`load_session`, and legacy sessions without the key still load.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/session.py` (dataclass field + `load_session`)
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Session.annotations_labels_path: str | None = None`, persisted by `save_session` (via `asdict`) and read by `load_session`. Consumed by Tasks 5 and 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session.py`:

```python
def test_session_annotations_labels_path_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        attachments={"Wav1": [{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}]},
        annotations_labels_path="/abs/labels.yaml",
    )
    out = save_session(session, tmp_path, "ann")
    loaded = load_session(out)
    assert loaded == session
    assert loaded.annotations_labels_path == "/abs/labels.yaml"


def test_session_default_annotations_labels_path_is_none() -> None:
    assert Session(block="b").annotations_labels_path is None


def test_load_session_without_annotations_key(tmp_path: Path) -> None:
    # Sessions written before this feature have no key and must still load.
    path = tmp_path / "old.yaml"
    path.write_text(
        "block: rRew03-1\n"
        "attachments: {}\n"
        "processed: []\n"
        "impedance: []\n"
    )
    loaded = load_session(path)
    assert loaded.annotations_labels_path is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_session.py -k annotations -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'annotations_labels_path'`.

- [ ] **Step 3: Add the field and load it**

Edit `src/tdt_ephyviewer_explorer/session.py`. Add the field to the `Session` dataclass (after `impedance`) and document it:

```python
@dataclass
class Session:
    """A saved composition: which viewers are attached to which stores.

    :param block: Block directory name.
    :param attachments: TDT store name -> list of serialized attachment dicts.
    :param processed: Processed-parquet sources composed into this session.
    :param impedance: Impedance CSV sidecars composed into this session.
    :param annotations_labels_path: Absolute path to the epoch-encoder labels YAML,
        or ``None`` to use the config default. Enablement is not stored (always-on).
    """

    block: str
    attachments: dict[str, list[dict]] = field(default_factory=dict)
    processed: list[ProcessedSource] = field(default_factory=list)
    impedance: list[ImpedanceSource] = field(default_factory=list)
    annotations_labels_path: str | None = None
```

Edit `load_session` to pass the (optional) key through:

```python
    return Session(
        block=container["block"],
        attachments=container["attachments"],
        processed=processed,
        impedance=impedance,
        annotations_labels_path=container.get("annotations_labels_path"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py -v`
Expected: PASS (new and existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/session.py tests/test_session.py
git commit -m "feat(session): persist annotations_labels_path"
```

---

### Task 5: Append the encoder plan in `launcher.py`

`plan_views` unconditionally appends one `"annotations"` / `"epochencoder"` plan; existing tests are updated for the extra plan. Deliverable: every launched block gets exactly one encoder, tabified with the first viewer.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/launcher.py` (`plan_views`)
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `annotations.build_annotation_source`, `annotations.resolve_labels_path`, `annotations.DEFAULT_CHANNEL_NAME` (Task 2); `Session.annotations_labels_path` (Task 4); `cfg.viewers.epochencoder` (Task 1).
- Produces: `plan_views(...)` returns a trailing `ViewPlan(name="annotations", viewer_type="epochencoder", params=viewer_defaults["epochencoder"], source=<CsvEpochSource>)`. `launch_block` needs no change — the existing first-bare / tabify-rest loop handles it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher.py` (near the other `plan_views` tests):

```python
def test_plan_views_always_appends_annotations(tmp_path, monkeypatch) -> None:
    # Even a session with no store attachments gets exactly one encoder plan,
    # and it creates the empty CSV under <block>/tdt_explore/.
    from ephyviewer import CsvEpochSource

    block_dir = tmp_path / "blk"
    block_dir.mkdir()
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(block="blk")
    plans = plan_views(block_dir, session, load_config())

    assert len(plans) == 1
    assert plans[-1].name == "annotations"
    assert plans[-1].viewer_type == "epochencoder"
    assert isinstance(plans[-1].source, CsvEpochSource)
    assert (block_dir / "tdt_explore" / "annotations.csv").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_launcher.py::test_plan_views_always_appends_annotations -v`
Expected: FAIL — `assert len(plans) == 1` fails (`0 != 1`); no annotations plan appended.

- [ ] **Step 3: Append the encoder plan in `plan_views`**

Edit `src/tdt_ephyviewer_explorer/launcher.py`. Add the import (with the other package imports):

```python
from tdt_ephyviewer_explorer.annotations import (
    DEFAULT_CHANNEL_NAME,
    build_annotation_source,
    resolve_labels_path,
)
```

In `plan_views`, after the impedance loop and before `return plans`, append the encoder plan unconditionally:

```python
    # Always-on writable annotation encoder, one per launched block.
    labels_path = resolve_labels_path(cfg, session.annotations_labels_path)
    plans.append(
        ViewPlan(
            name=DEFAULT_CHANNEL_NAME,
            viewer_type="epochencoder",
            params=dict(viewer_defaults.get("epochencoder", {})),
            source=build_annotation_source(block_path, labels_path, cfg),
        )
    )
    return plans
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `uv run pytest tests/test_launcher.py::test_plan_views_always_appends_annotations -v`
Expected: PASS.

- [ ] **Step 5: Update existing `plan_views` tests for the extra plan**

Running the full `test_launcher.py` now fails several older tests, because every `plan_views` call gains a trailing annotations plan (and, for fake block paths, would do stray CSV I/O). Fix them:

In `_patch_block` (used by `test_plan_views_loads_store_once_for_multiple_viewers` and `test_plan_views_missing_store_raises`), add a stub so no real CSV is written for fake paths:

```python
def _patch_block(monkeypatch, loads):
    """Patch read_headers/scan_block/load_store so plan_views runs without real tdt."""
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        launcher_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("UDP1", "scalars", None, 1, None, 0.0, None)],
    )
    monkeypatch.setattr(
        launcher_mod, "build_annotation_source", lambda *a, **k: object()
    )

    def fake_load(block_path, name, headers=None):
        loads.append(name)
        return _FakeScalar()

    monkeypatch.setattr(launcher_mod, "load_store", fake_load)
```

In `test_plan_views_loads_store_once_for_multiple_viewers`, update the plan-name assertion to include the trailing annotations plan:

```python
    assert [p.name for p in plans] == ["UDP1:eventlist", "UDP1:spiketrain", "annotations"]
```

In `test_plan_views_parses_block_index_once` and `test_plan_views_uses_supplied_headers` (they patch `tdt.read_block` and use the fake path `Path("tank/blk")`), add the stub so plan_views does no CSV write:

```python
    monkeypatch.setattr(
        launcher_mod, "build_annotation_source", lambda *a, **k: object()
    )
```

In the three processed/impedance tests that assert `len(plans) == 1`
(`test_plan_views_builds_timeseries_from_processed_source` / the tagged-parquet
test at the `raw_data_mep:trace` assertion, `test_plan_views_builds_blob_less_timeseries_with_sampling_rate_override`,
and `test_plan_views_includes_impedance_sources`), the block dir is a real
`tmp_path`, so the real encoder source is built. Change each `assert len(plans) == 1`
to account for the appended plan and assert its identity — for example:

```python
    assert len(plans) == 2
    assert plans[0].name == "raw_data_mep:trace"      # unchanged first-plan checks
    assert plans[-1].viewer_type == "epochencoder"
```

Apply the same `len == 2` + `plans[-1].viewer_type == "epochencoder"` update to the
`manual_ts:trace` and `spinal:impedance` tests, keeping their existing `plans[0]`
assertions intact.

The two raising tests (`test_plan_views_missing_store_raises`,
`test_plan_views_missing_impedance_file_raises`) raise inside the store/impedance
loops before the append, so they need no change beyond the `_patch_block` stub
already added.

- [ ] **Step 6: Run the full launcher suite to verify all pass**

Run: `uv run pytest tests/test_launcher.py -v`
Expected: PASS (all tests, including the updated ones).

- [ ] **Step 7: Commit**

```bash
git add src/tdt_ephyviewer_explorer/launcher.py tests/test_launcher.py
git commit -m "feat(launcher): always append epoch-encoder annotation plan"
```

---

### Task 6: Control Window labels-path text box

Adds an editable `annotations_labels_path` field to the global group, threads it onto the built `Session` on launch/save, and writes it back on load. Deliverable: the chosen labels path round-trips through the GUI and saved sessions.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/control_window.py`
- Test: `tests/test_control_window.py` (create if absent)

**Interfaces:**
- Consumes: `annotations.resolve_labels_path` (Task 2); `Session.annotations_labels_path` (Task 4).
- Produces: no new public function; the global param group gains an `annotations_labels_path` child; `_on_launch`/`_on_save` set `session.annotations_labels_path`; `_apply_session` restores it.

- [ ] **Step 1: Write the failing test**

Create/append `tests/test_control_window.py`:

```python
"""Qt smoke tests for the Control Window annotations labels-path field."""
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.annotations import resolve_labels_path
from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.control_window import ControlWindow
from tdt_ephyviewer_explorer.session import Session


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_global_group_seeds_labels_path(qapp) -> None:
    cfg = load_config()
    win = ControlWindow(cfg=cfg)
    field = win._global_root.child("annotations_labels_path")
    assert field.value() == str(resolve_labels_path(cfg))


def test_launch_threads_labels_path_onto_session(qapp) -> None:
    cfg = load_config()
    win = ControlWindow(cfg=cfg)
    win._block_path = Path("tank") / "blk"  # bypass a real block load
    win._global_root.child("annotations_labels_path").setValue("/custom/labels.yaml")

    captured: list[Session] = []
    win.launch_requested.connect(captured.append)
    win._on_launch()

    assert captured and captured[0].annotations_labels_path == "/custom/labels.yaml"


def test_apply_session_restores_labels_path(qapp) -> None:
    cfg = load_config()
    win = ControlWindow(cfg=cfg)
    win._apply_session(Session(block="blk", annotations_labels_path="/from/session.yaml"))
    assert win._global_root.child("annotations_labels_path").value() == "/from/session.yaml"
```

Note: `test_launch_threads_labels_path_onto_session` sets `_block_path` directly and relies on `spec_to_session` returning an empty-attachment session (the store tree is empty), so `_on_launch` emits without a real block scan.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_control_window.py -v`
Expected: FAIL — `KeyError`/`Exception` from `child("annotations_labels_path")` (child does not exist).

- [ ] **Step 3: Add the field and thread it through**

Edit `src/tdt_ephyviewer_explorer/control_window.py`.

Add the import:

```python
from tdt_ephyviewer_explorer.annotations import resolve_labels_path
```

In `__init__`, extend the global group's children with the labels-path box, seeded from the resolved default:

```python
        self._global_root = Parameter.create(
            name="global",
            type="group",
            children=[
                {"name": "block", "type": "list", "limits": [], "value": None},
                {
                    "name": "annotations_labels_path",
                    "type": "str",
                    "value": str(resolve_labels_path(self._cfg)),
                },
            ],
        )
```

Add a small helper to read the field, and use it in `_on_launch` and `_on_save`
after building the session:

```python
    def _annotations_labels_path(self) -> str:
        """Current value of the global annotations labels-path box."""
        return str(self._global_root.child("annotations_labels_path").value())
```

In `_on_launch`, set the attribute on the built session before emitting:

```python
    def _on_launch(self) -> None:
        """Read tree state, build a Session, and emit launch_requested signal."""
        if self._block_path is None:
            return
        state = self._read_state()
        session = spec_to_session(self._block_path.name, state)
        session.annotations_labels_path = self._annotations_labels_path()
        self.launch_requested.emit(session)
```

In `_on_save`, set it the same way before persisting:

```python
        if ok and name:
            session = spec_to_session(self._block_path.name, self._read_state())
            session.annotations_labels_path = self._annotations_labels_path()
            save_session(session, self._block_path.parent, name)
```

In `_apply_session`, restore the field from a loaded session (add near the top of
the method, before the per-store loop):

```python
        if session.annotations_labels_path:
            self._global_root.child("annotations_labels_path").setValue(
                session.annotations_labels_path
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_control_window.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/control_window.py tests/test_control_window.py
git commit -m "feat(control-window): editable annotations labels-path box"
```

---

### Task 7: Full-suite verification

Confirms the feature integrates cleanly with no regressions. Deliverable: the entire suite passes.

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: PASS — all tests green (the one real-`tdt` test stays skipped unless `TDT_EXPLORE_TEST_BLOCK` is set).

- [ ] **Step 2: If anything fails, fix it before proceeding**

Follow superpowers:systematic-debugging for any failure — do not paper over it. Re-run `uv run pytest` until green, then commit any fixes.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A
git commit -m "test: fix regressions from epoch-encoder annotation support"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Covered by |
| --- | --- |
| §4 `annotations.py` (`load_labels`, `resolve_labels_path`, `annotations_csv_path`, `build_annotation_source`, `DEFAULT_CHANNEL_NAME`) | Task 2 |
| §5 Config `annotations` group + `labels.yaml` + `config.yaml` defaults | Task 1 |
| §6 `builders.py` `epochencoder` in `_VIEWER_CLASSES` | Task 3 |
| §7 `launcher.py` unconditional encoder plan; `config/viewer/default.yaml` `epochencoder: {}`; no `launch_block` change | Tasks 5 + 1 |
| §8 `Session.annotations_labels_path` + `load_session` | Task 4 |
| §9 Control Window global labels-path box; `_on_launch`/`_on_save`/`_apply_session` | Task 6 |
| §10 Tests (`test_annotations.py`, session round-trip, plan_views always yields annotations) | Tasks 2, 4, 5 |
| §11 Edge cases (empty time range acceptable; existing-CSV labels kept via `restrict=false`; raw files untouched) | `restrict_to_possible_labels: false` (Task 1); CSV-only write (Task 2) |

No spec section is left without a task.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" placeholders; every code step contains the actual content.

**3. Type consistency:** `build_annotation_source(block_path, labels_path, cfg)`, `resolve_labels_path(cfg, path=None)`, `annotations_csv_path(block_path, cfg)`, `load_labels(path)`, and `DEFAULT_CHANNEL_NAME` are used identically across Tasks 2, 5, and 6. `Session.annotations_labels_path: str | None` is consistent across Tasks 4, 5, 6. The launcher's `resolve_labels_path(cfg, session.annotations_labels_path)` matches the two-arg signature defined in Task 2 (the spec's one-arg `resolve_labels_path(cfg)` is preserved as the default-only call used by the Control Window in Task 6).
