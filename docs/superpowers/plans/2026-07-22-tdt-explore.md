# tdt-explore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A modular desktop app that lists a TDT block's data stores and lets the user compose synchronized ephyviewer viewers from them, driven by Hydra config presets.

**Architecture:** A Qt-free core library (config, data model, probe reorder, stim formatters, ephyviewer source/viewer builders, session persistence) with a thin pyqtgraph/PySide6 Control Window on top. Phase 1 delivers the tested core plus a CLI that can launch viewers from a session file; Phase 2 adds the interactive Control Window.

**Tech Stack:** Python 3.12+, ephyviewer (rdarie fork), tdt, PySide6, numpy, pandas, hydra-core, probeinterface, pytest.

## Global Constraints

- Python `>=3.12`; always run inside the venv (`.venv/Scripts/python.exe`). Never run python/pytest/pip outside it.
- Configuration via Hydra structured configs. No hardcoded hyperparameters — viewer defaults, role patterns, schemas live in `config/`.
- Strict type hints on all functions; reST docstrings.
- No hardcoded absolute paths in shipped code (test fixtures/env vars excepted).
- No silent failures — raise with actionable messages.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit. Follow tasks in order; run tests after each.
- ephyviewer source signatures (verified): `InMemoryAnalogSignalSource(signals, sample_rate, t_start, channel_names=None)` with `signals` shaped `(n_samples, n_channels)`; `InMemoryEventSource(all_events=[{name,time,label}])`; `InMemoryEpochSource(all_epochs=[{name,time,duration,label}])`; `InMemorySpikeSource(all_spikes=[{name,time}])`. Viewers take `(source=, name=)` via `**kargs`.
- Raw TDT stream `data` is shaped `(n_channels, n_samples)`; scalar `data` is `(n_params, n_events)`.

---

## Phase 1 — Core library

### Task 1: Dependencies + Hydra config

**Files:**
- Modify: `pyproject.toml`
- Create: `src/tdt_ephyviewer_explorer/config_schema.py`
- Create: `src/tdt_ephyviewer_explorer/config/config.yaml`
- Create: `src/tdt_ephyviewer_explorer/config/viewer/default.yaml`
- Create: `src/tdt_ephyviewer_explorer/config/roles/default.yaml`
- Create: `src/tdt_ephyviewer_explorer/config/schema/default.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(overrides: list[str] | None = None) -> omegaconf.DictConfig`. The returned config has keys `viewers: dict[str, dict]`, `roles: list[dict]` (each `{pattern, role, schema?, viewers?, formatter?}`), `schemas: dict[str, list[str]]`.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add `"probeinterface"` and `"pyqtgraph"` to `dependencies` (pyqtgraph is
used directly by the Control Window; it currently arrives only transitively via ephyviewer)
and register the console script:

```toml
[project.scripts]
tdt-explore = "tdt_ephyviewer_explorer.app:main"
```

Then sync: `.venv/Scripts/python.exe -m uv sync` (run from repo root).

- [ ] **Step 2: Write the config YAMLs**

`src/tdt_ephyviewer_explorer/config/config.yaml`:

```yaml
defaults:
  - viewer: default
  - roles: default
  - schema: default
  - _self_
```

`src/tdt_ephyviewer_explorer/config/viewer/default.yaml`:

```yaml
# @package _global_
viewers:
  trace:
    scale_mode: real_scale
    display_labels: true
    antialias: true
  timefreq:
    show_axis: true
  spectrogram: {}
  eventlist: {}
  spiketrain: {}
  epoch: {}
```

`src/tdt_ephyviewer_explorer/config/roles/default.yaml`:

```yaml
# @package _global_
# Ordered rules; first name-pattern match wins (fnmatch syntax).
roles:
  - pattern: "eS?p"
    role: stim
    schema: iz_param_names
    viewers: [eventlist, spiketrain]
    formatter:
      _target_: tdt_ephyviewer_explorer.formatters.iz_voice.IZVoiceFormatter
  - pattern: "StS*"
    role: snip
    viewers: [spiketrain]
```

`src/tdt_ephyviewer_explorer/config/schema/default.yaml`:

```yaml
# @package _global_
schemas:
  iz_param_names:
    - perA
    - countA
    - ampA
    - durA
    - delayA
    - chanA
    - perB
    - countB
    - ampB
    - durB
    - delayB
    - chanB
    - perC
    - countC
    - ampC
    - durC
    - delayC
    - chanC
    - perD
    - countD
    - ampD
    - durD
    - delayD
    - chanD
```

- [ ] **Step 3: Write the failing test**

`tests/test_config.py`:

```python
"""Tests for Hydra config loading."""
from tdt_ephyviewer_explorer.config_schema import load_config


def test_load_config_has_expected_groups() -> None:
    cfg = load_config()
    assert "trace" in cfg.viewers
    assert cfg.viewers.trace.scale_mode == "real_scale"
    assert any(r.role == "stim" for r in cfg.roles)
    assert len(cfg.schemas.iz_param_names) == 24
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: config_schema`.

- [ ] **Step 5: Implement `config_schema.py`**

```python
"""Hydra configuration loading for tdt-explore."""
from __future__ import annotations

from pathlib import Path

from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra
from omegaconf import DictConfig

CONFIG_DIR: Path = Path(__file__).parent / "config"


def load_config(overrides: list[str] | None = None) -> DictConfig:
    """Compose the packaged Hydra config.

    :param overrides: Hydra dotlist overrides (e.g. ``["viewers.trace.antialias=false"]``).
    :returns: The composed configuration.
    """
    GlobalHydra.instance().clear()
    with initialize_config_dir(version_base=None, config_dir=str(CONFIG_DIR)):
        return compose(config_name="config", overrides=overrides or [])
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/tdt_ephyviewer_explorer/config src/tdt_ephyviewer_explorer/config_schema.py tests/test_config.py
git commit -m "feat: add probeinterface dep and Hydra config layer"
```

---

### Task 2: Store model + header scan + block discovery

**Files:**
- Create: `src/tdt_ephyviewer_explorer/stores.py`
- Create: `src/tdt_ephyviewer_explorer/tank.py`
- Test: `tests/test_stores.py`
- Test: `tests/test_tank.py`

**Interfaces:**
- Produces: `StoreInfo` frozen dataclass with fields `name: str, tdt_type: str, fs: float | None, n_channels: int | None, n_samples: int | None, t_start: float, duration: float | None`.
- Produces: `store_info_from_header(name: str, store: Mapping | object) -> StoreInfo`.
- Produces: `tank.list_blocks(tank_dir: Path) -> list[Path]`.

- [ ] **Step 1: Write the failing test for `store_info_from_header`**

`tests/test_stores.py`:

```python
"""Tests for store header parsing."""
import numpy as np

from tdt_ephyviewer_explorer.stores import StoreInfo, store_info_from_header


def test_store_info_from_stream_header() -> None:
    fake = {
        "type_str": "streams",
        "fs": 24414.0625,
        "chan": np.array([8, 7, 6, 5, 4, 3, 2, 1]),
        "start_time": 0.0,
    }
    info = store_info_from_header("Wav1", fake)
    assert info == StoreInfo(
        name="Wav1",
        tdt_type="streams",
        fs=24414.0625,
        n_channels=8,
        n_samples=None,
        t_start=0.0,
        duration=None,
    )


def test_store_info_from_scalar_header() -> None:
    fake = {"type_str": "scalars", "chan": np.array([1])}
    info = store_info_from_header("eS1p", fake)
    assert info.tdt_type == "scalars"
    assert info.fs is None
    assert info.n_channels == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stores.py -v`
Expected: FAIL with `ModuleNotFoundError: stores`.

- [ ] **Step 3: Implement `stores.py` (partial — dataclass + header parse)**

```python
"""TDT store model, header parsing, and lazy loading."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class StoreInfo:
    """Lightweight description of one TDT store, from a header-only scan.

    :param name: Store code, e.g. ``"Wav1"``.
    :param tdt_type: tdt ``type_str``: ``streams``/``scalars``/``epocs``/``snips``.
    :param fs: Sample rate in Hz (streams/snips), else ``None``.
    :param n_channels: Channel count where derivable.
    :param n_samples: Sample count where derivable.
    :param t_start: Store start time in seconds (0.0 if unknown until load).
    :param duration: Duration in seconds where derivable.
    """

    name: str
    tdt_type: str
    fs: float | None
    n_channels: int | None
    n_samples: int | None
    t_start: float
    duration: float | None


def _get(store: Mapping[str, Any] | object, key: str) -> Any:
    """Read ``key`` from a dict-like or attribute-based tdt store object."""
    try:
        return store[key]  # type: ignore[index]
    except (KeyError, TypeError):
        return getattr(store, key, None)


def store_info_from_header(name: str, store: Mapping[str, Any] | object) -> StoreInfo:
    """Build a :class:`StoreInfo` from one header-scan store entry.

    :param name: Store code.
    :param store: A tdt header store (dict-like or attribute object).
    :returns: The parsed store description.
    """
    fs_raw = _get(store, "fs")
    fs = float(fs_raw) if fs_raw else None
    chan = _get(store, "chan")
    n_channels = int(np.unique(np.ravel(chan)).size) if chan is not None else None
    start = _get(store, "start_time")
    t_start = float(start) if start is not None else 0.0
    return StoreInfo(
        name=name,
        tdt_type=str(_get(store, "type_str")),
        fs=fs,
        n_channels=n_channels,
        n_samples=None,
        t_start=t_start,
        duration=None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stores.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for `list_blocks`**

`tests/test_tank.py`:

```python
"""Tests for tank/block discovery."""
from pathlib import Path

from tdt_ephyviewer_explorer.tank import list_blocks


def test_list_blocks_finds_dirs_with_tsq(tmp_path: Path) -> None:
    good = tmp_path / "blockA-1"
    good.mkdir()
    (good / "blockA-1.tsq").write_bytes(b"")
    empty = tmp_path / "not_a_block"
    empty.mkdir()
    (tmp_path / "loose.tsq").write_bytes(b"")  # not in a subdir

    blocks = list_blocks(tmp_path)
    assert blocks == [good]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tank.py -v`
Expected: FAIL with `ModuleNotFoundError: tank`.

- [ ] **Step 7: Implement `tank.py` (partial — discovery only)**

```python
"""Tank/block discovery and header scanning."""
from __future__ import annotations

from pathlib import Path


def list_blocks(tank_dir: Path) -> list[Path]:
    """List block directories inside a tank.

    A block directory is any immediate subdirectory containing a ``*.tsq`` file.

    :param tank_dir: Path to the Synapse tank directory.
    :returns: Sorted list of block directory paths.
    """
    return sorted(
        p for p in tank_dir.iterdir() if p.is_dir() and any(p.glob("*.tsq"))
    )
```

- [ ] **Step 8: Run test + commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stores.py tests/test_tank.py -v`
Expected: PASS.

```bash
git add src/tdt_ephyviewer_explorer/stores.py src/tdt_ephyviewer_explorer/tank.py tests/test_stores.py tests/test_tank.py
git commit -m "feat: store header model and block discovery"
```

---

### Task 3: Store-role resolution

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/stores.py`
- Test: `tests/test_stores.py`

**Interfaces:**
- Consumes: `StoreInfo` (Task 2); `load_config().roles` (Task 1).
- Produces: `RoleRule` dataclass `{pattern: str, role: str, schema: str | None, viewers: tuple[str, ...], formatter: dict | None}`.
- Produces: `ResolvedStore` dataclass `{info: StoreInfo, role: str, schema: str | None, viewers: tuple[str, ...], formatter: dict | None}`.
- Produces: `VALID_VIEWERS: dict[str, tuple[str, ...]]`, `TDT_TYPE_TO_ROLE: dict[str, str]`.
- Produces: `resolve_role(info: StoreInfo, rules: Sequence[RoleRule]) -> ResolvedStore`.
- Produces: `rules_from_config(cfg) -> list[RoleRule]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_stores.py`:

```python
from tdt_ephyviewer_explorer.stores import (
    RoleRule,
    resolve_role,
    rules_from_config,
)
from tdt_ephyviewer_explorer.config_schema import load_config


def _info(name: str, tdt_type: str) -> StoreInfo:
    return StoreInfo(name, tdt_type, None, 1, None, 0.0, None)


def test_resolve_role_matches_pattern() -> None:
    rules = [RoleRule("eS?p", "stim", "iz_param_names", ("eventlist",), {"_target_": "x"})]
    resolved = resolve_role(_info("eS1p", "scalars"), rules)
    assert resolved.role == "stim"
    assert resolved.schema == "iz_param_names"
    assert resolved.viewers == ("eventlist",)


def test_resolve_role_falls_back_to_tdt_type() -> None:
    resolved = resolve_role(_info("Wav1", "streams"), [])
    assert resolved.role == "timeseries"
    assert resolved.viewers == ("trace", "timefreq", "spectrogram")


def test_rules_from_config_reads_packaged_rules() -> None:
    rules = rules_from_config(load_config())
    assert any(r.role == "snip" for r in rules)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stores.py -v`
Expected: FAIL with `ImportError: cannot import name 'RoleRule'`.

- [ ] **Step 3: Implement role resolution in `stores.py`**

Add these imports at the top of `stores.py`: `from fnmatch import fnmatchcase` and `from typing import Sequence`. Append:

```python
VALID_VIEWERS: dict[str, tuple[str, ...]] = {
    "timeseries": ("trace", "timefreq", "spectrogram"),
    "stim": ("eventlist", "spiketrain"),
    "event": ("eventlist", "spiketrain"),
    "epoch": ("eventlist", "epoch", "spiketrain"),
    "snip": ("spiketrain",),
}

TDT_TYPE_TO_ROLE: dict[str, str] = {
    "streams": "timeseries",
    "scalars": "event",
    "epocs": "epoch",
    "snips": "snip",
}


@dataclass(frozen=True)
class RoleRule:
    """A name-pattern rule mapping a store to a semantic role.

    :param pattern: fnmatch pattern tested against the store name.
    :param role: Semantic role (key of :data:`VALID_VIEWERS`).
    :param schema: Named column schema, or ``None``.
    :param viewers: Allowed viewer types; empty means use the role default.
    :param formatter: Hydra ``_target_`` spec for a stim formatter, or ``None``.
    """

    pattern: str
    role: str
    schema: str | None = None
    viewers: tuple[str, ...] = ()
    formatter: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResolvedStore:
    """A store with its resolved role and viewer options."""

    info: StoreInfo
    role: str
    schema: str | None
    viewers: tuple[str, ...]
    formatter: dict[str, Any] | None


def rules_from_config(cfg: Any) -> list[RoleRule]:
    """Convert the ``roles`` list of a composed config into :class:`RoleRule` objects."""
    rules: list[RoleRule] = []
    for r in cfg.roles:
        rules.append(
            RoleRule(
                pattern=str(r.pattern),
                role=str(r.role),
                schema=str(r.schema) if r.get("schema") is not None else None,
                viewers=tuple(r.get("viewers") or ()),
                formatter=dict(r.formatter) if r.get("formatter") is not None else None,
            )
        )
    return rules


def resolve_role(info: StoreInfo, rules: Sequence[RoleRule]) -> ResolvedStore:
    """Resolve a store's semantic role via name patterns, falling back to its tdt type.

    :param info: The store description.
    :param rules: Ordered role rules; first match wins.
    :returns: The resolved store with role, schema, viewers, and formatter.
    :raises KeyError: If the tdt type is unknown and no rule matches.
    """
    for rule in rules:
        if fnmatchcase(info.name, rule.pattern):
            viewers = rule.viewers or VALID_VIEWERS[rule.role]
            return ResolvedStore(info, rule.role, rule.schema, viewers, rule.formatter)
    role = TDT_TYPE_TO_ROLE[info.tdt_type]
    return ResolvedStore(info, role, None, VALID_VIEWERS[role], None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_stores.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/stores.py tests/test_stores.py
git commit -m "feat: config-driven store-role resolution"
```

---

### Task 4: Probe loading + channel reorder

**Files:**
- Create: `src/tdt_ephyviewer_explorer/probe.py`
- Test: `tests/test_probe.py`
- Test fixture: `tests/fixtures/probe_4ch.json`

**Interfaces:**
- Produces: `ProbeMap` frozen dataclass `{order: np.ndarray, names: list[str]}`.
- Produces: `load_probe(path: Path) -> ProbeMap`.
- Produces: `reorder_channels(data: np.ndarray, probe: ProbeMap) -> np.ndarray` (input `data` shaped `(n_channels, n_samples)`; returns rows permuted into contact order).

- [ ] **Step 1: Create the fixture**

`tests/fixtures/probe_4ch.json`:

```json
{
  "specification": "probeinterface",
  "version": "0.3.2",
  "probes": [
    {
      "ndim": 2,
      "si_units": "um",
      "annotations": {},
      "contact_annotations": {"brain_region": ["A", "B", "C", "D"]},
      "contact_positions": [[0, 0], [0, 100], [0, 200], [0, 300]],
      "contact_shapes": ["circle", "circle", "circle", "circle"],
      "contact_shape_params": [{"radius": 5}, {"radius": 5}, {"radius": 5}, {"radius": 5}],
      "device_channel_indices": [3, 2, 1, 0],
      "contact_ids": ["00", "01", "02", "03"],
      "shank_ids": ["0", "0", "0", "0"]
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

`tests/test_probe.py`:

```python
"""Tests for probe loading and channel reordering."""
from pathlib import Path

import numpy as np
import pytest

from tdt_ephyviewer_explorer.probe import ProbeMap, load_probe, reorder_channels

FIXTURE = Path(__file__).parent / "fixtures" / "probe_4ch.json"


def test_load_probe_reads_order_and_names() -> None:
    probe = load_probe(FIXTURE)
    assert list(probe.order) == [3, 2, 1, 0]
    assert probe.names == ["A 00", "B 01", "C 02", "D 03"]


def test_reorder_channels_permutes_rows() -> None:
    probe = load_probe(FIXTURE)
    data = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])  # channel i has value i
    out = reorder_channels(data, probe)
    assert list(out[:, 0]) == [3, 2, 1, 0]


def test_reorder_channels_count_mismatch_raises() -> None:
    probe = load_probe(FIXTURE)
    with pytest.raises(ValueError, match="channel count"):
        reorder_channels(np.zeros((3, 10)), probe)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_probe.py -v`
Expected: FAIL with `ModuleNotFoundError: probe`.

- [ ] **Step 4: Implement `probe.py`**

```python
"""Probe loading (probeinterface) and probe-native channel reordering."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from probeinterface import read_probeinterface


@dataclass(frozen=True)
class ProbeMap:
    """Channel reordering map derived from a probeinterface file.

    :param order: For displayed channel ``k``, the raw acquisition channel index
        (``device_channel_indices`` in contact order).
    :param names: Display name per contact-ordered channel.
    """

    order: np.ndarray
    names: list[str]


def load_probe(path: Path) -> ProbeMap:
    """Load the first probe from a probeinterface JSON file.

    :param path: Path to the ``.json`` probe file.
    :returns: The reorder map and per-channel names.
    """
    group = read_probeinterface(str(path))
    probe = group.probes[0]
    order = np.asarray(probe.device_channel_indices, dtype=int)
    regions = probe.contact_annotations.get("brain_region")
    ids = probe.contact_ids
    if regions is not None and ids is not None:
        names = [f"{r} {i}" for r, i in zip(regions, ids)]
    elif ids is not None:
        names = [str(i) for i in ids]
    else:
        names = [f"ch{k:0>2d}" for k in range(order.size)]
    return ProbeMap(order=order, names=names)


def reorder_channels(data: np.ndarray, probe: ProbeMap) -> np.ndarray:
    """Reorder a ``(n_channels, n_samples)`` array into probe-native contact order.

    :param data: Raw acquisition-order signal, channels along axis 0.
    :param probe: The probe reorder map.
    :returns: A view/copy with rows permuted so row ``k`` = raw channel ``order[k]``.
    :raises ValueError: If the probe contact count does not match the channel count.
    """
    if data.shape[0] != probe.order.size:
        raise ValueError(
            f"probe channel count {probe.order.size} != stream channel count {data.shape[0]}"
        )
    return data[probe.order, :]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_probe.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/probe.py tests/test_probe.py tests/fixtures/probe_4ch.json
git commit -m "feat: probeinterface loading and probe-native reorder"
```

---

### Task 5: Stim formatters

**Files:**
- Create: `src/tdt_ephyviewer_explorer/formatters/__init__.py`
- Create: `src/tdt_ephyviewer_explorer/formatters/base.py`
- Create: `src/tdt_ephyviewer_explorer/formatters/iz_voice.py`
- Test: `tests/test_formatters.py`

**Interfaces:**
- Produces: `StimFormatter` Protocol with `format_row(row: Mapping[str, Any]) -> str`.
- Produces: `GenericFormatter(columns: Sequence[str])`.
- Produces: `IZVoiceFormatter(voices: Sequence[str] = ("A","B","C","D"), amp_units: str = "uA")`.

- [ ] **Step 1: Write the failing test**

`tests/test_formatters.py`:

```python
"""Tests for stim-metadata label formatters."""
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter
from tdt_ephyviewer_explorer.formatters.iz_voice import IZVoiceFormatter


def test_generic_formatter_lists_columns() -> None:
    fmt = GenericFormatter(["a", "b"])
    assert fmt.format_row({"a": 1, "b": 2}) == "a: 1\nb: 2"


def test_iz_voice_formatter_skips_inactive_channels() -> None:
    fmt = IZVoiceFormatter()
    row = {"chanA": 5, "ampA": 100, "chanB": 0, "ampB": 0,
           "chanC": 0, "ampC": 0, "chanD": 0, "ampD": 0}
    assert fmt.format_row(row) == "chA: 05 100 uA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_formatters.py -v`
Expected: FAIL with `ModuleNotFoundError: formatters`.

- [ ] **Step 3: Implement the formatter modules**

`src/tdt_ephyviewer_explorer/formatters/__init__.py`:

```python
"""Stim-metadata label formatters."""
```

`src/tdt_ephyviewer_explorer/formatters/base.py`:

```python
"""Formatter protocol and a generic column-listing formatter."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class StimFormatter(Protocol):
    """Turns one stim/event parameter row into a display label."""

    def format_row(self, row: Mapping[str, Any]) -> str:
        """Return the label string for ``row``."""
        ...


class GenericFormatter:
    """Lists ``name: value`` for each configured column, one per line."""

    def __init__(self, columns: Sequence[str]) -> None:
        """:param columns: Column names to render, in order."""
        self._columns = list(columns)

    def format_row(self, row: Mapping[str, Any]) -> str:
        return "\n".join(f"{c}: {row[c]}" for c in self._columns)
```

`src/tdt_ephyviewer_explorer/formatters/iz_voice.py`:

```python
"""IZ multi-voice stim formatter (port of the reference chan_formatter)."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


class IZVoiceFormatter:
    """Renders active A/B/C/D stim voices as ``chX: NN amp units`` lines."""

    def __init__(
        self, voices: Sequence[str] = ("A", "B", "C", "D"), amp_units: str = "uA"
    ) -> None:
        """:param voices: Voice suffixes to inspect.
        :param amp_units: Amplitude unit label."""
        self._voices = list(voices)
        self._amp_units = amp_units

    def format_row(self, row: Mapping[str, Any]) -> str:
        parts: list[str] = []
        for v in self._voices:
            ch = int(row[f"chan{v}"])
            if ch > 0:
                amp = row[f"amp{v}"]
                parts.append(f"ch{v}: {ch:0>2d} {amp} {self._amp_units}")
        return "\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_formatters.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/formatters tests/test_formatters.py
git commit -m "feat: generic and IZ-voice stim formatters"
```

---

### Task 6: Attachment model + analog source builder

**Files:**
- Create: `src/tdt_ephyviewer_explorer/builders.py`
- Test: `tests/test_builders.py`

**Interfaces:**
- Consumes: `ProbeMap`, `reorder_channels` (Task 4).
- Produces: `Attachment` dataclass `{viewer_type: str, delay_samples: int = 0, probe_path: Path | None = None, params: dict = {}}`.
- Produces: `apply_delay(t_start: float, delay_samples: int, fs: float) -> float`.
- Produces: `build_analog_source(store: object, attachment: Attachment, probe: ProbeMap | None) -> InMemoryAnalogSignalSource`. `store` must expose `.data (n_channels, n_samples)`, `.fs`, `.start_time`.

- [ ] **Step 1: Write the failing test**

`tests/test_builders.py`:

```python
"""Tests for ephyviewer source builders (Qt-free)."""
from dataclasses import dataclass

import numpy as np

from tdt_ephyviewer_explorer.builders import (
    Attachment,
    apply_delay,
    build_analog_source,
)
from tdt_ephyviewer_explorer.probe import ProbeMap


@dataclass
class FakeStream:
    data: np.ndarray
    fs: float
    start_time: float


def test_apply_delay_converts_samples_to_seconds() -> None:
    assert apply_delay(1.0, 20, 1000.0) == 1.02


def test_build_analog_source_shapes_and_tstart() -> None:
    store = FakeStream(data=np.zeros((4, 100)), fs=1000.0, start_time=0.5)
    src = build_analog_source(store, Attachment("trace", delay_samples=10), probe=None)
    assert src.signals.shape == (100, 4)  # samples x channels
    assert src.t_start == 0.51


def test_build_analog_source_applies_probe_reorder_and_names() -> None:
    store = FakeStream(data=np.array([[0.0], [1.0], [2.0], [3.0]]), fs=1000.0, start_time=0.0)
    probe = ProbeMap(order=np.array([3, 2, 1, 0]), names=["w", "x", "y", "z"])
    src = build_analog_source(store, Attachment("trace"), probe=probe)
    assert list(src.signals[0, :]) == [3.0, 2.0, 1.0, 0.0]
    assert src.channel_names == ["w", "x", "y", "z"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_builders.py -v`
Expected: FAIL with `ModuleNotFoundError: builders`.

- [ ] **Step 3: Implement `builders.py` (partial — analog)**

```python
"""Build ephyviewer sources (and viewers) from loaded TDT stores."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from ephyviewer import InMemoryAnalogSignalSource

from tdt_ephyviewer_explorer.probe import ProbeMap, reorder_channels


@dataclass
class Attachment:
    """One viewer attached to one store, with alignment options.

    :param viewer_type: Viewer key (e.g. ``"trace"``).
    :param delay_samples: Samples added to the store's start time.
    :param probe_path: Optional probe file for reorder (timeseries only).
    :param params: Viewer parameter overrides.
    """

    viewer_type: str
    delay_samples: int = 0
    probe_path: Path | None = None
    params: dict = field(default_factory=dict)


def apply_delay(t_start: float, delay_samples: int, fs: float) -> float:
    """Shift ``t_start`` by ``delay_samples / fs`` seconds."""
    return float(t_start) + delay_samples / fs


def build_analog_source(
    store: object, attachment: Attachment, probe: ProbeMap | None
) -> InMemoryAnalogSignalSource:
    """Build an analog source from a stream store, applying delay and optional reorder.

    :param store: Loaded stream store exposing ``data`` (n_channels, n_samples), ``fs``,
        ``start_time``.
    :param attachment: Alignment and probe options.
    :param probe: Loaded probe map, or ``None`` for acquisition order.
    :returns: The configured in-memory analog source.
    """
    data: np.ndarray = np.asarray(store.data)  # type: ignore[attr-defined]
    fs: float = float(store.fs)  # type: ignore[attr-defined]
    if probe is not None:
        data = reorder_channels(data, probe)
        names = probe.names
    else:
        names = [f"ch{k:0>2d}" for k in range(data.shape[0])]
    signals = np.ascontiguousarray(data.T)  # samples x channels
    t_start = apply_delay(store.start_time, attachment.delay_samples, fs)  # type: ignore[attr-defined]
    return InMemoryAnalogSignalSource(signals, fs, t_start=t_start, channel_names=names)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_builders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/builders.py tests/test_builders.py
git commit -m "feat: analog source builder with delay and probe reorder"
```

---

### Task 7: Event / epoch / snip source builders

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/builders.py`
- Test: `tests/test_builders.py`

**Interfaces:**
- Consumes: `Attachment`, `apply_delay` (Task 6); `StimFormatter`, `GenericFormatter` (Task 5).
- Produces: `scalar_rows(store: object, columns: Sequence[str]) -> list[dict]` — turns scalar `data (n_params, n_events)` + `columns` into per-event dicts.
- Produces: `build_event_source(store, columns, formatter, attachment) -> InMemoryEventSource`.
- Produces: `build_epoch_source(store, attachment) -> InMemoryEpochSource`.
- Produces: `build_spike_source(store, attachment, group_fields=("chan","sortcode")) -> InMemorySpikeSource`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_builders.py`:

```python
from dataclasses import dataclass as _dc

from tdt_ephyviewer_explorer.builders import (
    build_epoch_source,
    build_event_source,
    build_spike_source,
    scalar_rows,
)
from tdt_ephyviewer_explorer.formatters.iz_voice import IZVoiceFormatter


@_dc
class FakeScalar:
    data: np.ndarray
    ts: np.ndarray


def test_scalar_rows_zips_columns() -> None:
    store = FakeScalar(data=np.array([[5, 6], [10, 20]]), ts=np.array([0.0, 1.0]))
    rows = scalar_rows(store, ["chanA", "ampA"])
    assert rows == [{"chanA": 5, "ampA": 10}, {"chanA": 6, "ampA": 20}]


def test_build_event_source_uses_formatter_and_delay() -> None:
    store = FakeScalar(
        data=np.array([[5, 0], [0, 0], [0, 0], [0, 0],  # chanA, chanB, chanC, chanD
                       [100, 0], [0, 0], [0, 0], [0, 0]]),  # ampA..ampD
        ts=np.array([2.0]),
    )
    cols = ["chanA", "chanB", "chanC", "chanD", "ampA", "ampB", "ampC", "ampD"]
    src = build_event_source(store, cols, IZVoiceFormatter(), Attachment("eventlist"))
    ev = src.all[0]  # ephyviewer stores channel dicts under `.all`
    assert ev["label"][0] == "chA: 05 100 uA"
    assert ev["time"][0] == 2.0


@_dc
class FakeEpoc:
    onset: np.ndarray
    offset: np.ndarray


def test_build_epoch_source_computes_duration() -> None:
    store = FakeEpoc(onset=np.array([1.0, 3.0]), offset=np.array([1.5, 3.25]))
    src = build_epoch_source(store, Attachment("epoch"))
    ep = src.all[0]
    assert list(ep["time"]) == [1.0, 3.0]
    assert list(np.round(ep["duration"], 2)) == [0.5, 0.25]


@_dc
class FakeSnip:
    ts: np.ndarray
    chan: np.ndarray
    sortcode: np.ndarray


def test_build_spike_source_groups_by_chan_sortcode() -> None:
    store = FakeSnip(
        ts=np.array([0.1, 0.2, 0.3]),
        chan=np.array([1, 1, 2]),
        sortcode=np.array([1, 1, 1]),
    )
    src = build_spike_source(store, Attachment("spiketrain"))
    names = sorted(s["name"] for s in src.all)
    assert names == ["ch01 u01", "ch02 u01"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_builders.py -v`
Expected: FAIL with `ImportError: cannot import name 'scalar_rows'`.

- [ ] **Step 3: Implement the event/epoch/snip builders in `builders.py`**

Add imports at the top: `from typing import Sequence` and extend the ephyviewer import to
`from ephyviewer import (InMemoryAnalogSignalSource, InMemoryEpochSource, InMemoryEventSource, InMemorySpikeSource)`.
Also add `from tdt_ephyviewer_explorer.formatters.base import StimFormatter`. Append:

```python
def scalar_rows(store: object, columns: Sequence[str]) -> list[dict]:
    """Turn a scalar store's ``data (n_params, n_events)`` into per-event dicts.

    :param store: Scalar store exposing ``data``.
    :param columns: Column names, one per param row (length must match ``data`` rows).
    :returns: One dict per event, mapping column name to value.
    :raises ValueError: If ``columns`` length does not match the number of param rows.
    """
    data = np.asarray(store.data)  # type: ignore[attr-defined]
    if data.ndim == 1:
        data = data[np.newaxis, :]
    if len(columns) != data.shape[0]:
        raise ValueError(
            f"schema has {len(columns)} columns but store has {data.shape[0]} param rows"
        )
    return [
        {col: data[p, i] for p, col in enumerate(columns)}
        for i in range(data.shape[1])
    ]


def build_event_source(
    store: object,
    columns: Sequence[str],
    formatter: StimFormatter,
    attachment: Attachment,
) -> InMemoryEventSource:
    """Build an event source from a scalar store using ``formatter`` for labels.

    :param store: Scalar store exposing ``data`` and ``ts``.
    :param columns: Column schema for the param rows.
    :param formatter: Row-to-label formatter.
    :param attachment: Alignment options (delay in samples; requires ``fs`` on the store
        for conversion, else delay is treated as seconds when ``fs`` is absent).
    """
    rows = scalar_rows(store, columns)
    labels = np.array([formatter.format_row(r) for r in rows])
    ts = np.asarray(store.ts, dtype=float)  # type: ignore[attr-defined]
    fs = getattr(store, "fs", None)
    if attachment.delay_samples and fs:
        ts = ts + attachment.delay_samples / float(fs)
    return InMemoryEventSource(
        all_events=[{"name": attachment.viewer_type, "time": ts, "label": labels}]
    )


def build_epoch_source(store: object, attachment: Attachment) -> InMemoryEpochSource:
    """Build an epoch source from an epoc store (onset/offset).

    :param store: Epoc store exposing ``onset`` and ``offset``.
    :param attachment: Alignment options.
    """
    onset = np.asarray(store.onset, dtype=float)  # type: ignore[attr-defined]
    offset = np.asarray(store.offset, dtype=float)  # type: ignore[attr-defined]
    duration = offset - onset
    labels = np.array([str(i) for i in range(onset.size)])
    return InMemoryEpochSource(
        all_epochs=[
            {"name": attachment.viewer_type, "time": onset, "duration": duration, "label": labels}
        ]
    )


def build_spike_source(
    store: object,
    attachment: Attachment,
    group_fields: Sequence[str] = ("chan", "sortcode"),
) -> InMemorySpikeSource:
    """Build a spike source from a snip/event store, one train per (chan, sortcode) group.

    Fields absent on the store are dropped from the grouping. If no grouping field is
    present, all timestamps form a single train.

    :param store: Store exposing ``ts`` and optionally ``chan``/``sortcode``.
    :param attachment: Alignment options.
    :param group_fields: Ordered grouping fields to try.
    """
    ts = np.asarray(store.ts, dtype=float)  # type: ignore[attr-defined]
    present = [f for f in group_fields if getattr(store, f, None) is not None]
    if not present:
        return InMemorySpikeSource(all_spikes=[{"name": attachment.viewer_type, "time": ts}])
    arrays = {f: np.asarray(getattr(store, f)).ravel() for f in present}
    keys = list(zip(*(arrays[f] for f in present)))
    spikes: list[dict] = []
    for key in sorted(set(keys)):
        mask = np.array([k == key for k in keys])
        label = " ".join(
            f"{'ch' if f == 'chan' else 'u'}{int(v):0>2d}" for f, v in zip(present, key)
        )
        spikes.append({"name": label, "time": ts[mask]})
    return InMemorySpikeSource(all_spikes=spikes)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_builders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/builders.py tests/test_builders.py
git commit -m "feat: event, epoch, and snip source builders"
```

---

### Task 8: Session persistence

**Files:**
- Create: `src/tdt_ephyviewer_explorer/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Produces: `Session` dataclass `{block: str, attachments: dict[str, list[dict]]}` where the outer key is a store name and each dict is a serialized `Attachment`.
- Produces: `save_session(session: Session, tank_dir: Path, name: str) -> Path` → writes `<tank>/tdt_explore/sessions/<name>.yaml`.
- Produces: `load_session(path: Path) -> Session`.

- [ ] **Step 1: Write the failing test**

`tests/test_session.py`:

```python
"""Tests for session save/load."""
from pathlib import Path

from tdt_ephyviewer_explorer.session import Session, load_session, save_session


def test_session_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        attachments={
            "Wav1": [{"viewer_type": "trace", "delay_samples": 0, "probe_path": None, "params": {}}],
            "eS1p": [{"viewer_type": "eventlist", "delay_samples": 20, "probe_path": None, "params": {}}],
        },
    )
    out = save_session(session, tmp_path, "mysession")
    assert out == tmp_path / "tdt_explore" / "sessions" / "mysession.yaml"
    assert out.exists()
    loaded = load_session(out)
    assert loaded == session
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: session`.

- [ ] **Step 3: Implement `session.py`**

```python
"""Per-tank session persistence (composition state only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from omegaconf import OmegaConf


@dataclass
class Session:
    """A saved composition: which viewers are attached to which stores.

    :param block: Block directory name.
    :param attachments: Store name -> list of serialized attachment dicts.
    """

    block: str
    attachments: dict[str, list[dict]] = field(default_factory=dict)


def save_session(session: Session, tank_dir: Path, name: str) -> Path:
    """Write a session to ``<tank>/tdt_explore/sessions/<name>.yaml``.

    :param session: The session to persist.
    :param tank_dir: Tank directory (raw block dirs are never written to).
    :param name: Session file stem.
    :returns: The written file path.
    """
    out_dir = tank_dir / "tdt_explore" / "sessions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.yaml"
    OmegaConf.save(config=OmegaConf.create(asdict(session)), f=out)
    return out


def load_session(path: Path) -> Session:
    """Load a session YAML written by :func:`save_session`."""
    cfg = OmegaConf.load(path)
    container = OmegaConf.to_container(cfg, resolve=True)
    assert isinstance(container, dict)
    return Session(block=container["block"], attachments=container["attachments"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/session.py tests/test_session.py
git commit -m "feat: per-tank session save/load"
```

---

### Task 9: TDT loaders + integration smoke test

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/tank.py`
- Modify: `src/tdt_ephyviewer_explorer/stores.py`
- Test: `tests/test_integration_tdt.py`

**Interfaces:**
- Produces: `tank.scan_block(block_path: Path) -> list[StoreInfo]`.
- Produces: `stores.load_store(block_path: Path, name: str) -> object` — the raw tdt store object for one store.

- [ ] **Step 1: Implement `scan_block` in `tank.py`**

Add `import tdt` and `from tdt_ephyviewer_explorer.stores import StoreInfo, store_info_from_header` at the top of `tank.py`, then append:

```python
def scan_block(block_path: Path) -> list[StoreInfo]:
    """Header-only scan of a block, listing its stores without bulk data.

    :param block_path: Path to the block directory.
    :returns: One :class:`StoreInfo` per store.
    """
    hdr = tdt.read_block(str(block_path), headers=1)
    stores = hdr["stores"]
    return [store_info_from_header(name, stores[name]) for name in stores.keys()]
```

- [ ] **Step 2: Implement `load_store` in `stores.py`**

Add `import tdt` at the top of `stores.py`, then append:

```python
def load_store(block_path: Path, name: str) -> Any:
    """Load a single store's full data from a block.

    :param block_path: Path to the block directory.
    :param name: Store code to load.
    :returns: The raw tdt store object (from ``streams``/``scalars``/``epocs``/``snips``).
    :raises KeyError: If the store is not present in the block.
    """
    blk = tdt.read_block(str(block_path), store=[name])
    for group in ("streams", "scalars", "epocs", "snips"):
        section = blk.get(group)
        if section is not None and name in section.keys():
            return section[name]
    raise KeyError(f"store {name!r} not found in block {block_path}")
```

- [ ] **Step 3: Write the integration smoke test (skipped by default)**

`tests/test_integration_tdt.py`:

```python
"""Real-tdt smoke test. Set TDT_EXPLORE_TEST_BLOCK to a block dir to run."""
import os
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.stores import load_store
from tdt_ephyviewer_explorer.tank import scan_block

BLOCK = os.environ.get("TDT_EXPLORE_TEST_BLOCK")
pytestmark = pytest.mark.skipif(BLOCK is None, reason="TDT_EXPLORE_TEST_BLOCK not set")


def test_scan_and_load_roundtrip() -> None:
    block = Path(BLOCK)  # type: ignore[arg-type]
    infos = scan_block(block)
    assert infos, "expected at least one store"
    stream = next(i for i in infos if i.tdt_type == "streams")
    store = load_store(block, stream.name)
    assert store.data.ndim == 2
```

- [ ] **Step 4: Run the full suite (integration skips)**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: all prior tests PASS; `test_integration_tdt` SKIPPED.

Optional real check (from repo root):

```bash
TDT_EXPLORE_TEST_BLOCK="C:/TDT/Synapse/Tanks/cnn_gp_mep_all_udp_v2-260626-115952/rRew03-260626-131743" \
  .venv/Scripts/python.exe -m pytest tests/test_integration_tdt.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/tank.py src/tdt_ephyviewer_explorer/stores.py tests/test_integration_tdt.py
git commit -m "feat: tdt header scan and per-store loader"
```

> **Verify here:** When the real block is available, confirm `StS1` loads with waveform
> `data`, `sortcode`, and `chan`. If it lacks these, add a role rule reclassifying it as
> `event` instead of `snip` (spec §4.2).

---

## Phase 2 — Control Window GUI

### Task 10: Viewer builder + launcher

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/builders.py`
- Create: `src/tdt_ephyviewer_explorer/launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: all Task 6/7 source builders; `ResolvedStore` (Task 3); `Session` (Task 8); `load_store` (Task 9); `load_config`, `rules_from_config` (Tasks 1/3).
- Produces: `build_viewer(viewer_type: str, source: object, name: str, params: dict) -> ViewerBase`.
- Produces: `build_source_for(resolved: ResolvedStore, attachment: Attachment, store: object, schemas: dict) -> object` — dispatches to the right source builder by viewer type.
- Produces: `launcher.launch_block(block_path: Path, session: Session, cfg) -> MainViewer`.

- [ ] **Step 1: Write the failing test (Qt smoke)**

`tests/test_launcher.py`:

```python
"""Qt smoke tests for viewer building and the block launcher."""
import numpy as np
import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.builders import Attachment, build_viewer, build_analog_source


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_build_viewer_returns_trace_viewer(qapp) -> None:
    class S:
        data = np.zeros((2, 50))
        fs = 1000.0
        start_time = 0.0

    src = build_analog_source(S(), Attachment("trace"), probe=None)
    view = build_viewer("trace", src, name="Wav1:trace", params={"display_labels": True})
    assert view.name == "Wav1:trace"
    assert view.params["display_labels"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launcher.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_viewer'`.

- [ ] **Step 3: Implement `build_viewer` + `build_source_for` in `builders.py`**

Extend the ephyviewer import to also bring in the viewers:
`from ephyviewer import (EpochViewer, EventList, InMemoryAnalogSignalSource, InMemoryEpochSource, InMemoryEventSource, InMemorySpikeSource, SpectrogramViewer, SpikeTrainViewer, TimeFreqViewer, TraceViewer)`.
Add `from hydra.utils import instantiate` and `from tdt_ephyviewer_explorer.formatters.base import GenericFormatter`, `from tdt_ephyviewer_explorer.probe import load_probe`, `from tdt_ephyviewer_explorer.stores import ResolvedStore`. Append:

```python
_VIEWER_CLASSES = {
    "trace": TraceViewer,
    "timefreq": TimeFreqViewer,
    "spectrogram": SpectrogramViewer,
    "eventlist": EventList,
    "spiketrain": SpikeTrainViewer,
    "epoch": EpochViewer,
}

_ANALOG_VIEWERS = frozenset({"trace", "timefreq", "spectrogram"})


def build_viewer(viewer_type: str, source: object, name: str, params: dict):
    """Construct an ephyviewer viewer and apply parameter overrides.

    :param viewer_type: Key into the viewer registry.
    :param source: A built ephyviewer source.
    :param name: Unique viewer name (dock key).
    :param params: Parameter overrides applied via ``view.params[key] = value``.
    :returns: The configured viewer.
    :raises KeyError: If ``viewer_type`` is unknown.
    """
    view = _VIEWER_CLASSES[viewer_type](source=source, name=name)
    for key, value in params.items():
        view.params[key] = value
    return view


def build_source_for(
    resolved: ResolvedStore, attachment: Attachment, store: object, schemas: dict
) -> object:
    """Dispatch to the correct source builder for one attachment.

    :param resolved: The resolved store (role, schema, formatter).
    :param attachment: The viewer attachment.
    :param store: The loaded raw tdt store.
    :param schemas: Mapping of schema name -> column list.
    :returns: An ephyviewer source.
    :raises ValueError: If the viewer type is not valid for the store's role.
    """
    vt = attachment.viewer_type
    if vt not in resolved.viewers:
        raise ValueError(f"viewer {vt!r} not valid for role {resolved.role!r}")
    if vt in _ANALOG_VIEWERS:
        probe = load_probe(attachment.probe_path) if attachment.probe_path else None
        return build_analog_source(store, attachment, probe)
    if resolved.role == "epoch":
        return build_epoch_source(store, attachment)
    if vt == "spiketrain":
        return build_spike_source(store, attachment)
    # eventlist on stim/event
    columns = list(schemas.get(resolved.schema, [])) if resolved.schema else []
    if not columns:
        n = int(np.asarray(store.data).shape[0])  # type: ignore[attr-defined]
        columns = [f"col{p:0>2d}" for p in range(n)]
    formatter = instantiate(resolved.formatter) if resolved.formatter else GenericFormatter(columns)
    return build_event_source(store, columns, formatter, attachment)
```

- [ ] **Step 4: Implement `launcher.py`**

```python
"""Launch a Block Window (MainViewer) from a session."""
from __future__ import annotations

from pathlib import Path

from ephyviewer import MainViewer
from omegaconf import OmegaConf

from tdt_ephyviewer_explorer.builders import Attachment, build_source_for, build_viewer
from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import load_store, resolve_role, rules_from_config
from tdt_ephyviewer_explorer.tank import scan_block


def _attachment_from_dict(d: dict) -> Attachment:
    probe = d.get("probe_path")
    return Attachment(
        viewer_type=d["viewer_type"],
        delay_samples=int(d.get("delay_samples", 0)),
        probe_path=Path(probe) if probe else None,
        params=dict(d.get("params", {})),
    )


def launch_block(block_path: Path, session: Session, cfg) -> MainViewer:
    """Build and populate a MainViewer for one block from a session.

    :param block_path: Block directory.
    :param session: The composition to realize.
    :param cfg: Composed Hydra config (viewers, roles, schemas).
    :returns: The populated (but not yet shown) MainViewer.
    """
    rules = rules_from_config(cfg)
    infos = {info.name: info for info in scan_block(block_path)}
    schemas = OmegaConf.to_container(cfg.schemas, resolve=True)
    viewer_defaults = OmegaConf.to_container(cfg.viewers, resolve=True)

    win = MainViewer(debug=False)
    win.setWindowTitle(block_path.name)
    first_name: str | None = None
    for store_name, attach_dicts in session.attachments.items():
        resolved = resolve_role(infos[store_name], rules)
        raw = load_store(block_path, store_name)
        for d in attach_dicts:
            attachment = _attachment_from_dict(d)
            source = build_source_for(resolved, attachment, raw, schemas)
            name = f"{store_name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            view = build_viewer(attachment.viewer_type, source, name, params)
            if first_name is None:
                win.add_view(view)
                first_name = name
            else:
                win.add_view(view, tabify_with=first_name)
    return win
```

- [ ] **Step 5: Run tests + commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_launcher.py -v`
Expected: PASS.

```bash
git add src/tdt_ephyviewer_explorer/builders.py src/tdt_ephyviewer_explorer/launcher.py tests/test_launcher.py
git commit -m "feat: viewer builder and block launcher"
```

---

### Task 11: Control-tree spec + Control Window

**Files:**
- Create: `src/tdt_ephyviewer_explorer/control_window.py`
- Test: `tests/test_control_window.py`

**Interfaces:**
- Consumes: `ResolvedStore` (Task 3); `load_config`, `rules_from_config`; `scan_block`.
- Produces: `build_param_tree_spec(resolved_stores: list[ResolvedStore], viewer_defaults: dict) -> list[dict]` — a pyqtgraph-parametertree-ready spec (pure, testable).
- Produces: `spec_to_session(block: str, param_state: dict) -> Session` — reads the tree's saved state into a `Session`.
- Produces: `ControlWindow(QWidget)` with `set_block(block_path: Path)` and signal `launch_requested`.

- [ ] **Step 1: Write the failing test for `build_param_tree_spec`**

`tests/test_control_window.py`:

```python
"""Tests for the control-tree spec and window."""
from tdt_ephyviewer_explorer.control_window import build_param_tree_spec
from tdt_ephyviewer_explorer.stores import ResolvedStore, StoreInfo


def _resolved(name: str, role: str, viewers: tuple[str, ...]) -> ResolvedStore:
    info = StoreInfo(name, "streams", 1000.0, 4, None, 0.0, None)
    return ResolvedStore(info, role, None, viewers, None)


def test_build_param_tree_spec_makes_group_per_store() -> None:
    spec = build_param_tree_spec(
        [_resolved("Wav1", "timeseries", ("trace", "timefreq"))], {"trace": {}, "timefreq": {}}
    )
    assert spec[0]["name"] == "Wav1"
    child_names = {c["name"] for c in spec[0]["children"]}
    assert "delay_samples" in child_names
    assert "probe_file" in child_names  # timeseries only
    viewers_group = next(c for c in spec[0]["children"] if c["name"] == "Viewers")
    assert {c["name"] for c in viewers_group["children"]} == {"trace", "timefreq"}


def test_build_param_tree_spec_omits_probe_for_events() -> None:
    spec = build_param_tree_spec(
        [_resolved("eS1p", "stim", ("eventlist",))], {"eventlist": {}}
    )
    child_names = {c["name"] for c in spec[0]["children"]}
    assert "probe_file" not in child_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_control_window.py -v`
Expected: FAIL with `ModuleNotFoundError: control_window`.

- [ ] **Step 3: Implement `build_param_tree_spec` + `spec_to_session` in `control_window.py`**

```python
"""The per-tank Control Window and its (pure) parameter-tree spec."""
from __future__ import annotations

from pathlib import Path

from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import ResolvedStore


def build_param_tree_spec(
    resolved_stores: list[ResolvedStore], viewer_defaults: dict
) -> list[dict]:
    """Build a pyqtgraph-parametertree spec: one group per store.

    :param resolved_stores: Stores with resolved roles.
    :param viewer_defaults: Per-viewer default params, seeded into viewer subgroups.
    :returns: A list of group-parameter dicts.
    """
    groups: list[dict] = []
    for rs in resolved_stores:
        children: list[dict] = [
            {"name": "role", "type": "str", "value": rs.role, "readonly": True},
            {"name": "fs", "type": "float", "value": rs.info.fs or 0.0, "readonly": True},
            {"name": "channels", "type": "int", "value": rs.info.n_channels or 0, "readonly": True},
            {"name": "delay_samples", "type": "int", "value": 0},
        ]
        if rs.role == "timeseries":
            children.append({"name": "probe_file", "type": "str", "value": ""})
            children.append({"name": "reorder", "type": "bool", "value": False})
        if rs.schema is not None:
            children.append(
                {"name": "schema", "type": "str", "value": rs.schema, "readonly": True}
            )
        viewer_children = [
            {"name": vt, "type": "bool", "value": False, "children": _params_children(
                viewer_defaults.get(vt, {})
            )}
            for vt in rs.viewers
        ]
        children.append({"name": "Viewers", "type": "group", "children": viewer_children})
        groups.append({"name": rs.info.name, "type": "group", "children": children})
    return groups


def _params_children(defaults: dict) -> list[dict]:
    """Turn a flat viewer-defaults dict into parametertree children."""
    out: list[dict] = []
    for key, value in defaults.items():
        ptype = {bool: "bool", int: "int", float: "float"}.get(type(value), "str")
        out.append({"name": key, "type": ptype, "value": value})
    return out


def spec_to_session(block: str, param_state: dict) -> Session:
    """Convert a saved parametertree state into a :class:`Session`.

    :param block: Block name.
    :param param_state: ``{store_name: {"delay_samples": int, "probe_file": str,
        "Viewers": {viewer_type: {"_enabled": bool, **params}}}}``.
    :returns: The composition session (only enabled viewers included).
    """
    attachments: dict[str, list[dict]] = {}
    for store_name, state in param_state.items():
        viewers = state.get("Viewers", {})
        entries: list[dict] = []
        probe = state.get("probe_file") or None
        for vt, vstate in viewers.items():
            if not vstate.get("_enabled"):
                continue
            params = {k: v for k, v in vstate.items() if k != "_enabled"}
            entries.append(
                {
                    "viewer_type": vt,
                    "delay_samples": int(state.get("delay_samples", 0)),
                    "probe_path": probe if state.get("reorder") else None,
                    "params": params,
                }
            )
        if entries:
            attachments[store_name] = entries
    return Session(block=block, attachments=attachments)
```

- [ ] **Step 4: Run the pure tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_control_window.py -v`
Expected: PASS.

- [ ] **Step 5: Add the `ControlWindow` widget**

Append to `control_window.py` (imports at top:
`from pyqtgraph.parametertree import Parameter, ParameterTree`,
`from PySide6 import QtWidgets`, `from PySide6.QtCore import Signal`,
`from tdt_ephyviewer_explorer.config_schema import load_config`,
`from tdt_ephyviewer_explorer.stores import resolve_role, rules_from_config`,
`from tdt_ephyviewer_explorer.tank import scan_block`,
`from omegaconf import OmegaConf`):

```python
class ControlWindow(QtWidgets.QWidget):
    """Per-tank control window: pick a block, compose viewers, launch."""

    launch_requested = Signal(object)  # emits a Session

    def __init__(self, cfg=None, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg if cfg is not None else load_config()
        self._rules = rules_from_config(self._cfg)
        self._viewer_defaults = OmegaConf.to_container(self._cfg.viewers, resolve=True)
        self._block_path: Path | None = None
        self._tree = ParameterTree()
        self._root = Parameter.create(name="stores", type="group", children=[])
        self._tree.setParameters(self._root, showTop=False)

        launch_btn = QtWidgets.QPushButton("Launch window")
        launch_btn.clicked.connect(self._on_launch)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._tree)
        layout.addWidget(launch_btn)

    def set_block(self, block_path: Path) -> None:
        """Scan a block and rebuild the parameter tree for it."""
        self._block_path = block_path
        resolved = [resolve_role(i, self._rules) for i in scan_block(block_path)]
        spec = build_param_tree_spec(resolved, self._viewer_defaults)
        self._root.clearChildren()
        self._root.addChildren(spec)

    def _on_launch(self) -> None:
        if self._block_path is None:
            return
        state = self._read_state()
        session = spec_to_session(self._block_path.name, state)
        self.launch_requested.emit(session)

    def _read_state(self) -> dict:
        """Read the current tree values into the shape expected by :func:`spec_to_session`."""
        out: dict = {}
        for store in self._root.children():
            s: dict = {}
            viewers: dict = {}
            for child in store.children():
                if child.name() == "Viewers":
                    for v in child.children():
                        params = {p.name(): p.value() for p in v.children()}
                        viewers[v.name()] = {"_enabled": v.value(), **params}
                else:
                    s[child.name()] = child.value()
            s["Viewers"] = viewers
            out[store.name()] = s
        return out
```

- [ ] **Step 6: Add a Qt smoke test**

Append to `tests/test_control_window.py`:

```python
import pytest

ephyviewer = pytest.importorskip("ephyviewer")


def test_spec_to_session_includes_only_enabled() -> None:
    from tdt_ephyviewer_explorer.control_window import spec_to_session

    state = {
        "Wav1": {
            "delay_samples": 5,
            "probe_file": "",
            "reorder": False,
            "Viewers": {"trace": {"_enabled": True, "display_labels": True},
                        "timefreq": {"_enabled": False}},
        }
    }
    session = spec_to_session("blk", state)
    assert list(session.attachments) == ["Wav1"]
    assert session.attachments["Wav1"][0]["viewer_type"] == "trace"
    assert session.attachments["Wav1"][0]["delay_samples"] == 5
```

- [ ] **Step 7: Run tests + commit**

Run: `.venv/Scripts/python.exe -m pytest tests/test_control_window.py -v`
Expected: PASS.

```bash
git add src/tdt_ephyviewer_explorer/control_window.py tests/test_control_window.py
git commit -m "feat: control window and parameter-tree composition"
```

---

### Task 12: App entry point + save/load wiring

**Files:**
- Create: `src/tdt_ephyviewer_explorer/app.py`
- Modify: `src/tdt_ephyviewer_explorer/control_window.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `ControlWindow` (Task 11); `launch_block` (Task 10); `list_blocks` (Task 2); `save_session`/`load_session` (Task 8).
- Produces: `app.main(argv: list[str] | None = None) -> int` — the `tdt-explore` entry point.
- Produces: `app.App` orchestrator holding the QApplication, ControlWindow, and open MainViewers.

- [ ] **Step 1: Write the failing test**

`tests/test_app.py`:

```python
"""Smoke tests for the app orchestrator."""
import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.app import App


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_app_constructs_control_window(qapp) -> None:
    app = App()
    assert app.control_window is not None
    assert app.windows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: app`.

- [ ] **Step 3: Implement `app.py`**

```python
"""tdt-explore application entry point and orchestrator."""
from __future__ import annotations

import argparse
from pathlib import Path

from ephyviewer import MainViewer, mkQApp

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.control_window import ControlWindow
from tdt_ephyviewer_explorer.launcher import launch_block
from tdt_ephyviewer_explorer.session import Session


class App:
    """Owns the control window and any open block windows."""

    def __init__(self, cfg=None) -> None:
        self._cfg = cfg if cfg is not None else load_config()
        self.control_window = ControlWindow(self._cfg)
        self.windows: list[MainViewer] = []
        self.control_window.launch_requested.connect(self._on_launch)

    def open_tank(self, tank_dir: Path, block: str | None = None) -> None:
        """Point the control window at a tank; optionally preselect a block."""
        self._tank_dir = tank_dir
        if block is not None:
            self.control_window.set_block(tank_dir / block)

    def _on_launch(self, session: Session) -> None:
        block_path = self._tank_dir / session.block
        win = launch_block(block_path, session, self._cfg)
        win.show()
        self.windows.append(win)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tdt-explore`` console script.

    :param argv: CLI args; ``--tank`` (required) and optional ``--block``.
    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(prog="tdt-explore")
    parser.add_argument("--tank", required=True, type=Path, help="Synapse tank directory")
    parser.add_argument("--block", default=None, help="Block name to preselect")
    args = parser.parse_args(argv)

    qapp = mkQApp()
    app = App()
    app.open_tank(args.tank, args.block)
    app.control_window.show()
    return int(qapp.exec())
```

- [ ] **Step 4: Add Save/Load buttons to `ControlWindow`**

In `control_window.py`, in `ControlWindow.__init__`, after the launch button, add:

```python
        save_btn = QtWidgets.QPushButton("Save session")
        save_btn.clicked.connect(self._on_save)
        load_btn = QtWidgets.QPushButton("Load session")
        load_btn.clicked.connect(self._on_load)
        layout.addWidget(save_btn)
        layout.addWidget(load_btn)
```

Add these methods to `ControlWindow` (imports at top:
`from tdt_ephyviewer_explorer.session import load_session, save_session, Session`):

```python
    def _on_save(self) -> None:
        if self._block_path is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save session", "Session name:")
        if ok and name:
            session = spec_to_session(self._block_path.name, self._read_state())
            save_session(session, self._block_path.parent, name)

    def _on_load(self) -> None:
        if self._block_path is None:
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load session", str(self._block_path.parent), "YAML (*.yaml)"
        )
        if path:
            session = load_session(Path(path))
            self._apply_session(session)

    def _apply_session(self, session: Session) -> None:
        """Set tree values from a loaded session (enabling the saved viewers)."""
        for store in self._root.children():
            entries = session.attachments.get(store.name(), [])
            by_type = {e["viewer_type"]: e for e in entries}
            for child in store.children():
                if child.name() == "Viewers":
                    for v in child.children():
                        entry = by_type.get(v.name())
                        v.setValue(entry is not None)
                        if entry:
                            for p in v.children():
                                if p.name() in entry["params"]:
                                    p.setValue(entry["params"][p.name()])
                elif child.name() == "delay_samples" and entries:
                    child.setValue(entries[0]["delay_samples"])
```

- [ ] **Step 5: Run tests + commit**

Run: `.venv/Scripts/python.exe -m pytest -v`
Expected: all PASS (integration SKIPPED).

```bash
git add src/tdt_ephyviewer_explorer/app.py src/tdt_ephyviewer_explorer/control_window.py tests/test_app.py
git commit -m "feat: tdt-explore entry point with save/load"
```

- [ ] **Step 6: Manual verification (real data)**

Run (from repo root):

```bash
.venv/Scripts/python.exe -m tdt_ephyviewer_explorer.app \
  --tank "C:/TDT/Synapse/Tanks/cnn_gp_mep_all_udp_v2-260626-115952" \
  --block "rRew03-260626-131743"
```

Expected: Control Window opens listing `Wav1/MonA/SU_1/eS1p/eS1r/UDP1/StS1/Tick`. Enable
`Wav1 → trace` and `eS1p → eventlist`, click **Launch window** — a MainViewer opens with the
trace and the stim event list, time-synchronized. Confirm the `StS1` snip verification note
from Task 9.

---

## Self-Review Notes

- **Spec coverage:** header scan+lazy load (T2, T9), store roles (T3), config presets (T1),
  control tree (T11), delays (T6/T7), probe reorder (T4/T6), stim formatters (T5), unknown
  columns → `col00…` placeholder (T10 `build_source_for`), snips (T7), sessions (T8),
  one-window-per-block launcher (T10), error handling (raises in T4/T7/T10), tests (all).
- **Deferred (spec §12):** MonA/eS1r special handling, snip waveform overlay, live window
  state persistence, promoting column names to presets, multi-store viewers — none implemented, by design.
- **Open verification:** `StS1` snip classification (flagged in T9).
