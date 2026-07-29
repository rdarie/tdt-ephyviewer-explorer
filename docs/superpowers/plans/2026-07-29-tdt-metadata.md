# tdt-metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tdt-metadata`, a second app in this repo that browses a Synapse tank and shows per-block duration, gizmos, notes, and an eStim pulse/parameter-combination summary, with an editable post-hoc annotation file.

**Architecture:** A Qt-free core (`metadata/listing.py`, `notes.py`, `stim.py`, `summary.py`, `textio.py`) that does all parsing and computation, plus a thin Qt shell (`metadata/window.py`, `notes_panel.py`). Reads are tiered: text metadata eagerly for every block, `.tsq` headers and `eS1p` data lazily on expand. A new shared `tank_picker.py` widget is adopted by both this app and the existing `tdt-explore`.

**Tech Stack:** Python 3.12+, PySide6, numpy, Hydra/OmegaConf, `tdt`, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-07-29-tdt-metadata-design.md`

## Global Constraints

- Always run Python through the venv: `uv run <cmd>`. Never bare `python`/`pytest`/`pip`.
- Strict type hints on every function and method.
- reST (`:param:`/`:returns:`/`:raises:`) docstrings on every public function, method, class, and module.
- No hardcoded paths, no magic numbers. Tunables go in `src/tdt_ephyviewer_explorer/config/`, never inline.
- No silent failures. Every degraded path records a warning string that reaches the UI.
- Only `<block>/analysis_notes.txt` may be written into a raw block directory. `Notes.txt`, `StoresListing.txt`, and all TDT binaries are read-only on every code path.
- Notes files are **CRLF** (`\r\n`) with a trailing newline, read as UTF-8 falling back to latin-1, always written as UTF-8.
- Qt-touching tests go behind `pytest.importorskip("ephyviewer")` with a module-scoped `qapp` fixture. Real-`tdt` tests are gated on the `TDT_EXPLORE_TEST_BLOCK` env var.
- Reference values, asserted in the integration test: block `Epi_02_Green-260727-154827` yields **15561 pulses** and **1881 unique combinations**. (Voice B is the return electrode — `countB == 0` for every event — and 438 events have `chanA == 0`, so they deliver nothing.)
- Never `git add` anything matched by `.gitignore`.

## File Structure

| File | Responsibility |
|---|---|
| `src/tdt_ephyviewer_explorer/tank_picker.py` | NEW. Shared Qt tank-directory picker. Validates, emits `tank_changed`. |
| `src/tdt_ephyviewer_explorer/app.py` | MODIFY. `--tank` optional; tank ownership moves to the control window. |
| `src/tdt_ephyviewer_explorer/control_window.py` | MODIFY. Hosts a `TankPicker`; exposes `tank_dir`; disables launch with no block. |
| `src/tdt_ephyviewer_explorer/metadata/textio.py` | NEW. Encoding-tolerant read, atomic write. |
| `src/tdt_ephyviewer_explorer/metadata/listing.py` | NEW. `StoresListing.txt` → `list[Gizmo]`. |
| `src/tdt_ephyviewer_explorer/metadata/notes.py` | NEW. Notes parse/render; `AnalysisNotes` editing model. |
| `src/tdt_ephyviewer_explorer/metadata/stim.py` | NEW. `eS1p` array → `StimSummary`. |
| `src/tdt_ephyviewer_explorer/metadata/summary.py` | NEW. `BlockSummary`, the three read tiers, `BlockCache`. |
| `src/tdt_ephyviewer_explorer/metadata/notes_panel.py` | NEW. Qt side-panel notes tables. |
| `src/tdt_ephyviewer_explorer/metadata/window.py` | NEW. Qt main window: picker, block tree, side panel. |
| `src/tdt_ephyviewer_explorer/metadata/app.py` | NEW. `tdt-metadata` console script. |
| `src/tdt_ephyviewer_explorer/config/metadata/default.yaml` | NEW. Hydra group for stim/notes settings. |

**Deviation from the spec's module tree:** the spec did not list `textio.py`. It exists because
`listing.py`, `notes.py`, and `summary.py` all need the same encoding-tolerant read, and
`notes.py` needs the atomic write. Six lines duplicated three ways is worse than one small module.

---

### Task 1: Shared TankPicker widget

**Files:**
- Create: `src/tdt_ephyviewer_explorer/tank_picker.py`
- Test: `tests/test_tank_picker.py`

**Interfaces:**
- Consumes: `tank.list_blocks(tank_dir: Path) -> list[Path]` (existing).
- Produces:
  - `TankPicker(parent: QtWidgets.QWidget | None = None)` — a `QWidget`.
  - `TankPicker.tank_changed` — `Signal(object)`, emits a `Path`.
  - `TankPicker.tank_dir` — `property -> Path | None`.
  - `TankPicker.set_tank(tank_dir: Path) -> bool` — validates, adopts, emits on success.
  - `TankPicker.show_tank(tank_dir: Path) -> None` — adopts without emitting.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tank_picker.py`:

```python
"""Tests for the shared tank-directory picker."""
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.tank_picker import TankPicker


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def _make_tank(tmp_path: Path) -> Path:
    tank = tmp_path / "tank"
    blk = tank / "blockA-1"
    blk.mkdir(parents=True)
    (blk / "blockA-1.tsq").write_bytes(b"")
    return tank


def test_set_tank_adopts_and_emits(qapp, tmp_path) -> None:
    picker = TankPicker()
    seen: list[Path] = []
    picker.tank_changed.connect(seen.append)
    tank = _make_tank(tmp_path)

    assert picker.set_tank(tank) is True
    assert picker.tank_dir == tank
    assert seen == [tank]


def test_set_tank_rejects_tank_with_no_blocks(qapp, tmp_path) -> None:
    picker = TankPicker()
    seen: list[Path] = []
    picker.tank_changed.connect(seen.append)
    empty = tmp_path / "empty"
    empty.mkdir()

    assert picker.set_tank(empty) is False
    assert picker.tank_dir is None  # rejected paths are never adopted
    assert seen == []
    assert picker.message_text != ""


def test_set_tank_rejects_missing_directory(qapp, tmp_path) -> None:
    picker = TankPicker()
    assert picker.set_tank(tmp_path / "nope") is False
    assert picker.tank_dir is None
    assert picker.message_text != ""


def test_show_tank_adopts_without_emitting(qapp, tmp_path) -> None:
    picker = TankPicker()
    seen: list[Path] = []
    picker.tank_changed.connect(seen.append)
    tank = _make_tank(tmp_path)

    picker.show_tank(tank)
    assert picker.tank_dir == tank
    assert seen == []  # display-only: no signal, so no re-entrant reload


def test_message_clears_after_a_good_pick(qapp, tmp_path) -> None:
    picker = TankPicker()
    empty = tmp_path / "empty"
    empty.mkdir()
    picker.set_tank(empty)
    assert picker.message_text != ""

    picker.set_tank(_make_tank(tmp_path))
    assert picker.message_text == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tank_picker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.tank_picker'`

- [ ] **Step 3: Write the implementation**

Create `src/tdt_ephyviewer_explorer/tank_picker.py`:

```python
"""A shared tank-directory picker, used by both the explorer and the metadata app."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets
from PySide6.QtCore import Signal

from tdt_ephyviewer_explorer.tank import list_blocks


class TankPicker(QtWidgets.QWidget):
    """A read-only path field, a Browse button, and an inline validation message.

    :attr:`tank_changed` fires only for directories holding at least one block, so
    consumers never have to re-validate. Use :meth:`show_tank` to reflect a tank
    adopted elsewhere without triggering that signal.
    """

    tank_changed = Signal(object)  # emits a Path

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """:param parent: Parent Qt widget."""
        super().__init__(parent)
        self._tank_dir: Path | None = None

        self._field = QtWidgets.QLineEdit()
        self._field.setReadOnly(True)
        self._field.setPlaceholderText("No tank selected")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        self._message = QtWidgets.QLabel("")
        self._message.setWordWrap(True)
        self._message.setVisible(False)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Tank"))
        row.addWidget(self._field, 1)
        row.addWidget(browse)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self._message)

    @property
    def tank_dir(self) -> Path | None:
        """The currently adopted tank directory, or ``None``."""
        return self._tank_dir

    @property
    def message_text(self) -> str:
        """The inline validation message; empty when there is nothing to report."""
        return self._message.text()

    def set_tank(self, tank_dir: Path) -> bool:
        """Validate a tank, adopt it, and emit :attr:`tank_changed`.

        A directory that does not exist or holds no blocks is reported inline and
        left unadopted, so a bad pick never clears a good one.

        :param tank_dir: Candidate Synapse tank directory.
        :returns: ``True`` if the tank was adopted.
        """
        problem = self._validate(tank_dir)
        if problem is not None:
            self._set_message(problem)
            return False
        self.show_tank(tank_dir)
        self.tank_changed.emit(tank_dir)
        return True

    def show_tank(self, tank_dir: Path) -> None:
        """Display a tank adopted elsewhere, without emitting :attr:`tank_changed`.

        Consumers call this from their own ``set_tank`` so that a programmatic tank
        change updates the field without bouncing a signal back and re-entering.

        :param tank_dir: The tank directory to display.
        """
        self._tank_dir = tank_dir
        self._field.setText(str(tank_dir))
        self._set_message("")

    @staticmethod
    def _validate(tank_dir: Path) -> str | None:
        """Return a human-readable problem with ``tank_dir``, or ``None`` if it is fine."""
        if not tank_dir.is_dir():
            return f"Not a directory: {tank_dir}"
        if not list_blocks(tank_dir):
            return f"No blocks found in {tank_dir}"
        return None

    def _set_message(self, text: str) -> None:
        """Show ``text`` inline, hiding the label when empty."""
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def _on_browse(self) -> None:
        """Prompt for a directory and try to adopt it."""
        start = str(self._tank_dir) if self._tank_dir is not None else ""
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select tank directory", start
        )
        if chosen:
            self.set_tank(Path(chosen))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_tank_picker.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/tank_picker.py tests/test_tank_picker.py
git commit -m "feat(picker): shared tank-directory picker widget"
```

---

### Task 2: Adopt the picker in tdt-explore; make --tank optional

Moving tank ownership into `ControlWindow` is not cosmetic: without it, picking a new tank in
the GUI would leave `App` launching blocks from the previous tank's directory.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/control_window.py` (imports; `__init__`; `set_tank`)
- Modify: `src/tdt_ephyviewer_explorer/app.py` (`__init__`, `open_tank`, `_on_launch`, `main`)
- Test: `tests/test_control_window.py` (add cases), `tests/test_app.py` (fix one case, add one)

**Interfaces:**
- Consumes: `TankPicker` from Task 1.
- Produces: `ControlWindow.tank_dir -> Path | None`. `App` no longer has `_tank_dir`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_control_window.py`:

```python
def test_control_window_exposes_tank_dir(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    assert cw.tank_dir is None  # nothing picked yet

    tank = _make_tank(tmp_path)
    cw.set_tank(tank)
    assert cw.tank_dir == tank


def test_picker_signal_loads_the_tank(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    tank = _make_tank(tmp_path)

    cw.picker.set_tank(tank)  # as if the user browsed to it
    assert cw.tank_dir == tank
    assert [c.name() for c in cw._root.children()] == ["Wav1"]


def test_launch_button_disabled_until_a_block_loads(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    assert cw.launch_button.isEnabled() is False  # no tank yet

    cw.set_tank(_make_tank(tmp_path))
    assert cw.launch_button.isEnabled() is True

    empty = tmp_path / "empty_tank"
    empty.mkdir()
    cw.set_tank(empty)
    assert cw.launch_button.isEnabled() is False  # cleared again


def test_set_tank_updates_the_picker_without_reentering(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    calls: list[object] = []
    cw.picker.tank_changed.connect(calls.append)

    tank = _make_tank(tmp_path)
    cw.set_tank(tank)  # programmatic: picker must display it, not re-emit
    assert cw.picker.tank_dir == tank
    assert calls == []
```

In `tests/test_app.py`, replace the line `app._tank_dir = Path("tank")` with:

```python
    app.control_window._tank_dir = Path("tank")
```

and append this case:

```python
def test_main_without_tank_opens_an_empty_window(qapp, monkeypatch) -> None:
    from tdt_ephyviewer_explorer import app as app_mod

    shown: list[object] = []
    monkeypatch.setattr(app_mod, "mkQApp", lambda: _FakeQApp(shown))

    assert app_mod.main([]) == 0  # --tank is optional now
    assert shown == ["exec"]


class _FakeQApp:
    """Stands in for the Qt application so main() returns without an event loop."""

    def __init__(self, shown: list) -> None:
        self._shown = shown

    def exec(self) -> int:
        self._shown.append("exec")
        return 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_control_window.py tests/test_app.py -v`
Expected: FAIL — `AttributeError: 'ControlWindow' object has no attribute 'tank_dir'`, and
`main([])` fails with a SystemExit from argparse because `--tank` is still required.

- [ ] **Step 3: Modify `control_window.py`**

Add the import beside the existing ones:

```python
from tdt_ephyviewer_explorer.tank_picker import TankPicker
```

In `__init__`, replace the global-tree block. The readonly `tank` row goes away — the picker
now shows the path, and two widgets displaying the same string stacked on top of each other is
just noise:

```python
        # Global group: a block selector populated from list_blocks(). The tank path
        # itself is shown by the picker above, not duplicated here.
        self._picker = TankPicker()
        self._picker.tank_changed.connect(self.set_tank)
        self._global_tree = ParameterTree(showHeader=False)
        self._global_root = Parameter.create(
            name="global",
            type="group",
            children=[
                {"name": "block", "type": "list", "limits": [], "value": None},
            ],
        )
        self._global_tree.setParameters(self._global_root, showTop=False)
        self._global_root.child("block").sigValueChanged.connect(self._on_block_changed)
```

Replace the launch-button block so the button is reachable and starts disabled:

```python
        self._launch_btn = QtWidgets.QPushButton("Launch window")
        self._launch_btn.clicked.connect(self._on_launch)
        self._launch_btn.setEnabled(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._picker)
        layout.addWidget(self._global_tree)
        layout.addWidget(self._tree)
        layout.addWidget(self._launch_btn)
```

Add two properties next to the existing `headers` property:

```python
    @property
    def picker(self) -> TankPicker:
        """The tank picker hosted at the top of the window."""
        return self._picker

    @property
    def launch_button(self) -> QtWidgets.QPushButton:
        """The launch button, disabled while no block is loaded."""
        return self._launch_btn

    @property
    def tank_dir(self) -> Path | None:
        """The current tank directory, or ``None`` before one is picked.

        This window is the single owner of the current tank; :class:`~app.App` reads
        it from here so that picking a new tank in the GUI cannot leave the launcher
        pointed at the previous one.
        """
        return self._tank_dir
```

In `set_tank`, replace the readonly-param update with a picker update, and keep the launch
button in step with the loaded block:

```python
        self._tank_dir = tank_dir
        self._picker.show_tank(tank_dir)
```

and at the end of `set_tank`, replace the `if chosen is not None:` block with:

```python
        if chosen is not None:
            self.set_block(tank_dir / chosen)
        else:
            self._block_path = None
            self._headers = None
            self._root.clearChildren()
        self._launch_btn.setEnabled(self._block_path is not None)
```

At the end of `set_block`, after `self._append_processed_groups(block_path)`, add:

```python
        self._launch_btn.setEnabled(True)
```

- [ ] **Step 4: Modify `app.py`**

Delete `self._tank_dir: Path | None = None` from `App.__init__`, then replace `open_tank`
and `_on_launch`:

```python
    def open_tank(self, tank_dir: Path, block: str | None = None) -> None:
        """Point the control window at a tank, populating its block selector.

        :param tank_dir: Tank directory containing block subdirectories.
        :param block: Block name to preselect; otherwise ``set_tank`` selects the
            first block (if any).
        :returns: None.
        """
        self.control_window.set_tank(tank_dir, block)

    def _on_launch(self, session: Session) -> None:
        # The control window owns the current tank: the user may have picked a new
        # one since startup, and this must follow it.
        tank_dir = self.control_window.tank_dir
        if tank_dir is None:
            return
        block_path = tank_dir / session.block
        # Reuse the index the control window already parsed for this block.
        win = launch_block(block_path, session, self._cfg, headers=self.control_window.headers)
        win.show()
        self.windows.append(win)
```

Replace `main`:

```python
def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tdt-explore`` console script.

    :param argv: CLI args; optional ``--tank`` and ``--block``. With no ``--tank``
        the window opens empty and the tank is chosen with the in-window picker.
    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(prog="tdt-explore")
    parser.add_argument(
        "--tank", default=None, type=Path, help="Synapse tank directory (optional)"
    )
    parser.add_argument("--block", default=None, help="Block name to preselect")
    args = parser.parse_args(argv)

    qapp = mkQApp()
    app = App()
    if args.tank is not None:
        app.open_tank(args.tank, args.block)
    app.control_window.show()
    return int(qapp.exec())
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass, including the pre-existing control-window and app tests.

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/control_window.py src/tdt_ephyviewer_explorer/app.py tests/test_control_window.py tests/test_app.py
git commit -m "feat(explore): in-window tank picker, optional --tank"
```

---

### Task 3: metadata package — text IO and the StoresListing parser

**Files:**
- Create: `src/tdt_ephyviewer_explorer/metadata/__init__.py`
- Create: `src/tdt_ephyviewer_explorer/metadata/textio.py`
- Create: `src/tdt_ephyviewer_explorer/metadata/listing.py`
- Create: `tests/fixtures/metadata/StoresListing.txt`
- Test: `tests/test_metadata_textio.py`, `tests/test_metadata_listing.py`

**Interfaces:**
- Produces:
  - `textio.read_text(path: Path) -> str`
  - `textio.write_text_atomic(path: Path, text: str) -> None`
  - `listing.Gizmo(object_id: str, kind: str | None, stores: tuple[str, ...])` — frozen dataclass
  - `listing.parse_stores_listing(text: str) -> list[Gizmo]`
  - `listing.read_stores_listing(block_path: Path) -> list[Gizmo]`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/metadata/StoresListing.txt` with exactly this content (a trimmed copy of
a real file — three gizmos is enough to cover the block grammar):

```
Experiment: cnn_gp_mep_all_udp_v2
Subject: Epi_02_Green
User: User
Date: 07/27/2026
Time: 3:29:27pm

Object ID : RZ2(1) - RZn Processor
 Rate     : 24414.1 Hz
 Store ID : Tick

Object ID : eStim1 - Electrical Stim Driver
 Store ID : eS1p
  Mode    : Single scalar
  Format  : Float-32
 Store ID : eS1r
  Mode    : Strobe controlled
  Format  : Float-32

Object ID : Wave1 - Stream Data Storage
 Store ID : Wav1
  Format  : Float-32
  Rate    : 24414.1 Hz


Flat Listing:
StoreID  Gizmo/Hal      Description
eS1p     eStim1         store|
eS1r     eStim1         store|
Tick     RZn(1)         Marking one second intervals.
Wav1     Wave1          Streaming: ~PZAn(1).Amp1
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_metadata_textio.py`:

```python
"""Tests for encoding-tolerant reads and atomic writes."""
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.textio import read_text, write_text_atomic


def test_read_text_reads_utf8(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes("café\r\n".encode("utf-8"))
    assert read_text(p) == "café\r\n"


def test_read_text_falls_back_to_latin1(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes(b"caf\xe9\r\n")  # latin-1, invalid as utf-8
    assert read_text(p) == "café\r\n"


def test_read_text_preserves_crlf(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes(b"one\r\ntwo\r\n")
    assert read_text(p) == "one\r\ntwo\r\n"  # no universal-newline translation


def test_write_text_atomic_roundtrips_and_leaves_no_temp(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    write_text_atomic(p, "one\r\ntwo\r\n")
    assert p.read_bytes() == b"one\r\ntwo\r\n"
    assert [f.name for f in tmp_path.iterdir()] == ["a.txt"]


def test_write_text_atomic_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    write_text_atomic(p, "first\r\n")
    write_text_atomic(p, "second\r\n")
    assert p.read_bytes() == b"second\r\n"
```

Create `tests/test_metadata_listing.py`:

```python
"""Tests for the StoresListing.txt parser."""
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.listing import (
    Gizmo,
    parse_stores_listing,
    read_stores_listing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "metadata" / "StoresListing.txt"


def test_parses_gizmos_with_kinds_and_stores() -> None:
    gizmos = parse_stores_listing(FIXTURE.read_text())
    assert gizmos == [
        Gizmo("RZ2(1)", "RZn Processor", ("Tick",)),
        Gizmo("eStim1", "Electrical Stim Driver", ("eS1p", "eS1r")),
        Gizmo("Wave1", "Stream Data Storage", ("Wav1",)),
    ]


def test_stops_at_the_flat_listing() -> None:
    # The flat listing repeats every store; parsing into it would duplicate them.
    gizmos = parse_stores_listing(FIXTURE.read_text())
    assert sum(len(g.stores) for g in gizmos) == 4


def test_object_id_without_a_kind() -> None:
    text = "Object ID : Solo\n Store ID : ABCD\n"
    assert parse_stores_listing(text) == [Gizmo("Solo", None, ("ABCD",))]


def test_gizmo_with_no_stores_is_kept() -> None:
    text = "Object ID : Empty - Some Kind\n Rate : 100 Hz\n"
    assert parse_stores_listing(text) == [Gizmo("Empty", "Some Kind", ())]


def test_truncated_file_yields_what_it_can() -> None:
    text = "Object ID : eStim1 - Electrical Stim Driver\n Store ID : eS1p\n Store ID"
    assert parse_stores_listing(text) == [Gizmo("eStim1", "Electrical Stim Driver", ("eS1p",))]


def test_empty_text_yields_nothing() -> None:
    assert parse_stores_listing("") == []


def test_header_only_file_yields_nothing() -> None:
    assert parse_stores_listing("Experiment: x\nSubject: y\nUser: z\n") == []


def test_read_stores_listing_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_stores_listing(tmp_path) == []


def test_read_stores_listing_reads_the_block_file(tmp_path: Path) -> None:
    (tmp_path / "StoresListing.txt").write_bytes(FIXTURE.read_bytes())
    assert [g.object_id for g in read_stores_listing(tmp_path)] == [
        "RZ2(1)",
        "eStim1",
        "Wave1",
    ]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_textio.py tests/test_metadata_listing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata'`

- [ ] **Step 4: Write the implementation**

Create `src/tdt_ephyviewer_explorer/metadata/__init__.py`:

```python
"""Session-metadata browsing: parsers, summaries, and the tdt-metadata window."""
```

Create `src/tdt_ephyviewer_explorer/metadata/textio.py`:

```python
"""Encoding-tolerant text reads and crash-safe writes for the metadata sidecar files."""
from __future__ import annotations

import os
from pathlib import Path


def read_text(path: Path) -> str:
    """Read a text file as UTF-8, falling back to latin-1.

    Synapse sidecar files are Windows-authored and occasionally carry a stray
    non-UTF-8 byte; latin-1 decodes any byte sequence, so this never raises on
    content. Newlines are returned verbatim (no universal-newline translation) so a
    parsed file can be re-rendered byte-for-byte.

    :param path: File to read.
    :returns: The decoded text.
    :raises OSError: If the file cannot be read.
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as UTF-8 via a same-directory temp file and rename.

    A crash mid-write leaves the previous file intact rather than a truncated one.
    The temp file is a sibling so the rename stays on one filesystem.

    :param path: Destination file.
    :param text: Full file content, newlines already as intended.
    :raises OSError: If the directory is not writable or the rename fails.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
```

Create `src/tdt_ephyviewer_explorer/metadata/listing.py`:

```python
"""Parser for a block's ``StoresListing.txt``."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tdt_ephyviewer_explorer.metadata.textio import read_text

LISTING_FILENAME = "StoresListing.txt"
_OBJECT_PREFIX = "Object ID :"
_STORE_PREFIX = "Store ID :"
_FLAT_PREFIX = "Flat Listing:"


@dataclass(frozen=True)
class Gizmo:
    """One Synapse gizmo and the stores it writes.

    :param object_id: Synapse object id, e.g. ``"eStim1"``.
    :param kind: Human-readable gizmo type, e.g. ``"Electrical Stim Driver"``;
        ``None`` when the listing gives no type.
    :param stores: Store codes written by this gizmo, in listing order.
    """

    object_id: str
    kind: str | None
    stores: tuple[str, ...]


def parse_stores_listing(text: str) -> list[Gizmo]:
    """Parse the ``Object ID :`` blocks of a StoresListing into gizmos.

    The trailing ``Flat Listing:`` table repeats the same stores but carries only a
    terse description in place of the gizmo type, so parsing stops when it starts.

    :param text: Full contents of a ``StoresListing.txt``.
    :returns: One :class:`Gizmo` per ``Object ID :`` block, in file order.
    """
    gizmos: list[Gizmo] = []
    object_id: str | None = None
    kind: str | None = None
    stores: list[str] = []

    def flush() -> None:
        """Emit the gizmo accumulated so far, if any."""
        if object_id is not None:
            gizmos.append(Gizmo(object_id, kind, tuple(stores)))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(_FLAT_PREFIX):
            break
        if line.startswith(_OBJECT_PREFIX):
            flush()
            value = line[len(_OBJECT_PREFIX):].strip()
            object_id, _, rest = value.partition(" - ")
            object_id = object_id.strip()
            kind = rest.strip() or None
            stores = []
        elif line.startswith(_STORE_PREFIX) and object_id is not None:
            code = line[len(_STORE_PREFIX):].strip()
            if code:
                stores.append(code)
    flush()
    return gizmos


def read_stores_listing(block_path: Path) -> list[Gizmo]:
    """Read and parse ``StoresListing.txt`` from a block directory.

    :param block_path: Path to the block directory.
    :returns: The parsed gizmos; empty when the file is absent.
    """
    path = block_path / LISTING_FILENAME
    if not path.is_file():
        return []
    return parse_stores_listing(read_text(path))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_textio.py tests/test_metadata_listing.py -v`
Expected: 14 passed

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/ tests/test_metadata_textio.py tests/test_metadata_listing.py tests/fixtures/metadata/
git commit -m "feat(metadata): text IO and StoresListing parser"
```

---

### Task 4: Notes parsing and rendering

The round-trip has to be byte-exact, because the same renderer writes `analysis_notes.txt` and
a lossy renderer would corrupt a file the user typed into. Three details drive the code:
files are **CRLF** with a trailing newline; `strftime("%I:%M:%S%p")` produces `03:33:11PM` but
the files use `3:33:11pm`, so time formatting is hand-rolled; and the layout is
`header / blank / notes / blank / Stop`, which yields exactly two blank lines when there are
no notes.

**Files:**
- Create: `src/tdt_ephyviewer_explorer/metadata/notes.py`
- Create: `tests/fixtures/metadata/Notes.txt`, `tests/fixtures/metadata/Notes_nonotes.txt`
- Test: `tests/test_metadata_notes.py`

**Interfaces:**
- Consumes: `textio.read_text`.
- Produces:
  - `notes.Note(index: int, timestamp: datetime, text: str)` — frozen dataclass
  - `notes.NotesFile(experiment, subject, user, start, stop, notes, warnings)` — frozen dataclass
  - `notes.parse_notes(text: str) -> NotesFile`
  - `notes.render_notes(nf: NotesFile) -> str`
  - `notes.read_notes(path: Path) -> NotesFile`
  - `notes.NOTES_FILENAME = "Notes.txt"`

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/metadata/Notes.txt` — must be written with CRLF endings and a trailing CRLF:

```bash
printf 'Experiment: cnn_gp_mep_all_udp_v2\r\nSubject: Epi_02_Green\r\nUser: User\r\nStart: 3:48:30pm 07/27/2026\r\n\r\nNote-1: 3:49:37pm "first run should be chan 5 but is chan 4"\r\nNote-2: 3:50:16pm "will correctly set chan 6 to 6 to avoid confusion"\r\n\r\nStop: 3:57:38pm 07/27/2026\r\n' > tests/fixtures/metadata/Notes.txt
```

`tests/fixtures/metadata/Notes_nonotes.txt` — note the two consecutive blank lines:

```bash
printf 'Experiment: cnn_gp_mep_all_udp_v2\r\nSubject: Mickey\r\nUser: User\r\nStart: 5:37:30pm 06/10/2026\r\n\r\n\r\nStop: 5:38:14pm 06/10/2026\r\n' > tests/fixtures/metadata/Notes_nonotes.txt
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_metadata_notes.py`:

```python
"""Tests for Notes.txt parsing and rendering."""
from datetime import datetime
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.notes import (
    Note,
    NotesFile,
    parse_notes,
    read_notes,
    render_notes,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"
NOTES = FIXTURES / "Notes.txt"
NO_NOTES = FIXTURES / "Notes_nonotes.txt"


def test_parses_header_fields() -> None:
    nf = parse_notes(NOTES.read_bytes().decode("utf-8"))
    assert nf.experiment == "cnn_gp_mep_all_udp_v2"
    assert nf.subject == "Epi_02_Green"
    assert nf.user == "User"
    assert nf.start == datetime(2026, 7, 27, 15, 48, 30)
    assert nf.stop == datetime(2026, 7, 27, 15, 57, 38)


def test_parses_notes_with_the_start_date_inferred() -> None:
    nf = parse_notes(NOTES.read_bytes().decode("utf-8"))
    assert nf.notes == (
        Note(1, datetime(2026, 7, 27, 15, 49, 37),
             "first run should be chan 5 but is chan 4"),
        Note(2, datetime(2026, 7, 27, 15, 50, 16),
             "will correctly set chan 6 to 6 to avoid confusion"),
    )
    assert nf.warnings == ()


def test_parses_an_explicit_date_on_a_note() -> None:
    text = (
        'Start: 3:48:30pm 07/27/2026\r\n\r\n'
        'Note-1: 2:02:14pm 07/29/2026 "EMG saturated"\r\n\r\n'
        'Stop: 3:57:38pm 07/27/2026\r\n'
    )
    nf = parse_notes(text)
    assert nf.notes[0].timestamp == datetime(2026, 7, 29, 14, 2, 14)


def test_note_text_may_contain_quotes() -> None:
    text = 'Start: 3:48:30pm 07/27/2026\r\n\r\nNote-1: 3:49:00pm "he said "ok" then"\r\n'
    assert parse_notes(text).notes[0].text == 'he said "ok" then'


def test_unparseable_note_line_is_warned_and_skipped() -> None:
    text = (
        'Start: 3:48:30pm 07/27/2026\r\n\r\n'
        'Note-1: not a time "bad"\r\n'
        'Note-2: 3:50:16pm "good"\r\n'
    )
    nf = parse_notes(text)
    assert [n.text for n in nf.notes] == ["good"]  # the good one survives
    assert len(nf.warnings) == 1
    assert "Note-1" in nf.warnings[0]


def test_no_notes_file_parses_to_no_notes() -> None:
    nf = parse_notes(NO_NOTES.read_bytes().decode("utf-8"))
    assert nf.notes == ()
    assert nf.subject == "Mickey"


def test_render_reproduces_the_source_bytes() -> None:
    original = NOTES.read_bytes().decode("utf-8")
    assert render_notes(parse_notes(original)) == original


def test_render_reproduces_the_no_notes_layout() -> None:
    # Two blank lines between Start and Stop when there are no notes.
    original = NO_NOTES.read_bytes().decode("utf-8")
    assert render_notes(parse_notes(original)) == original


def test_roundtrip_is_stable_across_two_passes() -> None:
    once = parse_notes(NOTES.read_bytes().decode("utf-8"))
    assert parse_notes(render_notes(once)) == once


def test_render_omits_the_date_when_it_matches_start() -> None:
    nf = NotesFile(
        experiment="e", subject="s", user="u",
        start=datetime(2026, 7, 27, 15, 48, 30),
        stop=datetime(2026, 7, 27, 15, 57, 38),
        notes=(Note(1, datetime(2026, 7, 27, 16, 0, 0), "same day"),),
        warnings=(),
    )
    assert 'Note-1: 4:00:00pm "same day"' in render_notes(nf)


def test_render_includes_the_date_when_it_differs_from_start() -> None:
    nf = NotesFile(
        experiment="e", subject="s", user="u",
        start=datetime(2026, 7, 27, 15, 48, 30),
        stop=datetime(2026, 7, 27, 15, 57, 38),
        notes=(Note(1, datetime(2026, 7, 29, 14, 2, 14), "two days later"),),
        warnings=(),
    )
    assert 'Note-1: 2:02:14pm 07/29/2026 "two days later"' in render_notes(nf)


def test_render_uses_crlf_and_a_trailing_newline() -> None:
    out = render_notes(parse_notes(NOTES.read_bytes().decode("utf-8")))
    assert "\r\n" in out
    assert out.endswith("\r\n")
    assert "\n" not in out.replace("\r\n", "")  # no bare LF anywhere


@pytest.mark.parametrize(
    "moment,expected",
    [
        (datetime(2026, 1, 1, 0, 5, 9), "12:05:09am"),   # midnight is 12am
        (datetime(2026, 1, 1, 12, 5, 9), "12:05:09pm"),  # noon is 12pm
        (datetime(2026, 1, 1, 9, 5, 9), "9:05:09am"),    # hour is not zero-padded
        (datetime(2026, 1, 1, 23, 5, 9), "11:05:09pm"),
    ],
)
def test_time_formatting_edges(moment: datetime, expected: str) -> None:
    nf = NotesFile(
        experiment=None, subject=None, user=None,
        start=datetime(2026, 1, 1, 0, 0, 0), stop=None,
        notes=(Note(1, moment, "x"),), warnings=(),
    )
    assert f"Note-1: {expected} " in render_notes(nf)


def test_read_notes_missing_file_is_empty(tmp_path: Path) -> None:
    nf = read_notes(tmp_path / "Notes.txt")
    assert nf.notes == ()
    assert nf.start is None


def test_read_notes_reads_a_real_file(tmp_path: Path) -> None:
    p = tmp_path / "Notes.txt"
    p.write_bytes(NOTES.read_bytes())
    assert read_notes(p).subject == "Epi_02_Green"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_notes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata.notes'`

- [ ] **Step 4: Write the implementation**

Create `src/tdt_ephyviewer_explorer/metadata/notes.py`:

```python
"""Parsing and rendering of Synapse ``Notes.txt`` and the ``analysis_notes.txt`` sidecar."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from tdt_ephyviewer_explorer.metadata.textio import read_text

NOTES_FILENAME = "Notes.txt"

LINE_END = "\r\n"
_TIME_FMT = "%I:%M:%S%p"
_DATE_FMT = "%m/%d/%Y"

_NOTE_RE = re.compile(
    r'^Note-(?P<index>\d+):\s+'
    r'(?P<time>\d{1,2}:\d{2}:\d{2}\s*[ap]m)'
    r'(?:\s+(?P<date>\d{1,2}/\d{1,2}/\d{4}))?'
    r'\s+"(?P<text>.*)"\s*$',
    re.IGNORECASE,
)
_HEADER_KEYS = {"Experiment": "experiment", "Subject": "subject", "User": "user"}


@dataclass(frozen=True)
class Note:
    """One timestamped note.

    :param index: 1-based position within its file.
    :param timestamp: When the note was taken (wall clock).
    :param text: The note body, without surrounding quotes.
    """

    index: int
    timestamp: datetime
    text: str


@dataclass(frozen=True)
class NotesFile:
    """A parsed notes file: its header block plus its notes.

    :param experiment: Experiment name, or ``None``.
    :param subject: Subject name, or ``None``.
    :param user: Synapse user, or ``None``.
    :param start: Recording start, or ``None``.
    :param stop: Recording stop, or ``None``.
    :param notes: The notes, in file order.
    :param warnings: Human-readable problems found while parsing.
    """

    experiment: str | None
    subject: str | None
    user: str | None
    start: datetime | None
    stop: datetime | None
    notes: tuple[Note, ...]
    warnings: tuple[str, ...]


EMPTY_NOTES = NotesFile(None, None, None, None, None, (), ())


def _parse_moment(time_token: str, date_token: str | None, fallback: datetime | None) -> datetime:
    """Combine a ``3:33:11pm`` token with a date, falling back to another date.

    :param time_token: The time-of-day token.
    :param date_token: An ``MM/DD/YYYY`` token, or ``None`` to use ``fallback``.
    :param fallback: Date to borrow when ``date_token`` is absent.
    :returns: The combined timestamp.
    :raises ValueError: If either token is malformed, or no date is available.
    """
    clock = datetime.strptime(time_token.replace(" ", ""), _TIME_FMT)
    if date_token is not None:
        day = datetime.strptime(date_token, _DATE_FMT)
    elif fallback is not None:
        day = fallback
    else:
        raise ValueError("no date available for a time-only entry")
    return day.replace(
        hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=0
    )


def _parse_header_moment(value: str) -> datetime:
    """Parse a ``Start:``/``Stop:`` value of the form ``3:29:27pm 07/27/2026``.

    :param value: The value after the colon.
    :returns: The parsed timestamp.
    :raises ValueError: If the value is malformed.
    """
    parts = value.split()
    if len(parts) != 2:
        raise ValueError(f"expected '<time> <date>', got {value!r}")
    return _parse_moment(parts[0], parts[1], None)


def parse_notes(text: str) -> NotesFile:
    """Parse a Synapse notes file.

    Accepts both entry forms: ``Note-1: 3:33:11pm "text"`` (date inferred from
    ``Start:``) and ``Note-1: 2:02:14pm 07/29/2026 "text"``. A line that will not
    parse is skipped and recorded in :attr:`NotesFile.warnings` rather than
    aborting the file.

    :param text: Full file contents.
    :returns: The parsed file.
    """
    fields: dict[str, str | None] = {"experiment": None, "subject": None, "user": None}
    start: datetime | None = None
    stop: datetime | None = None
    warnings: list[str] = []
    raw_notes: list[tuple[str, str | None, str]] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if sep and key in _HEADER_KEYS:
            fields[_HEADER_KEYS[key]] = value.strip()
            continue
        if sep and key in ("Start", "Stop"):
            try:
                moment = _parse_header_moment(value.strip())
            except ValueError as exc:
                warnings.append(f"{key}: {exc}")
                continue
            if key == "Start":
                start = moment
            else:
                stop = moment
            continue
        if line.startswith("Note-"):
            match = _NOTE_RE.match(line)
            if match is None:
                warnings.append(f"unparseable note line: {line}")
                continue
            raw_notes.append((match["time"], match["date"], match["text"]))

    # Notes are resolved after the loop because a time-only note borrows Start's
    # date, and Start may appear after some notes in a hand-edited file.
    notes: list[Note] = []
    for time_token, date_token, body in raw_notes:
        try:
            moment = _parse_moment(time_token, date_token, start)
        except ValueError as exc:
            warnings.append(f"unparseable note timestamp {time_token!r}: {exc}")
            continue
        notes.append(Note(len(notes) + 1, moment, body))

    return NotesFile(
        experiment=fields["experiment"],
        subject=fields["subject"],
        user=fields["user"],
        start=start,
        stop=stop,
        notes=tuple(notes),
        warnings=tuple(warnings),
    )


def format_clock(moment: datetime) -> str:
    """Format a timestamp as Synapse does: ``3:33:11pm``, hour not zero-padded.

    ``strftime('%I:%M:%S%p')`` yields ``03:33:11PM``, which does not match the file
    format, so this is hand-rolled.

    :param moment: The timestamp.
    :returns: The formatted time of day.
    """
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d}:{moment.second:02d}{suffix}"


def format_day(moment: datetime) -> str:
    """Format a timestamp's date as ``MM/DD/YYYY``.

    :param moment: The timestamp.
    :returns: The formatted date.
    """
    return moment.strftime(_DATE_FMT)


def _render_note(note: Note, start: datetime | None) -> str:
    """Render one note line, including the date only when it differs from ``start``.

    Omitting a same-day date is what makes rendering a parsed ``Notes.txt`` produce
    the original bytes; including a differing date is what lets an analysis note
    written days later round-trip.

    :param note: The note to render.
    :param start: The file's recording start, for the same-day comparison.
    :returns: The rendered line, without a line terminator.
    """
    stamp = format_clock(note.timestamp)
    if start is None or note.timestamp.date() != start.date():
        stamp = f"{stamp} {format_day(note.timestamp)}"
    return f'Note-{note.index}: {stamp} "{note.text}"'


def render_notes(nf: NotesFile) -> str:
    """Render a notes file back to Synapse's format.

    Layout is header / blank / notes / blank / ``Stop``, which collapses to two
    consecutive blank lines when there are no notes — exactly what Synapse writes.
    Lines are CRLF-terminated, including the last.

    :param nf: The notes file to render.
    :returns: The full file text.
    """
    lines: list[str] = []
    if nf.experiment is not None:
        lines.append(f"Experiment: {nf.experiment}")
    if nf.subject is not None:
        lines.append(f"Subject: {nf.subject}")
    if nf.user is not None:
        lines.append(f"User: {nf.user}")
    if nf.start is not None:
        lines.append(f"Start: {format_clock(nf.start)} {format_day(nf.start)}")
    lines.append("")
    lines.extend(_render_note(n, nf.start) for n in nf.notes)
    lines.append("")
    if nf.stop is not None:
        lines.append(f"Stop: {format_clock(nf.stop)} {format_day(nf.stop)}")
    return LINE_END.join(lines) + LINE_END


def renumber(notes: tuple[Note, ...]) -> tuple[Note, ...]:
    """Reindex notes ``1..N`` in their current order.

    :param notes: Notes in the desired order.
    :returns: The same notes with contiguous 1-based indices.
    """
    return tuple(replace(n, index=i) for i, n in enumerate(notes, start=1))


def read_notes(path: Path) -> NotesFile:
    """Read and parse a notes file.

    :param path: Path to the notes file.
    :returns: The parsed file, or :data:`EMPTY_NOTES` when it does not exist.
    """
    if not path.is_file():
        return EMPTY_NOTES
    return parse_notes(read_text(path))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_notes.py -v`
Expected: 18 passed

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/notes.py tests/test_metadata_notes.py tests/fixtures/metadata/
git commit -m "feat(metadata): Notes.txt parse and byte-exact render"
```

---

### Task 5: The AnalysisNotes editing model

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/notes.py` (append)
- Test: `tests/test_metadata_analysis_notes.py`

**Interfaces:**
- Consumes: `Note`, `NotesFile`, `render_notes`, `read_notes`, `renumber`, `textio.write_text_atomic`.
- Produces:
  - `notes.NotesConflict` — exception
  - `notes.AnalysisNotes.load(block_path: Path, filename: str, header: NotesFile) -> AnalysisNotes`
  - `AnalysisNotes.notes -> tuple[Note, ...]`
  - `AnalysisNotes.path -> Path`
  - `AnalysisNotes.append(text: str, now: datetime) -> None`
  - `AnalysisNotes.edit(index: int, text: str) -> None`
  - `AnalysisNotes.delete(index: int) -> None`
  - `AnalysisNotes.save() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata_analysis_notes.py`:

```python
"""Tests for the editable analysis-notes sidecar."""
from datetime import datetime
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.notes import (
    AnalysisNotes,
    NotesConflict,
    NotesFile,
    parse_notes,
)

FILENAME = "analysis_notes.txt"
HEADER = NotesFile(
    experiment="cnn_gp_mep_all_udp_v2",
    subject="Epi_02_Green",
    user="User",
    start=datetime(2026, 7, 27, 15, 48, 30),
    stop=datetime(2026, 7, 27, 15, 57, 38),
    notes=(),
    warnings=(),
)
T1 = datetime(2026, 7, 29, 14, 2, 14)
T2 = datetime(2026, 7, 29, 14, 5, 31)


def test_load_on_a_block_with_no_file(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    assert an.notes == ()
    assert an.path == tmp_path / FILENAME
    assert not an.path.exists()  # browsing must not create the file


def test_append_and_save_creates_the_file(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("EMG saturated", T1)
    an.save()

    text = an.path.read_bytes().decode("utf-8")
    assert 'Note-1: 2:02:14pm 07/29/2026 "EMG saturated"' in text
    assert "Subject: Epi_02_Green" in text  # header copied from the recording
    assert text.endswith("\r\n")


def test_saved_file_reloads_identically(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("first", T1)
    an.append("second", T2)
    an.save()

    reloaded = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    assert [(n.index, n.timestamp, n.text) for n in reloaded.notes] == [
        (1, T1, "first"),
        (2, T2, "second"),
    ]


def test_edit_replaces_text_and_keeps_the_timestamp(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("typo", T1)
    an.edit(1, "fixed")
    assert an.notes[0].text == "fixed"
    assert an.notes[0].timestamp == T1  # provenance survives an edit


def test_delete_renumbers_the_rest(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    an.append("two", T2)
    an.delete(1)
    assert [(n.index, n.text) for n in an.notes] == [(1, "two")]


def test_delete_then_save_then_reload(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    an.append("two", T2)
    an.delete(1)
    an.save()
    assert [n.text for n in AnalysisNotes.load(tmp_path, FILENAME, HEADER).notes] == ["two"]


def test_edit_and_delete_reject_a_bad_index(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    with pytest.raises(IndexError):
        an.edit(2, "nope")
    with pytest.raises(IndexError):
        an.delete(0)


def test_save_refuses_when_the_file_changed_underneath(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("mine", T1)
    an.save()

    other = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    other.append("theirs", T2)
    other.save()  # a second editor writes

    an.append("mine again", T2)
    with pytest.raises(NotesConflict):
        an.save()  # stale snapshot must not clobber
    assert "theirs" in an.path.read_bytes().decode("utf-8")


def test_reload_clears_the_conflict(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("mine", T1)
    an.save()
    other = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    other.append("theirs", T2)
    other.save()

    fresh = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    fresh.append("mine again", T2)
    fresh.save()  # no conflict: snapshot is current
    assert [n.text for n in AnalysisNotes.load(tmp_path, FILENAME, HEADER).notes] == [
        "mine",
        "theirs",
        "mine again",
    ]


def test_save_on_an_unwritable_directory_raises(tmp_path: Path, monkeypatch) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("x", T1)

    def boom(self, data):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(OSError):
        an.save()  # must surface, never swallow


def test_header_is_preserved_from_an_existing_file(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("one", T1)
    an.save()

    different = NotesFile(
        experiment="other", subject="other", user="other",
        start=None, stop=None, notes=(), warnings=(),
    )
    reloaded = AnalysisNotes.load(tmp_path, FILENAME, different)
    reloaded.append("two", T2)
    reloaded.save()

    text = an.path.read_bytes().decode("utf-8")
    assert "Subject: Epi_02_Green" in text  # the file's own header wins
    assert "Subject: other" not in text


def test_notes_are_ordered_and_indexed_after_several_appends(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    for i, moment in enumerate((T1, T2, datetime(2026, 7, 29, 15, 0, 0)), start=1):
        an.append(f"note {i}", moment)
    assert [n.index for n in an.notes] == [1, 2, 3]


def test_saved_text_parses_with_the_shared_parser(tmp_path: Path) -> None:
    an = AnalysisNotes.load(tmp_path, FILENAME, HEADER)
    an.append("EMG saturated", T1)
    an.save()
    nf = parse_notes(an.path.read_bytes().decode("utf-8"))
    assert nf.notes[0].timestamp == T1
    assert nf.warnings == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_analysis_notes.py -v`
Expected: FAIL — `ImportError: cannot import name 'AnalysisNotes'`

- [ ] **Step 3: Append the implementation to `notes.py`**

Add the import at the top of `notes.py`, beside the existing `read_text` import:

```python
from tdt_ephyviewer_explorer.metadata.textio import read_text, write_text_atomic
```

Then append:

```python
class NotesConflict(RuntimeError):
    """Raised when the notes file changed on disk since it was loaded."""


class AnalysisNotes:
    """Mutable, savable view of a block's ``analysis_notes.txt``.

    Notes are stamped with the wall clock at the moment they are typed. The file is
    written whole and atomically, and a write is refused if the file changed on disk
    since it was loaded, so two open windows cannot silently clobber each other.
    """

    def __init__(self, path: Path, header: NotesFile, notes: tuple[Note, ...],
                 mtime: float | None) -> None:
        """:param path: The sidecar file path (may not exist yet).
        :param header: Header block to write with the notes.
        :param notes: Notes loaded from disk, if any.
        :param mtime: The file's mtime when loaded; ``None`` if it did not exist."""
        self._path = path
        self._header = header
        self._notes = notes
        self._mtime = mtime

    @classmethod
    def load(cls, block_path: Path, filename: str, header: NotesFile) -> AnalysisNotes:
        """Load a block's analysis notes, or start an empty set.

        An existing file's own header wins over ``header``: the file records the
        recording it belongs to, and a caller's fallback must not overwrite it.

        :param block_path: The block directory.
        :param filename: Sidecar filename, from config.
        :param header: Header to use when the file does not exist yet, normally
            taken from the block's ``Notes.txt``.
        :returns: The loaded editing model. No file is created.
        """
        path = block_path / filename
        if not path.is_file():
            return cls(path, header, (), None)
        existing = read_notes(path)
        return cls(path, existing, existing.notes, path.stat().st_mtime)

    @property
    def path(self) -> Path:
        """The sidecar file path; may not exist until the first :meth:`save`."""
        return self._path

    @property
    def notes(self) -> tuple[Note, ...]:
        """The current notes, indexed ``1..N``."""
        return self._notes

    def append(self, text: str, now: datetime) -> None:
        """Add a note stamped with the current wall clock.

        :param text: The note body.
        :param now: The authoring timestamp (injected so tests are deterministic).
        """
        self._notes = self._notes + (Note(len(self._notes) + 1, now, text),)

    def edit(self, index: int, text: str) -> None:
        """Replace a note's text, keeping its timestamp.

        :param index: 1-based note index.
        :param text: The replacement body.
        :raises IndexError: If ``index`` is out of range.
        """
        self._require(index)
        self._notes = tuple(
            replace(n, text=text) if n.index == index else n for n in self._notes
        )

    def delete(self, index: int) -> None:
        """Delete a note and renumber the rest.

        :param index: 1-based note index.
        :raises IndexError: If ``index`` is out of range.
        """
        self._require(index)
        self._notes = renumber(tuple(n for n in self._notes if n.index != index))

    def save(self) -> None:
        """Write the notes atomically, refusing to clobber a newer file.

        :raises NotesConflict: If the file changed on disk since it was loaded.
        :raises OSError: If the directory is not writable.
        """
        if self._stale():
            raise NotesConflict(
                f"{self._path} changed on disk since it was loaded; reload before saving"
            )
        text = render_notes(
            NotesFile(
                experiment=self._header.experiment,
                subject=self._header.subject,
                user=self._header.user,
                start=self._header.start,
                stop=self._header.stop,
                notes=self._notes,
                warnings=(),
            )
        )
        write_text_atomic(self._path, text)
        self._mtime = self._path.stat().st_mtime

    def _stale(self) -> bool:
        """Whether the on-disk file has moved on from the loaded snapshot."""
        exists = self._path.is_file()
        if not exists:
            return False  # nothing to clobber
        if self._mtime is None:
            return True  # appeared after we started with no file
        return self._path.stat().st_mtime != self._mtime

    def _require(self, index: int) -> None:
        """Raise if ``index`` is not a current note index."""
        if not any(n.index == index for n in self._notes):
            raise IndexError(f"no note with index {index}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_analysis_notes.py tests/test_metadata_notes.py -v`
Expected: 31 passed

Note: `test_save_refuses_when_the_file_changed_underneath` depends on mtime resolution. If it
proves flaky on a fast filesystem, make `save()` also compare the file's size and content hash
rather than loosening the assertion — do not add a sleep.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/notes.py tests/test_metadata_analysis_notes.py
git commit -m "feat(metadata): editable analysis-notes sidecar with conflict guard"
```

---

### Task 6: Stim summary and the metadata config group

**Files:**
- Create: `src/tdt_ephyviewer_explorer/config/metadata/default.yaml`
- Modify: `src/tdt_ephyviewer_explorer/config/config.yaml` (add to `defaults`)
- Create: `src/tdt_ephyviewer_explorer/metadata/stim.py`
- Test: `tests/test_metadata_stim.py`, `tests/test_config.py` (add one case)

**Interfaces:**
- Consumes: `stores.load_store`, `config_schema.load_config`.
- Produces:
  - `stim.StimSummary(store: str, n_pulses: int, n_combinations: int)` — frozen dataclass
  - `stim.StimSchemaMismatch` — exception
  - `stim.StimConfig(store_pattern, schema, voices, chan_prefix, count_prefix)` — frozen dataclass
  - `stim.stim_config_from(cfg) -> tuple[StimConfig, list[str]]` — config plus its column names
  - `stim.summarize_stim(store, data, column_names, voices, chan_prefix, count_prefix) -> StimSummary`
  - `stim.read_stim_summaries(block_path, cfg, headers=None) -> tuple[list[StimSummary], list[str]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata_stim.py`:

```python
"""Tests for the eStim pulse/parameter-combination summary."""
import numpy as np
import pytest

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.stim import (
    StimSchemaMismatch,
    StimSummary,
    stim_config_from,
    summarize_stim,
)

VOICES = ("A", "B", "C", "D")
COLS = tuple(
    f"{field}{v}" for v in VOICES
    for field in ("per", "count", "amp", "dur", "delay", "chan")
)


def _blank(n_events: int) -> np.ndarray:
    """A (24, n_events) all-zero parameter block."""
    return np.zeros((len(COLS), n_events), dtype=float)


def _row(name: str) -> int:
    return COLS.index(name)


def _summarize(data: np.ndarray) -> StimSummary:
    return summarize_stim("eS1p", data, COLS, VOICES, "chan", "count")


def test_single_active_voice_one_pulse_each() -> None:
    data = _blank(10)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 10, 1)


def test_sweeping_a_channel_counts_distinct_combinations() -> None:
    data = _blank(6)
    data[_row("chanA")] = [1, 1, 2, 2, 3, 3]
    data[_row("countA")] = 1.0
    assert _summarize(data) == StimSummary("eS1p", 6, 3)


def test_two_active_voices_combine_into_pairs() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 1, 2, 2]
    data[_row("chanB")] = [5, 6, 5, 6]
    data[_row("countA")] = 1.0
    data[_row("countB")] = 1.0
    assert _summarize(data) == StimSummary("eS1p", 4, 4)


def test_count_greater_than_one_yields_more_pulses_than_events() -> None:
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    assert _summarize(data).n_pulses == 15


def test_concurrent_voices_do_not_double_count_pulses() -> None:
    # A and B fire together; a 3-pulse train is 3 pulses in time, not 6.
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    data[_row("chanB")] = 2.0
    data[_row("countB")] = 3.0
    assert _summarize(data).n_pulses == 15


def test_pulses_take_the_max_across_voices() -> None:
    data = _blank(1)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 2.0
    data[_row("chanB")] = 1.0
    data[_row("countB")] = 5.0
    assert _summarize(data).n_pulses == 5


def test_idle_voice_with_nonzero_params_does_not_inflate_combinations() -> None:
    # C has chan == 0 throughout (a dummy voice) but wobbling amp/per. Including
    # its columns would report 3 combinations instead of 1.
    data = _blank(3)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampC")] = [-1.0, -2.0, -3.0]
    data[_row("perC")] = 0.983
    assert _summarize(data) == StimSummary("eS1p", 3, 1)


def test_inactive_voice_events_contribute_no_pulses() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 0, 1, 0]  # voice A idle on two events
    data[_row("countA")] = 1.0
    assert _summarize(data).n_pulses == 2


def test_no_active_voice_anywhere_is_all_zeros() -> None:
    data = _blank(7)
    data[_row("ampA")] = -100.0  # amp set but chan == 0: not stimulation
    assert _summarize(data) == StimSummary("eS1p", 0, 0)


def test_zero_events() -> None:
    assert _summarize(_blank(0)) == StimSummary("eS1p", 0, 0)


def test_row_count_mismatch_raises() -> None:
    data = np.zeros((23, 4), dtype=float)
    with pytest.raises(StimSchemaMismatch):
        _summarize(data)


def test_negative_chan_is_not_active() -> None:
    data = _blank(3)
    data[_row("chanA")] = -1.0
    assert _summarize(data) == StimSummary("eS1p", 0, 0)


def test_stim_config_comes_from_the_packaged_config() -> None:
    sc, columns = stim_config_from(load_config())
    assert sc.store_pattern == "eS?p"
    assert sc.voices == ("A", "B", "C", "D")
    assert sc.chan_prefix == "chan"
    assert sc.count_prefix == "count"
    assert len(columns) == 24
    assert columns[:3] == ["perA", "countA", "ampA"]
```

Append to `tests/test_config.py`:

```python
def test_metadata_group_is_composed() -> None:
    from tdt_ephyviewer_explorer.config_schema import load_config

    cfg = load_config()
    assert cfg.metadata.analysis_notes_filename == "analysis_notes.txt"
    assert cfg.metadata.stim.schema == "iz_param_names"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_stim.py tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata.stim'`

- [ ] **Step 3: Add the config group**

Create `src/tdt_ephyviewer_explorer/config/metadata/default.yaml`:

```yaml
# @package _global_
# Settings for the tdt-metadata browser.
metadata:
  # Sidecar file for post-hoc annotations, written into the block directory. This is
  # the one documented exception to "raw block dirs are never written to".
  analysis_notes_filename: analysis_notes.txt
  stim:
    # fnmatch pattern for the stim parameter store (eS1p, eS2p, …).
    store_pattern: "eS?p"
    # Named column schema (see schema/default.yaml) giving the store's row order.
    schema: iz_param_names
    # Voice suffixes appended to each parameter name (perA, countA, …).
    voices: [A, B, C, D]
    # Column prefixes: chan{V} > 0 marks a voice active; count{V} is pulses per train.
    chan_prefix: chan
    count_prefix: count
```

In `src/tdt_ephyviewer_explorer/config/config.yaml`, add `metadata` to `defaults`:

```yaml
defaults:
  - viewer: default
  - roles: default
  - schema: default
  - startup: default
  - processed: default
  - metadata: default
  - _self_
```

- [ ] **Step 4: Write `stim.py`**

Create `src/tdt_ephyviewer_explorer/metadata/stim.py`:

```python
"""Pulse and parameter-combination summaries for eStim parameter stores."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from tdt_ephyviewer_explorer.stores import _get, load_store


class StimSchemaMismatch(ValueError):
    """Raised when a stim store's row count does not match its configured schema."""


@dataclass(frozen=True)
class StimSummary:
    """Headline stimulation figures for one parameter store.

    :param store: Store code, e.g. ``"eS1p"``.
    :param n_pulses: Total pulses delivered.
    :param n_combinations: Distinct parameter settings used.
    """

    store: str
    n_pulses: int
    n_combinations: int


@dataclass(frozen=True)
class StimConfig:
    """Resolved ``metadata.stim`` settings.

    :param store_pattern: fnmatch pattern selecting parameter stores.
    :param schema: Name of the column schema in ``schemas``.
    :param voices: Voice suffixes appended to each parameter name.
    :param chan_prefix: Column prefix whose value marks a voice active when ``> 0``.
    :param count_prefix: Column prefix giving pulses per train.
    """

    store_pattern: str
    schema: str
    voices: tuple[str, ...]
    chan_prefix: str
    count_prefix: str


def stim_config_from(cfg: Any) -> tuple[StimConfig, list[str]]:
    """Extract the stim settings and their column names from a composed config.

    :param cfg: The composed Hydra config.
    :returns: The settings, and the ordered column names of the named schema.
    :raises KeyError: If the configured schema is not defined in ``schemas``.
    """
    node = cfg.metadata.stim
    schema = str(node.schema)
    columns = [str(c) for c in cfg.schemas[schema]]
    return (
        StimConfig(
            store_pattern=str(node.store_pattern),
            schema=schema,
            voices=tuple(str(v) for v in node.voices),
            chan_prefix=str(node.chan_prefix),
            count_prefix=str(node.count_prefix),
        ),
        columns,
    )


def summarize_stim(
    store: str,
    data: np.ndarray,
    column_names: Sequence[str],
    voices: Sequence[str],
    chan_prefix: str,
    count_prefix: str,
) -> StimSummary:
    """Reduce a stim parameter block to a pulse count and a combination count.

    A voice is *active* when its ``chan`` column exceeds zero for at least one event
    (``chan == 0`` is Synapse's dummy value for "no stimulation"). Only active
    voices' columns take part, so an idle voice whose other parameters happen to
    vary cannot inflate the combination count.

    Pulses per event are the **maximum** ``count`` across that event's active voices,
    not the sum: voices fire concurrently, so a 3-pulse train on two voices is three
    pulses in time.

    :param store: Store code, carried into the result.
    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param column_names: Row labels, one per row of ``data``.
    :param voices: Voice suffixes to consider.
    :param chan_prefix: Prefix of the channel column.
    :param count_prefix: Prefix of the pulses-per-train column.
    :returns: The summary.
    :raises StimSchemaMismatch: If ``data`` has a different row count than
        ``column_names`` — labelling the rows anyway would silently mis-report.
    """
    if data.shape[0] != len(column_names):
        raise StimSchemaMismatch(
            f"{store}: {data.shape[0]} rows but schema names {len(column_names)} columns"
        )
    index = {name: i for i, name in enumerate(column_names)}
    n_events = int(data.shape[1])

    active = [
        v for v in voices
        if f"{chan_prefix}{v}" in index and bool((data[index[f"{chan_prefix}{v}"]] > 0).any())
    ]
    if not active or n_events == 0:
        return StimSummary(store, 0, 0)

    combo_rows = [i for name, i in index.items() if any(name.endswith(v) for v in active)]
    n_combinations = int(np.unique(data[combo_rows].T, axis=0).shape[0])

    per_event = np.zeros(n_events, dtype=float)
    for v in active:
        channel = data[index[f"{chan_prefix}{v}"]]
        count = data[index[f"{count_prefix}{v}"]]
        per_event = np.maximum(per_event, np.where(channel > 0, count, 0.0))
    return StimSummary(store, int(per_event.sum()), n_combinations)


def read_stim_summaries(
    block_path: Path, cfg: Any, headers: Any | None = None
) -> tuple[list[StimSummary], list[str]]:
    """Load every stim parameter store in a block and summarize each.

    :param block_path: Path to the block directory.
    :param cfg: The composed Hydra config.
    :param headers: Pre-parsed ``.tsq`` headers to reuse; ``None`` parses them.
    :returns: The summaries, and any warnings raised while producing them.
    :raises KeyError: If the configured schema is not defined in ``schemas``.
    """
    settings, columns = stim_config_from(cfg)
    summaries: list[StimSummary] = []
    warnings: list[str] = []
    if headers is None:
        return summaries, ["stim summary skipped: block index not parsed"]

    names = [n for n in headers["stores"].keys() if fnmatchcase(n, settings.store_pattern)]
    for name in names:
        try:
            store = load_store(block_path, name, headers=headers)
            data = np.atleast_2d(np.asarray(_get(store, "data"), dtype=float))
            summaries.append(
                summarize_stim(
                    name, data, columns, settings.voices,
                    settings.chan_prefix, settings.count_prefix,
                )
            )
        except StimSchemaMismatch as exc:
            warnings.append(str(exc))
        except (KeyError, OSError, ValueError) as exc:
            warnings.append(f"{name}: could not read stim parameters ({exc})")
    return summaries, warnings
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_stim.py tests/test_config.py -v`
Expected: 13 stim tests plus the existing config tests, all passing.

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/stim.py src/tdt_ephyviewer_explorer/config/metadata/ src/tdt_ephyviewer_explorer/config/config.yaml tests/test_metadata_stim.py tests/test_config.py
git commit -m "feat(metadata): stim pulse and combination summary"
```

---

### Task 7: BlockSummary and the three read tiers

**Files:**
- Create: `src/tdt_ephyviewer_explorer/metadata/summary.py`
- Test: `tests/test_metadata_summary.py`

**Interfaces:**
- Consumes: `listing.Gizmo`/`read_stores_listing`, `notes.Note`/`read_notes`/`NOTES_FILENAME`,
  `stim.StimSummary`/`read_stim_summaries`, `tank.read_headers`.
- Produces:
  - `summary.BlockSummary` — frozen dataclass, fields listed below
  - `summary.read_text_metadata(block_path: Path) -> BlockSummary`
  - `summary.augment_with_headers(summary: BlockSummary, headers: Any) -> BlockSummary`
  - `summary.load_details(summary: BlockSummary, cfg: Any) -> BlockSummary`
  - `summary.scan_tank(tank_dir: Path) -> list[BlockSummary]`
  - `summary.BlockCache` with `use_tank`, `get`, `put`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata_summary.py`:

```python
"""Tests for block summaries and the tiered reads."""
from datetime import datetime
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.listing import Gizmo
from tdt_ephyviewer_explorer.metadata.stim import StimSummary
from tdt_ephyviewer_explorer.metadata.summary import (
    BlockCache,
    BlockSummary,
    augment_with_headers,
    load_details,
    read_text_metadata,
    scan_tank,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"


def _block(tmp_path: Path, name: str = "Epi_02_Green-260727-154827",
           notes: bool = True, listing: bool = True) -> Path:
    blk = tmp_path / name
    blk.mkdir(parents=True)
    (blk / f"{name}.tsq").write_bytes(b"")
    if notes:
        (blk / "Notes.txt").write_bytes((FIXTURES / "Notes.txt").read_bytes())
    if listing:
        (blk / "StoresListing.txt").write_bytes((FIXTURES / "StoresListing.txt").read_bytes())
    return blk


class _Headers(dict):
    """Minimal stand-in for tdt's headers struct."""


def _headers(store_names: list[str], start: float = 1000.0, stop: float = 1600.0) -> _Headers:
    return _Headers(
        stores={n: {} for n in store_names},
        start_time=[start],
        stop_time=[stop],
    )


def test_text_metadata_reads_header_notes_and_gizmos(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    assert s.name == "Epi_02_Green-260727-154827"
    assert s.subject == "Epi_02_Green"
    assert s.experiment == "cnn_gp_mep_all_udp_v2"
    assert s.start == datetime(2026, 7, 27, 15, 48, 30)
    assert s.duration_s == pytest.approx(548.0)
    assert [n.text for n in s.notes] == [
        "first run should be chan 5 but is chan 4",
        "will correctly set chan 6 to 6 to avoid confusion",
    ]
    assert Gizmo("eStim1", "Electrical Stim Driver", ("eS1p", "eS1r")) in s.gizmos
    assert s.details_loaded is False


def test_text_metadata_without_notes_file(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path, notes=False))
    assert s.notes == ()
    assert s.start is None
    assert s.duration_s is None
    assert s.gizmos  # the listing still parsed


def test_text_metadata_without_stores_listing(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path, listing=False))
    assert s.gizmos == ()
    assert s.subject == "Epi_02_Green"


def test_augment_fills_duration_when_notes_did_not(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path, notes=False))
    out = augment_with_headers(s, _headers(["Wav1"], start=100.0, stop=250.0))
    assert out.duration_s == pytest.approx(150.0)


def test_augment_keeps_the_notes_duration(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    out = augment_with_headers(s, _headers(["Wav1"], start=0.0, stop=9999.0))
    assert out.duration_s == pytest.approx(548.0)  # Notes.txt wins


def test_augment_adds_unlisted_stores(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    out = augment_with_headers(s, _headers(["Tick", "eS1p", "eS1r", "Wav1", "Surprise"]))
    unlisted = [g for g in out.gizmos if g.object_id == "(unlisted)"]
    assert len(unlisted) == 1
    assert unlisted[0].stores == ("Surprise",)


def test_augment_adds_no_unlisted_gizmo_when_all_are_listed(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    out = augment_with_headers(s, _headers(["Tick", "eS1p", "eS1r", "Wav1"]))
    assert all(g.object_id != "(unlisted)" for g in out.gizmos)


def test_load_details_attaches_stim_and_marks_loaded(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    monkeypatch.setattr(mod, "read_headers", lambda p: _headers(["eS1p"]))
    monkeypatch.setattr(
        mod, "read_stim_summaries",
        lambda block_path, cfg, headers=None: ([StimSummary("eS1p", 15561, 1881)], []),
    )
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.stim == (StimSummary("eS1p", 15561, 1881),)
    assert out.details_loaded is True


def test_load_details_records_stim_warnings(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    monkeypatch.setattr(mod, "read_headers", lambda p: _headers(["eS1p"]))
    monkeypatch.setattr(
        mod, "read_stim_summaries",
        lambda block_path, cfg, headers=None: ([], ["eS1p: 23 rows but schema names 24"]),
    )
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.stim == ()
    assert any("23 rows" in w for w in out.warnings)


def test_load_details_survives_a_header_parse_failure(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    def boom(path):
        raise OSError("corrupt tsq")

    monkeypatch.setattr(mod, "read_headers", boom)
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.details_loaded is True  # done trying; not stuck on "loading…"
    assert any("corrupt tsq" in w for w in out.warnings)
    assert out.subject == "Epi_02_Green"  # tier-0 data survives


def test_scan_tank_returns_one_summary_per_block(tmp_path: Path) -> None:
    _block(tmp_path, "blockB-2")
    _block(tmp_path, "blockA-1")
    assert [s.name for s in scan_tank(tmp_path)] == ["blockA-1", "blockB-2"]


def test_scan_tank_marks_a_block_it_cannot_read(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    _block(tmp_path, "blockA-1")

    def boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(mod, "read_text_metadata", boom)
    out = scan_tank(tmp_path)
    assert len(out) == 1  # never silently dropped
    assert any("permission denied" in w for w in out[0].warnings)


def test_cache_returns_what_was_put(tmp_path: Path) -> None:
    cache = BlockCache()
    cache.use_tank(tmp_path)
    s = read_text_metadata(_block(tmp_path))
    cache.put(s)
    assert cache.get(s.name) is s


def test_cache_clears_on_a_different_tank(tmp_path: Path) -> None:
    cache = BlockCache()
    cache.use_tank(tmp_path)
    s = read_text_metadata(_block(tmp_path))
    cache.put(s)

    cache.use_tank(tmp_path / "other")
    assert cache.get(s.name) is None


def test_cache_survives_reselecting_the_same_tank(tmp_path: Path) -> None:
    cache = BlockCache()
    cache.use_tank(tmp_path)
    s = read_text_metadata(_block(tmp_path))
    cache.put(s)

    cache.use_tank(tmp_path)  # same tank: expensive details must not be thrown away
    assert cache.get(s.name) is s
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_summary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata.summary'`

- [ ] **Step 3: Write the implementation**

Create `src/tdt_ephyviewer_explorer/metadata/summary.py`:

```python
"""Per-block metadata summaries, assembled in three increasingly expensive tiers."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from tdt_ephyviewer_explorer.metadata.listing import Gizmo, read_stores_listing
from tdt_ephyviewer_explorer.metadata.notes import NOTES_FILENAME, Note, read_notes
from tdt_ephyviewer_explorer.metadata.stim import StimSummary, read_stim_summaries
from tdt_ephyviewer_explorer.tank import list_blocks, read_headers

UNLISTED_GIZMO = "(unlisted)"


@dataclass(frozen=True)
class BlockSummary:
    """Everything the metadata browser knows about one block.

    :param name: Block directory name.
    :param path: Block directory path.
    :param experiment: Experiment name, or ``None``.
    :param subject: Subject name, or ``None``.
    :param user: Synapse user, or ``None``.
    :param start: Recording start, or ``None``.
    :param stop: Recording stop, or ``None``.
    :param duration_s: Recording duration in seconds, or ``None``.
    :param gizmos: Gizmos and the stores they wrote.
    :param notes: Notes read from ``Notes.txt``.
    :param stim: One summary per stim parameter store.
    :param warnings: Human-readable problems found while assembling this summary.
    :param details_loaded: Whether the header and stim tiers have been attempted.
    """

    name: str
    path: Path
    experiment: str | None
    subject: str | None
    user: str | None
    start: datetime | None
    stop: datetime | None
    duration_s: float | None
    gizmos: tuple[Gizmo, ...]
    notes: tuple[Note, ...]
    stim: tuple[StimSummary, ...]
    warnings: tuple[str, ...]
    details_loaded: bool = False


def read_text_metadata(block_path: Path) -> BlockSummary:
    """Tier 0: build a summary from the block's text sidecars alone.

    Reads no TDT binaries, so it is fast enough to run over every block in a tank
    before showing the window.

    :param block_path: Path to the block directory.
    :returns: The summary, with ``stim`` empty and ``details_loaded`` false.
    """
    nf = read_notes(block_path / NOTES_FILENAME)
    gizmos = read_stores_listing(block_path)
    duration = (
        (nf.stop - nf.start).total_seconds()
        if nf.start is not None and nf.stop is not None
        else None
    )
    return BlockSummary(
        name=block_path.name,
        path=block_path,
        experiment=nf.experiment,
        subject=nf.subject,
        user=nf.user,
        start=nf.start,
        stop=nf.stop,
        duration_s=duration,
        gizmos=tuple(gizmos),
        notes=nf.notes,
        stim=(),
        warnings=nf.warnings,
        details_loaded=False,
    )


def augment_with_headers(summary: BlockSummary, headers: Any) -> BlockSummary:
    """Tier 1: fill gaps from the parsed ``.tsq`` index.

    Supplies a duration when ``Notes.txt`` gave none, and appends any store present
    in the index but missing from ``StoresListing.txt`` under a synthetic
    ``(unlisted)`` gizmo, so a stale listing hides nothing.

    :param summary: The tier-0 summary.
    :param headers: Parsed headers from :func:`~tank.read_headers`.
    :returns: An updated copy.
    """
    duration = summary.duration_s
    if duration is None:
        try:
            duration = float(headers["stop_time"][0]) - float(headers["start_time"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            duration = None

    listed = {code for g in summary.gizmos for code in g.stores}
    unlisted = tuple(n for n in headers["stores"].keys() if n not in listed)
    gizmos = summary.gizmos
    if unlisted:
        gizmos = gizmos + (Gizmo(UNLISTED_GIZMO, None, unlisted),)

    return replace(summary, duration_s=duration, gizmos=gizmos)


def load_details(summary: BlockSummary, cfg: Any) -> BlockSummary:
    """Tiers 1 and 2: parse the index, then summarize the stim stores.

    Runs on a worker thread. Any failure is recorded as a warning and the summary is
    still marked loaded, so the UI leaves the "loading…" state either way.

    :param summary: The tier-0 summary.
    :param cfg: The composed Hydra config.
    :returns: An updated copy with ``details_loaded`` set.
    """
    warnings = list(summary.warnings)
    try:
        headers = read_headers(summary.path)
    except Exception as exc:  # noqa: BLE001 - a bad block must not kill the window
        warnings.append(f"could not read block index: {exc}")
        return replace(summary, warnings=tuple(warnings), details_loaded=True)

    out = augment_with_headers(summary, headers)
    try:
        stim, stim_warnings = read_stim_summaries(out.path, cfg, headers=headers)
    except Exception as exc:  # noqa: BLE001
        stim, stim_warnings = [], [f"could not summarize stimulation: {exc}"]
    warnings.extend(stim_warnings)
    return replace(
        out, stim=tuple(stim), warnings=tuple(warnings), details_loaded=True
    )


def scan_tank(tank_dir: Path) -> list[BlockSummary]:
    """Tier 0 over every block in a tank, in name order.

    :param tank_dir: The tank directory.
    :returns: One summary per block. A block that cannot be read still appears,
        carrying the reason as a warning.
    """
    out: list[BlockSummary] = []
    for block_path in list_blocks(tank_dir):
        try:
            out.append(read_text_metadata(block_path))
        except Exception as exc:  # noqa: BLE001
            out.append(
                BlockSummary(
                    name=block_path.name, path=block_path, experiment=None,
                    subject=None, user=None, start=None, stop=None, duration_s=None,
                    gizmos=(), notes=(), stim=(),
                    warnings=(f"could not read block: {exc}",), details_loaded=True,
                )
            )
    return out


class BlockCache:
    """Per-tank cache of block summaries, keyed by block name.

    Switching to a different tank drops everything; reselecting the current tank
    keeps it, so an expensive tier-2 read is not repeated.
    """

    def __init__(self) -> None:
        self._tank: Path | None = None
        self._by_name: dict[str, BlockSummary] = {}

    def use_tank(self, tank_dir: Path) -> None:
        """Point the cache at a tank, clearing it if the tank changed.

        :param tank_dir: The tank now being browsed.
        """
        if self._tank != tank_dir:
            self._tank = tank_dir
            self._by_name = {}

    def get(self, name: str) -> BlockSummary | None:
        """Return the cached summary for ``name``, or ``None``."""
        return self._by_name.get(name)

    def put(self, summary: BlockSummary) -> None:
        """Store ``summary`` under its block name."""
        self._by_name[summary.name] = summary
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_summary.py -v`
Expected: 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/summary.py tests/test_metadata_summary.py
git commit -m "feat(metadata): block summaries and tiered reads"
```

---

### Task 8: The notes side panel

**Files:**
- Create: `src/tdt_ephyviewer_explorer/metadata/notes_panel.py`
- Test: `tests/test_metadata_notes_panel.py`

**Interfaces:**
- Consumes: `notes.AnalysisNotes`, `notes.Note`, `notes.NotesConflict`, `notes.format_clock`, `notes.format_day`.
- Produces:
  - `notes_panel.NotesPanel(parent=None)` — a `QWidget`
  - `NotesPanel.show_readonly(block_name: str, title: str, notes: Sequence[Note]) -> None`
  - `NotesPanel.show_editable(block_name: str, title: str, model: AnalysisNotes, clock: Callable[[], datetime]) -> None`
  - `NotesPanel.header_text -> str`
  - `NotesPanel.message_text -> str`
  - `NotesPanel.row_count -> int`
  - `NotesPanel.notes_changed` — `Signal()`, fires after a successful save

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata_notes_panel.py`:

```python
"""Tests for the notes side panel."""
from datetime import datetime
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.metadata.notes import AnalysisNotes, Note, NotesFile
from tdt_ephyviewer_explorer.metadata.notes_panel import NotesPanel

HEADER = NotesFile("e", "s", "u", datetime(2026, 7, 27, 15, 48, 30), None, (), ())
NOW = datetime(2026, 7, 29, 14, 2, 14)


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def _model(tmp_path: Path) -> AnalysisNotes:
    return AnalysisNotes.load(tmp_path, "analysis_notes.txt", HEADER)


def test_readonly_view_lists_the_notes(qapp) -> None:
    panel = NotesPanel()
    panel.show_readonly(
        "blk", "Notes.txt · read-only",
        [Note(1, datetime(2026, 7, 27, 15, 49, 37), "first"),
         Note(2, datetime(2026, 7, 27, 15, 50, 16), "second")],
    )
    assert panel.row_count == 2  # no trailing blank row when read-only
    assert "blk" in panel.header_text
    assert "read-only" in panel.header_text
    assert panel.cell_text(0, 2) == "first"


def test_readonly_cells_are_not_editable(qapp) -> None:
    from PySide6.QtCore import Qt

    panel = NotesPanel()
    panel.show_readonly("blk", "Notes.txt · read-only",
                        [Note(1, datetime(2026, 7, 27, 15, 49, 37), "only")])
    assert not (panel.item_flags(0, 2) & Qt.ItemIsEditable)


def test_editable_view_has_a_trailing_blank_row(qapp, tmp_path) -> None:
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", _model(tmp_path), lambda: NOW)
    assert panel.row_count == 1  # just the blank entry row
    assert panel.cell_text(0, 2) == ""


def test_typing_in_the_blank_row_appends_and_saves(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    fired: list[int] = []
    panel.notes_changed.connect(lambda: fired.append(1))
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    panel.set_cell_text(0, 2, "EMG saturated")
    assert [n.text for n in model.notes] == ["EMG saturated"]
    assert model.path.exists()
    assert panel.row_count == 2  # a fresh blank row appeared
    assert fired == [1]


def test_new_note_is_stamped_with_the_injected_clock(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    panel.set_cell_text(0, 2, "stamped")
    assert model.notes[0].timestamp == NOW


def test_blank_input_is_ignored(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    panel.set_cell_text(0, 2, "   ")
    assert model.notes == ()
    assert not model.path.exists()


def test_editing_an_existing_row_saves(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    model.append("typo", NOW)
    model.save()
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    panel.set_cell_text(0, 2, "fixed")
    assert model.notes[0].text == "fixed"
    assert "fixed" in model.path.read_bytes().decode("utf-8")


def test_delete_removes_the_row_and_saves(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    model.append("one", NOW)
    model.append("two", NOW)
    model.save()
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    panel.delete_row(0)
    assert [n.text for n in model.notes] == ["two"]
    assert panel.row_count == 2  # one note plus the blank row


def test_timestamp_column_is_read_only(qapp, tmp_path) -> None:
    from PySide6.QtCore import Qt

    model = _model(tmp_path)
    model.append("one", NOW)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    assert not (panel.item_flags(0, 1) & Qt.ItemIsEditable)  # provenance is not editable
    assert panel.item_flags(0, 2) & Qt.ItemIsEditable


def test_a_conflicting_save_is_reported_and_not_silent(qapp, tmp_path) -> None:
    model = _model(tmp_path)
    model.append("mine", NOW)
    model.save()

    other = _model(tmp_path)
    other.append("theirs", NOW)
    other.save()  # someone else writes

    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)
    panel.set_cell_text(panel.row_count - 1, 2, "mine again")
    assert "changed on disk" in panel.message_text


def test_a_write_failure_is_reported(qapp, tmp_path, monkeypatch) -> None:
    model = _model(tmp_path)
    panel = NotesPanel()
    panel.show_editable("blk", "Analysis notes", model, lambda: NOW)

    def boom(self, data):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "write_bytes", boom)
    panel.set_cell_text(0, 2, "nope")
    assert "read-only" in panel.message_text


def test_switching_views_replaces_the_content(qapp, tmp_path) -> None:
    panel = NotesPanel()
    panel.show_readonly("blkA", "Notes.txt · read-only",
                        [Note(1, NOW, "a"), Note(2, NOW, "b")])
    panel.show_editable("blkB", "Analysis notes", _model(tmp_path), lambda: NOW)
    assert "blkB" in panel.header_text
    assert panel.row_count == 1  # the read-only rows are gone
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_notes_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata.notes_panel'`

- [ ] **Step 3: Write the implementation**

Create `src/tdt_ephyviewer_explorer/metadata/notes_panel.py`:

```python
"""The side panel showing a block's read-only notes or its editable analysis notes."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from PySide6 import QtWidgets
from PySide6.QtCore import Qt, Signal

from tdt_ephyviewer_explorer.metadata.notes import (
    AnalysisNotes,
    Note,
    NotesConflict,
    format_clock,
    format_day,
)

_COLUMNS = ("#", "Timestamp", "Note")


class NotesPanel(QtWidgets.QWidget):
    """A titled table of notes, either read-only or editable.

    The header names the block and the file, because several blocks may be expanded
    at once while only one panel is visible.
    """

    notes_changed = Signal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        """:param parent: Parent Qt widget."""
        super().__init__(parent)
        self._model: AnalysisNotes | None = None
        self._clock: Callable[[], datetime] = datetime.now
        self._editable = False
        self._applying = False

        self._header = QtWidgets.QLabel("")
        self._header.setWordWrap(True)
        self._message = QtWidgets.QLabel("")
        self._message.setWordWrap(True)
        self._message.setVisible(False)

        self._table = QtWidgets.QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemChanged.connect(self._on_item_changed)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._header)
        layout.addWidget(self._message)
        layout.addWidget(self._table)

    @property
    def header_text(self) -> str:
        """The panel's title line."""
        return self._header.text()

    @property
    def message_text(self) -> str:
        """The inline error message; empty when there is nothing to report."""
        return self._message.text()

    @property
    def row_count(self) -> int:
        """Number of table rows, including the trailing blank row when editable."""
        return self._table.rowCount()

    def cell_text(self, row: int, column: int) -> str:
        """Return the text of one cell.

        :param row: 0-based row.
        :param column: 0-based column.
        :returns: The cell text, or ``""`` when the cell is empty.
        """
        item = self._table.item(row, column)
        return "" if item is None else item.text()

    def item_flags(self, row: int, column: int) -> Qt.ItemFlags:
        """Return one cell's item flags, for checking editability.

        :param row: 0-based row.
        :param column: 0-based column.
        :returns: The Qt item flags.
        """
        item = self._table.item(row, column)
        return Qt.NoItemFlags if item is None else item.flags()

    def set_cell_text(self, row: int, column: int, text: str) -> None:
        """Set a cell's text as if the user had typed it, running the edit handler.

        :param row: 0-based row.
        :param column: 0-based column.
        :param text: The new text.
        """
        item = self._table.item(row, column)
        if item is None:
            item = QtWidgets.QTableWidgetItem()
            self._table.setItem(row, column, item)
        item.setText(text)

    def show_readonly(self, block_name: str, title: str, notes: Sequence[Note]) -> None:
        """Display notes that cannot be edited.

        :param block_name: Block the notes belong to.
        :param title: Subtitle naming the source file.
        :param notes: The notes to list.
        """
        self._model = None
        self._editable = False
        self._set_header(block_name, title)
        self._set_message("")
        self._fill(notes, editable=False, blank_row=False)

    def show_editable(
        self,
        block_name: str,
        title: str,
        model: AnalysisNotes,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        """Display an editable analysis-notes table.

        :param block_name: Block the notes belong to.
        :param title: Subtitle naming the source file.
        :param model: The editing model, saved after every change.
        :param clock: Supplies the wall clock for new notes; injectable for tests.
        """
        self._model = model
        self._clock = clock
        self._editable = True
        self._set_header(block_name, title)
        self._set_message("")
        self._fill(model.notes, editable=True, blank_row=True)

    def delete_row(self, row: int) -> None:
        """Delete the note in ``row`` and save.

        :param row: 0-based row; the trailing blank row is ignored.
        """
        if self._model is None or row >= len(self._model.notes):
            return
        self._model.delete(self._model.notes[row].index)
        if self._save():
            self._fill(self._model.notes, editable=True, blank_row=True)

    def _set_header(self, block_name: str, title: str) -> None:
        """Write the two-line panel title."""
        self._header.setText(f"{block_name}\n{title}")

    def _set_message(self, text: str) -> None:
        """Show ``text`` inline, hiding the label when empty."""
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def _fill(self, notes: Sequence[Note], editable: bool, blank_row: bool) -> None:
        """Rebuild the table from ``notes``.

        :param notes: Notes to show.
        :param editable: Whether the note column accepts edits.
        :param blank_row: Whether to append an empty entry row.
        """
        self._applying = True  # suppress itemChanged while populating
        try:
            self._table.setRowCount(len(notes) + (1 if blank_row else 0))
            for row, note in enumerate(notes):
                self._put(row, 0, str(note.index), editable=False)
                self._put(row, 1, self._stamp(note), editable=False)
                self._put(row, 2, note.text, editable=editable)
            if blank_row:
                row = len(notes)
                self._put(row, 0, "", editable=False)
                self._put(row, 1, "", editable=False)
                self._put(row, 2, "", editable=True)
        finally:
            self._applying = False

    @staticmethod
    def _stamp(note: Note) -> str:
        """Format a note's timestamp as ``3:49:37pm 07/27/2026``."""
        return f"{format_clock(note.timestamp)} {format_day(note.timestamp)}"

    def _put(self, row: int, column: int, text: str, editable: bool) -> None:
        """Place one cell with the right editability."""
        item = QtWidgets.QTableWidgetItem(text)
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if editable:
            flags |= Qt.ItemIsEditable
        item.setFlags(flags)
        self._table.setItem(row, column, item)

    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        """Append or edit a note when the user finishes typing in the note column."""
        if self._applying or not self._editable or self._model is None:
            return
        if item.column() != 2:
            return
        row = item.row()
        text = item.text().strip()
        existing = self._model.notes

        if row < len(existing):
            if text == existing[row].text:
                return
            self._model.edit(existing[row].index, text)
        else:
            if not text:
                return  # an empty entry row is not a note
            self._model.append(text, self._clock())

        if self._save():
            self._fill(self._model.notes, editable=True, blank_row=True)

    def _save(self) -> bool:
        """Save the model, reporting any failure inline.

        :returns: ``True`` when the save succeeded.
        """
        if self._model is None:
            return False
        try:
            self._model.save()
        except NotesConflict as exc:
            self._set_message(str(exc))
            return False
        except OSError as exc:
            self._set_message(f"Could not save notes: {exc}")
            return False
        self._set_message("")
        self.notes_changed.emit()
        return True

    def _on_context_menu(self, point) -> None:
        """Offer a delete action on the clicked row."""
        if not self._editable or self._model is None:
            return
        row = self._table.rowAt(point.y())
        if row < 0 or row >= len(self._model.notes):
            return
        menu = QtWidgets.QMenu(self)
        action = menu.addAction("Delete note")
        if menu.exec(self._table.viewport().mapToGlobal(point)) == action:
            self.delete_row(row)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_notes_panel.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/notes_panel.py tests/test_metadata_notes_panel.py
git commit -m "feat(metadata): notes side panel with editable analysis notes"
```

---

### Task 9: The metadata window

**Files:**
- Create: `src/tdt_ephyviewer_explorer/metadata/window.py`
- Test: `tests/test_metadata_window.py`

**Interfaces:**
- Consumes: `TankPicker`, `NotesPanel`, `summary.*`, `notes.AnalysisNotes`, `config_schema.load_config`.
- Produces:
  - `window.run_in_pool(fn, on_done, on_error) -> None` — default background runner
  - `window.MetadataWindow(cfg=None, runner=run_in_pool, parent=None)`
  - `MetadataWindow.set_tank(tank_dir: Path) -> None`
  - `MetadataWindow.picker -> TankPicker`
  - `MetadataWindow.panel -> NotesPanel`
  - `MetadataWindow.block_names() -> list[str]`
  - `MetadataWindow.expand_block(name: str) -> None`
  - `MetadataWindow.detail_lines(name: str) -> list[str]`
  - `MetadataWindow.open_in_explorer_requested` — `Signal(object, str)`, emits `(tank_dir, block_name)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata_window.py`:

```python
"""Tests for the metadata browser window."""
from datetime import datetime
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.stim import StimSummary
from tdt_ephyviewer_explorer.metadata.window import MetadataWindow

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def _sync(fn, on_done, on_error):
    """Runner that executes inline, so tests never wait on a thread pool."""
    try:
        on_done(fn())
    except Exception as exc:  # noqa: BLE001
        on_error(exc)


def _tank(tmp_path: Path, names=("Epi_02_Green-260727-154827", "Epi_02_Green-260727-152924")) -> Path:
    tank = tmp_path / "tank"
    for name in names:
        blk = tank / name
        blk.mkdir(parents=True)
        (blk / f"{name}.tsq").write_bytes(b"")
        (blk / "Notes.txt").write_bytes((FIXTURES / "Notes.txt").read_bytes())
        (blk / "StoresListing.txt").write_bytes((FIXTURES / "StoresListing.txt").read_bytes())
    return tank


def _window(monkeypatch, stim=(StimSummary("eS1p", 15561, 1881),), warnings=()):
    from tdt_ephyviewer_explorer.metadata import window as mod
    from dataclasses import replace

    monkeypatch.setattr(
        mod, "load_details",
        lambda summary, cfg: replace(
            summary, stim=tuple(stim),
            warnings=summary.warnings + tuple(warnings), details_loaded=True,
        ),
    )
    return MetadataWindow(load_config(), runner=_sync)


def test_set_tank_lists_blocks_in_order(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    assert win.block_names() == [
        "Epi_02_Green-260727-152924",
        "Epi_02_Green-260727-154827",
    ]


def test_collapsed_row_shows_start_and_duration(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    row = win.row_text("Epi_02_Green-260727-154827")
    assert row[1] == "15:48:30"
    assert row[2] == "9m08s"


def test_expanding_shows_gizmos_and_stim(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert any("Electrical Stim Driver" in ln for ln in lines)
    assert any("15561 pulses · 1881 combinations" in ln for ln in lines)


def test_details_are_loaded_once_per_block(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import window as mod
    from dataclasses import replace

    calls: list[str] = []

    def counting(summary, cfg):
        calls.append(summary.name)
        return replace(summary, details_loaded=True)

    monkeypatch.setattr(mod, "load_details", counting)
    win = MetadataWindow(load_config(), runner=_sync)
    win.set_tank(_tank(tmp_path))

    win.expand_block("Epi_02_Green-260727-154827")
    win.expand_block("Epi_02_Green-260727-154827")
    assert calls == ["Epi_02_Green-260727-154827"]  # cached, not re-read


def test_a_block_with_no_stim_shows_no_stim_line(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch, stim=())
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert not any("pulses" in ln for ln in lines)


def test_warnings_appear_on_the_row(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch, warnings=("eS1p: 23 rows but schema names 24",))
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert any("23 rows" in ln for ln in lines)
    assert "⚠" in win.row_text("Epi_02_Green-260727-154827")[0]


def test_a_worker_failure_is_reported_not_raised(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import window as mod

    def boom(summary, cfg):
        raise OSError("corrupt tsq")

    monkeypatch.setattr(mod, "load_details", boom)
    win = MetadataWindow(load_config(), runner=_sync)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    assert any("corrupt tsq" in ln for ln in win.detail_lines("Epi_02_Green-260727-154827"))


def test_notes_expand_opens_the_read_only_panel(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_notes("Epi_02_Green-260727-154827")
    assert "Notes.txt" in win.panel.header_text
    assert win.panel.row_count == 2


def test_analysis_notes_expand_opens_the_editable_panel(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.set_tank(tank)
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_analysis_notes("Epi_02_Green-260727-154827")
    assert "Analysis notes" in win.panel.header_text
    assert win.panel.row_count == 1  # just the blank entry row


def test_saving_an_analysis_note_writes_into_the_block_dir(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.set_tank(tank)
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_analysis_notes("Epi_02_Green-260727-154827")
    win.panel.set_cell_text(0, 2, "EMG saturated")

    written = tank / "Epi_02_Green-260727-154827" / "analysis_notes.txt"
    assert written.is_file()
    assert "EMG saturated" in written.read_bytes().decode("utf-8")


def test_saving_a_note_never_touches_notes_txt(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    original = (tank / "Epi_02_Green-260727-154827" / "Notes.txt").read_bytes()
    win.set_tank(tank)
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_analysis_notes("Epi_02_Green-260727-154827")
    win.panel.set_cell_text(0, 2, "EMG saturated")

    assert (tank / "Epi_02_Green-260727-154827" / "Notes.txt").read_bytes() == original


def test_open_in_explorer_emits_tank_and_block(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.set_tank(tank)
    seen: list[tuple] = []
    win.open_in_explorer_requested.connect(lambda t, b: seen.append((t, b)))

    win.request_open_in_explorer("Epi_02_Green-260727-154827")
    assert seen == [(tank, "Epi_02_Green-260727-154827")]


def test_switching_tanks_replaces_the_block_list(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    other = _tank(tmp_path / "second", names=("Solo-260101-000000",))
    win.set_tank(other)
    assert win.block_names() == ["Solo-260101-000000"]


def test_picker_signal_drives_set_tank(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.picker.set_tank(tank)
    assert win.block_names()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata.window'`

- [ ] **Step 3: Write the implementation**

Create `src/tdt_ephyviewer_explorer/metadata/window.py`:

```python
"""The tdt-metadata browser window: a tank picker, a block tree, and a notes panel."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from omegaconf import DictConfig
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.notes import NOTES_FILENAME, AnalysisNotes, read_notes
from tdt_ephyviewer_explorer.metadata.notes_panel import NotesPanel
from tdt_ephyviewer_explorer.metadata.summary import (
    BlockCache,
    BlockSummary,
    load_details,
    scan_tank,
)
from tdt_ephyviewer_explorer.tank_picker import TankPicker

LOADING_TEXT = "loading…"
WARNING_MARK = "⚠"


class _WorkerSignals(QtCore.QObject):
    """Signals for :class:`_Worker`; ``QRunnable`` cannot carry them itself."""

    done = Signal(object)
    failed = Signal(object)


class _Worker(QtCore.QRunnable):
    """Runs a callable on the thread pool and reports the outcome on the GUI thread."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        """:param fn: The work to run off the GUI thread."""
        super().__init__()
        self._fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        """Execute the callable, emitting ``done`` or ``failed``."""
        try:
            self.signals.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - reported, never raised into Qt
            self.signals.failed.emit(exc)


def run_in_pool(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_error: Callable[[BaseException], None],
) -> None:
    """Run ``fn`` on the global thread pool, delivering the result to the GUI thread.

    :param fn: The work to run.
    :param on_done: Called with the result on success.
    :param on_error: Called with the exception on failure.
    """
    worker = _Worker(fn)
    worker.signals.done.connect(on_done)
    worker.signals.failed.connect(on_error)
    QtCore.QThreadPool.globalInstance().start(worker)


def format_duration(seconds: float | None) -> str:
    """Format a duration as ``9m08s``, or ``—`` when unknown.

    :param seconds: Duration in seconds, or ``None``.
    :returns: The formatted duration.
    """
    if seconds is None:
        return "—"
    total = int(round(seconds))
    return f"{total // 60}m{total % 60:02d}s"


def format_start(start: datetime | None) -> str:
    """Format a start time as ``15:48:30``, or ``—`` when unknown.

    :param start: The start timestamp, or ``None``.
    :returns: The formatted time of day.
    """
    return "—" if start is None else start.strftime("%H:%M:%S")


class MetadataWindow(QtWidgets.QWidget):
    """Browse a tank's blocks and their session metadata.

    Text metadata for every block is read up front; the ``.tsq`` index and the stim
    parameter stores are read only when a block is expanded, and cached thereafter.
    """

    open_in_explorer_requested = Signal(object, str)  # (tank_dir: Path, block: str)

    def __init__(
        self,
        cfg: DictConfig | None = None,
        runner: Callable[
            [Callable[[], Any], Callable[[Any], None], Callable[[BaseException], None]], None
        ] = run_in_pool,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """:param cfg: Configuration; loaded from the packaged config when ``None``.
        :param runner: Schedules background work. Tests inject a synchronous one.
        :param parent: Parent Qt widget."""
        super().__init__(parent)
        self._cfg = cfg if cfg is not None else load_config()
        self._runner = runner
        self._cache = BlockCache()
        self._tank_dir: Path | None = None
        self._items: dict[str, QtWidgets.QTreeWidgetItem] = {}

        self._picker = TankPicker()
        self._picker.tank_changed.connect(self.set_tank)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Block", "Start", "Duration"])
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)

        self._panel = NotesPanel()
        self._panel.setVisible(False)
        self._panel.notes_changed.connect(self._on_notes_changed)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self._tree)
        splitter.addWidget(self._panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._picker)
        layout.addWidget(splitter)
        self.setWindowTitle("tdt-metadata")

    @property
    def picker(self) -> TankPicker:
        """The tank picker at the top of the window."""
        return self._picker

    @property
    def panel(self) -> NotesPanel:
        """The notes side panel."""
        return self._panel

    @property
    def tank_dir(self) -> Path | None:
        """The tank currently browsed, or ``None``."""
        return self._tank_dir

    def set_tank(self, tank_dir: Path) -> None:
        """Scan a tank's text metadata and rebuild the block tree.

        :param tank_dir: The tank directory.
        """
        self._tank_dir = tank_dir
        self._picker.show_tank(tank_dir)
        self._cache.use_tank(tank_dir)
        self._panel.setVisible(False)
        self._tree.clear()
        self._items = {}
        for summary in scan_tank(tank_dir):
            cached = self._cache.get(summary.name)
            if cached is None:
                self._cache.put(summary)
                cached = summary
            self._add_row(cached)

    def block_names(self) -> list[str]:
        """The block names currently listed, in tree order."""
        return [
            self._tree.topLevelItem(i).data(0, Qt.UserRole)
            for i in range(self._tree.topLevelItemCount())
        ]

    def row_text(self, name: str) -> list[str]:
        """The three collapsed-row columns for one block.

        :param name: Block name.
        :returns: ``[block, start, duration]``.
        """
        item = self._items[name]
        return [item.text(0), item.text(1), item.text(2)]

    def detail_lines(self, name: str) -> list[str]:
        """The expanded child rows for one block, flattened depth-first.

        :param name: Block name.
        :returns: One string per child row.
        """
        out: list[str] = []

        def walk(node: QtWidgets.QTreeWidgetItem) -> None:
            for i in range(node.childCount()):
                child = node.child(i)
                text = " ".join(t for t in (child.text(0), child.text(1)) if t)
                out.append(text)
                walk(child)

        walk(self._items[name])
        return out

    def expand_block(self, name: str) -> None:
        """Expand a block, loading its details on first expansion.

        :param name: Block name.
        """
        item = self._items[name]
        item.setExpanded(True)
        self._ensure_details(name)

    def open_notes(self, name: str) -> None:
        """Show the block's read-only ``Notes.txt`` in the side panel.

        :param name: Block name.
        """
        summary = self._require(name)
        self._panel.setVisible(True)
        self._panel.show_readonly(name, f"{NOTES_FILENAME} · read-only", summary.notes)

    def open_analysis_notes(self, name: str) -> None:
        """Show the block's editable analysis notes in the side panel.

        :param name: Block name.
        """
        summary = self._require(name)
        filename = str(self._cfg.metadata.analysis_notes_filename)
        header = read_notes(summary.path / NOTES_FILENAME)
        model = AnalysisNotes.load(summary.path, filename, header)
        self._panel.setVisible(True)
        self._panel.show_editable(name, f"Analysis notes · {filename}", model)

    def request_open_in_explorer(self, name: str) -> None:
        """Ask the application to open this block in tdt-explore.

        :param name: Block name.
        """
        if self._tank_dir is not None:
            self.open_in_explorer_requested.emit(self._tank_dir, name)

    def _require(self, name: str) -> BlockSummary:
        """Return the cached summary for ``name``.

        :raises KeyError: If the block is not listed.
        """
        summary = self._cache.get(name)
        if summary is None:
            raise KeyError(f"no such block: {name}")
        return summary

    def _add_row(self, summary: BlockSummary) -> None:
        """Add or refresh one block's top-level row and its children."""
        item = self._items.get(summary.name)
        if item is None:
            item = QtWidgets.QTreeWidgetItem(self._tree)
            item.setData(0, Qt.UserRole, summary.name)
            self._items[summary.name] = item
        mark = f"{WARNING_MARK} " if summary.warnings else ""
        item.setText(0, f"{mark}{summary.name}")
        item.setText(1, format_start(summary.start))
        item.setText(2, format_duration(summary.duration_s))
        self._rebuild_children(item, summary)

    def _rebuild_children(
        self, item: QtWidgets.QTreeWidgetItem, summary: BlockSummary
    ) -> None:
        """Replace a block row's children to match its current summary."""
        item.takeChildren()
        for label, value in (
            ("Experiment", summary.experiment),
            ("Subject", summary.subject),
            ("User", summary.user),
        ):
            if value:
                self._child(item, label, value)

        gizmos = QtWidgets.QTreeWidgetItem(item, ["Gizmos", ""])
        if not summary.details_loaded:
            QtWidgets.QTreeWidgetItem(gizmos, [LOADING_TEXT, ""])
        for gizmo in summary.gizmos:
            kind = gizmo.kind or ""
            QtWidgets.QTreeWidgetItem(
                gizmos, [f"{gizmo.object_id}  {kind}".strip(), " ".join(gizmo.stores)]
            )

        if not summary.details_loaded:
            stim = QtWidgets.QTreeWidgetItem(item, ["Stimulation", ""])
            QtWidgets.QTreeWidgetItem(stim, [LOADING_TEXT, ""])
        elif summary.stim:
            stim = QtWidgets.QTreeWidgetItem(item, ["Stimulation", ""])
            for entry in summary.stim:
                QtWidgets.QTreeWidgetItem(
                    stim,
                    [
                        entry.store,
                        f"{entry.n_pulses} pulses · {entry.n_combinations} combinations",
                    ],
                )

        self._notes_row(item, "Notes", len(summary.notes), summary.name, analysis=False)
        self._notes_row(
            item, "Analysis notes", self._analysis_count(summary), summary.name, analysis=True
        )

        for warning in summary.warnings:
            self._child(item, WARNING_MARK, warning)

    def _analysis_count(self, summary: BlockSummary) -> int:
        """Count the block's saved analysis notes without creating the file."""
        filename = str(self._cfg.metadata.analysis_notes_filename)
        return len(read_notes(summary.path / filename).notes)

    def _notes_row(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        label: str,
        count: int,
        block: str,
        analysis: bool,
    ) -> None:
        """Add a notes row carrying a count and an Expand button."""
        row = QtWidgets.QTreeWidgetItem(parent, [label, f"{count} note{'' if count == 1 else 's'}"])
        button = QtWidgets.QPushButton("Expand")
        if analysis:
            button.clicked.connect(lambda: self.open_analysis_notes(block))
        else:
            button.clicked.connect(lambda: self.open_notes(block))
        self._tree.setItemWidget(row, 2, button)

    @staticmethod
    def _child(parent: QtWidgets.QTreeWidgetItem, label: str, value: str) -> None:
        """Add a simple two-column child row."""
        QtWidgets.QTreeWidgetItem(parent, [label, value])

    def _ensure_details(self, name: str) -> None:
        """Load a block's tier-1 and tier-2 data once, off the GUI thread."""
        summary = self._require(name)
        if summary.details_loaded:
            return
        self._runner(
            lambda: load_details(summary, self._cfg),
            lambda result: self._on_details(result),
            lambda exc: self._on_details_failed(name, exc),
        )

    def _on_details(self, summary: BlockSummary) -> None:
        """Cache and render a loaded summary."""
        self._cache.put(summary)
        self._add_row(summary)
        self._items[summary.name].setExpanded(True)

    def _on_details_failed(self, name: str, exc: BaseException) -> None:
        """Record a worker failure on the block's row rather than raising."""
        from dataclasses import replace

        summary = self._require(name)
        failed = replace(
            summary,
            warnings=summary.warnings + (f"could not load details: {exc}",),
            details_loaded=True,
        )
        self._cache.put(failed)
        self._add_row(failed)
        self._items[name].setExpanded(True)

    def _on_item_expanded(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Load details when a top-level block row is expanded."""
        name = item.data(0, Qt.UserRole)
        if name:
            self._ensure_details(name)

    def _on_notes_changed(self) -> None:
        """Refresh note counts after the panel saves."""
        for name in list(self._items):
            self._add_row(self._require(name))

    def _top_level_name(self, item: QtWidgets.QTreeWidgetItem | None) -> str | None:
        """Walk up to the owning block row and return its name."""
        while item is not None:
            name = item.data(0, Qt.UserRole)
            if name:
                return str(name)
            item = item.parent()
        return None

    def _on_context_menu(self, point) -> None:
        """Offer 'Open in tdt-explore' on the clicked block."""
        name = self._top_level_name(self._tree.itemAt(point))
        if name is None:
            return
        menu = QtWidgets.QMenu(self)
        action = menu.addAction("Open in tdt-explore")
        if menu.exec(self._tree.viewport().mapToGlobal(point)) == action:
            self.request_open_in_explorer(name)

    def _on_double_click(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        """Double-clicking a block opens it in tdt-explore."""
        name = self._top_level_name(item)
        if name is not None:
            self.request_open_in_explorer(name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_metadata_window.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/window.py tests/test_metadata_window.py
git commit -m "feat(metadata): browser window with block tree and side panel"
```

---

### Task 10: Entry point, integration test, and docs

**Files:**
- Create: `src/tdt_ephyviewer_explorer/metadata/app.py`
- Modify: `pyproject.toml` (`[project.scripts]`)
- Modify: `tests/test_integration_tdt.py` (add one case)
- Modify: `README.md`, `.claude/CLAUDE.md`
- Test: `tests/test_metadata_app.py`

**Interfaces:**
- Consumes: `MetadataWindow`, the existing `App` from `app.py`.
- Produces:
  - `metadata.app.MetadataApp(cfg=None)` with `.window` and `.explorers: list[App]`
  - `metadata.app.main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata_app.py`:

```python
"""Tests for the tdt-metadata entry point."""
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.metadata.app import MetadataApp


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_constructs_a_window(qapp) -> None:
    app = MetadataApp()
    assert app.window is not None
    assert app.explorers == []


def test_open_in_explorer_launches_the_control_window(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import app as mod

    opened: list[tuple] = []

    class _FakeApp:
        def __init__(self, cfg=None):
            self.control_window = _FakeControl()

        def open_tank(self, tank_dir, block=None):
            opened.append((tank_dir, block))

    class _FakeControl:
        def show(self):
            pass

    monkeypatch.setattr(mod, "App", _FakeApp)
    app = MetadataApp()
    app.window.open_in_explorer_requested.emit(tmp_path, "blk")

    assert opened == [(tmp_path, "blk")]
    assert len(app.explorers) == 1


def test_main_without_tank_returns_zero(qapp, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import app as mod

    class _FakeQApp:
        def exec(self):
            return 0

    monkeypatch.setattr(mod, "mkQApp", lambda: _FakeQApp())
    assert mod.main([]) == 0


def test_main_with_a_tank_loads_it(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import app as mod

    tank = tmp_path / "tank"
    blk = tank / "blk-1"
    blk.mkdir(parents=True)
    (blk / "blk-1.tsq").write_bytes(b"")

    class _FakeQApp:
        def exec(self):
            return 0

    seen: list[Path] = []
    monkeypatch.setattr(mod, "mkQApp", lambda: _FakeQApp())
    monkeypatch.setattr(mod.MetadataWindow, "set_tank", lambda self, t: seen.append(t))
    assert mod.main(["--tank", str(tank)]) == 0
    assert seen == [tank]
```

Append to `tests/test_integration_tdt.py`:

```python
def test_stim_summary_matches_the_reference_block() -> None:
    """The reference block delivers 15561 pulses under 1881 distinct settings.

    Voice B is the return electrode (``countB == 0`` for every event) and 438 of the
    15999 events have ``chanA == 0``, so they deliver nothing: 15999 - 438 = 15561.
    """
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.metadata.stim import read_stim_summaries
    from tdt_ephyviewer_explorer.tank import read_headers

    block = Path(BLOCK)  # type: ignore[arg-type]
    if block.name != "Epi_02_Green-260727-154827":
        pytest.skip("reference figures apply to Epi_02_Green-260727-154827 only")

    headers = read_headers(block)
    summaries, warnings = read_stim_summaries(block, load_config(), headers=headers)
    assert warnings == []
    assert [(s.store, s.n_pulses, s.n_combinations) for s in summaries] == [
        ("eS1p", 15561, 1881)
    ]


def test_text_metadata_reads_the_real_block() -> None:
    from tdt_ephyviewer_explorer.metadata.summary import read_text_metadata

    block = Path(BLOCK)  # type: ignore[arg-type]
    summary = read_text_metadata(block)
    assert summary.name == block.name
    assert summary.gizmos, "expected StoresListing.txt to yield gizmos"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_metadata_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tdt_ephyviewer_explorer.metadata.app'`

- [ ] **Step 3: Write the entry point**

Create `src/tdt_ephyviewer_explorer/metadata/app.py`:

```python
"""tdt-metadata application entry point."""
from __future__ import annotations

import argparse
from pathlib import Path

from ephyviewer import mkQApp
from omegaconf import DictConfig

from tdt_ephyviewer_explorer.app import App
from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.window import MetadataWindow


class MetadataApp:
    """Owns the metadata window and any explorer windows launched from it."""

    def __init__(self, cfg: DictConfig | None = None) -> None:
        """:param cfg: Configuration; loaded from the packaged config when ``None``."""
        self._cfg = cfg if cfg is not None else load_config()
        self.window = MetadataWindow(self._cfg)
        self.explorers: list[App] = []
        self.window.open_in_explorer_requested.connect(self._on_open_in_explorer)

    def _on_open_in_explorer(self, tank_dir: Path, block: str) -> None:
        """Open a block in a new tdt-explore control window.

        :param tank_dir: The tank holding the block.
        :param block: Block name to preselect.
        """
        explorer = App(self._cfg)
        explorer.open_tank(tank_dir, block)
        explorer.control_window.show()
        self.explorers.append(explorer)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tdt-metadata`` console script.

    :param argv: CLI args; an optional ``--tank``. With none, the window opens empty
        and the tank is chosen with the in-window picker.
    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(prog="tdt-metadata")
    parser.add_argument(
        "--tank", default=None, type=Path, help="Synapse tank directory (optional)"
    )
    args = parser.parse_args(argv)

    qapp = mkQApp()
    app = MetadataApp()
    if args.tank is not None:
        app.window.set_tank(args.tank)
    app.window.show()
    return int(qapp.exec())
```

- [ ] **Step 4: Register the console script**

In `pyproject.toml`, replace the `[project.scripts]` table:

```toml
[project.scripts]
tdt-explore = "tdt_ephyviewer_explorer.app:main"
tdt-metadata = "tdt_ephyviewer_explorer.metadata.app:main"
```

- [ ] **Step 5: Run the tests**

Run: `uv sync && uv run pytest tests/test_metadata_app.py -v`
Expected: 4 passed

- [ ] **Step 6: Update the docs**

In `README.md`, under `## Running`, after the existing `tdt-explore` usage, add:

```markdown
`--tank` is optional for both apps; without it the window opens empty and you pick a
tank with the in-window Browse button.

## Session metadata browser

```
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
```

In `.claude/CLAUDE.md`, under `### Commands`, add:

```markdown
* Run metadata browser: `uv run tdt-metadata [--tank "<tank dir>"]`.
```

In `.claude/CLAUDE.md`, under `### Key concepts`, extend the **Session** bullet with:

```markdown
  **Exception:** `tdt-metadata` writes `<block>/analysis_notes.txt` — the one sanctioned
  write into a raw block dir, for post-hoc annotations. Nothing else may write there.
```

In `.claude/CLAUDE.md`, after the pipeline section, add:

```markdown
### The metadata browser (`metadata/`)
A second app (`tdt-metadata`) that browses session metadata without opening viewers, built
on the same Qt-free-core rule: `listing.py` (StoresListing → gizmos), `notes.py` (Notes.txt
parse/render plus the editable `AnalysisNotes` model), `stim.py` (eS1p → pulses and unique
parameter combinations), `summary.py` (`BlockSummary` and the three read tiers), with
`window.py`/`notes_panel.py` as the Qt shell. `tank_picker.py` is shared with the Control
Window. Reads are tiered — text sidecars for all blocks, `.tsq` headers and `eS1p` only on
expand — so don't move the expensive reads into the eager path.
```

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass.

Then run the real-data check:

```bash
TDT_EXPLORE_TEST_BLOCK="/c/TDT/Synapse/Tanks/cnn_gp_mep_all_udp_v2-260610-173723/Epi_02_Green-260727-154827" uv run pytest tests/test_integration_tdt.py -v
```

Expected: passes, asserting 15561 pulses and 1881 combinations.

- [ ] **Step 8: Launch the app and confirm it works**

```bash
uv run tdt-metadata --tank "C:/TDT/Synapse/Tanks/cnn_gp_mep_all_udp_v2-260610-173723"
```

Confirm by hand: blocks list with durations; expanding `Epi_02_Green-260727-154827` shows the
eStim gizmo and `15561 pulses · 1881 combinations`; the Notes Expand button shows the two real
notes; typing an analysis note creates `analysis_notes.txt` in the block directory and leaves
`Notes.txt` untouched; right-click opens `tdt-explore`.

- [ ] **Step 9: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/app.py pyproject.toml tests/test_metadata_app.py tests/test_integration_tdt.py README.md .claude/CLAUDE.md
git commit -m "feat(metadata): tdt-metadata entry point, integration test, docs"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: packaging and module tree (Tasks 3–10);
the shared picker and the `tdt-explore` changes (Tasks 1–2); the data model (Tasks 3–7); the
three read tiers (Tasks 6–7); the window, tree, side panel, and "Open in tdt-explore" (Tasks
8–10); analysis notes location, format, editing, and atomic writing (Tasks 4–5, 8); the full
error-handling table (Tasks 6–9); the testing plan (every task) and the documentation updates
(Task 10).

**Deliberate deviations from the spec**, both noted at their point of use:
1. `textio.py` was added — the spec's tree omitted it, but three modules need the same
   encoding-tolerant read and `notes.py` needs the atomic write.
2. The spec named test files `test_metadata_summary.py` and so on; the notes work is split
   across `test_metadata_notes.py` and `test_metadata_analysis_notes.py` because parsing and
   the editing model are separate deliverables landing in separate tasks.

**Known risks the implementer should watch:**
- `test_save_refuses_when_the_file_changed_underneath` depends on filesystem mtime resolution.
  The fix, if it is flaky, is a content hash — not a sleep and not a weaker assertion.
- `MetadataWindow._notes_row` puts a `QPushButton` in a tree row. If Qt drops the widget when
  `takeChildren()` rebuilds the row, re-set it after the rebuild rather than caching the
  button.
