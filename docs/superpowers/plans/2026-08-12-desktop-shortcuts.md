# Desktop Shortcuts Installer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `tdt-install-shortcuts` console script that drops Windows desktop shortcuts for `tdt-explore` and `tdt-metadata`, launched via `pythonw.exe` (no console flash).

**Architecture:** A new Qt-free module `shortcuts.py` builds `ShortcutSpec`s and generates PowerShell that creates the `.lnk` files through the built-in `WScript.Shell` COM object. Two new `__main__.py` files let `pythonw -m <package>` launch each GUI. No third-party dependency is added.

**Tech Stack:** Python 3.12+, stdlib only (`subprocess`, `sys`, `pathlib`, `dataclasses`), PowerShell's `WScript.Shell` at runtime, pytest for tests, `uv` for running.

## Global Constraints

- Python 3.12+; strict `typing`; reST-style docstrings.
- No new dependencies — stdlib + PowerShell only.
- Qt-free core: `shortcuts.py` and its tests import no Qt / ephyviewer. Test suite stays headless.
- No hardcoded absolute paths; resolve interpreter/desktop at runtime.
- Each `src/` module gets a mirror `tests/test_<module>.py`.
- Windows-only behavior for actual install; guard on `sys.platform == "win32"`.
- Concise commit messages.

---

### Task 1: `shortcuts.py` core — specs, pythonw resolution, PowerShell generation

**Files:**
- Create: `src/tdt_ephyviewer_explorer/shortcuts.py`
- Test: `tests/test_shortcuts.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `@dataclass(frozen=True) class ShortcutSpec` with fields `name: str`, `target: Path`, `arguments: str`, `working_dir: Path`, `description: str`.
  - `find_pythonw(executable: Path | None = None) -> Path`
  - `explorer_specs(pythonw: Path, working_dir: Path | None = None) -> list[ShortcutSpec]`
  - `build_powershell(spec: ShortcutSpec) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_shortcuts.py
"""Tests for the Windows desktop-shortcut installer (Qt-free, headless)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tdt_ephyviewer_explorer import shortcuts
from tdt_ephyviewer_explorer.shortcuts import ShortcutSpec


def _pythonw() -> Path:
    return Path(r"C:\venv\Scripts\pythonw.exe")


def test_find_pythonw_prefers_sibling(tmp_path: Path) -> None:
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("")
    (scripts / "pythonw.exe").write_text("")
    assert shortcuts.find_pythonw(scripts / "python.exe") == scripts / "pythonw.exe"


def test_find_pythonw_falls_back_to_given_executable(tmp_path: Path) -> None:
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    (scripts / "python.exe").write_text("")
    # No pythonw.exe present -> fall back to the interpreter we were given.
    assert shortcuts.find_pythonw(scripts / "python.exe") == scripts / "python.exe"


def test_explorer_specs_target_the_two_apps() -> None:
    specs = shortcuts.explorer_specs(_pythonw())
    assert [s.name for s in specs] == ["TDT Explore", "TDT Metadata"]
    assert all(s.target == _pythonw() for s in specs)
    assert specs[0].arguments == "-m tdt_ephyviewer_explorer"
    assert specs[1].arguments == "-m tdt_ephyviewer_explorer.metadata"


def test_build_powershell_embeds_spec_fields() -> None:
    spec = ShortcutSpec(
        name="TDT Explore",
        target=_pythonw(),
        arguments="-m tdt_ephyviewer_explorer",
        working_dir=Path(r"C:\Users\lab"),
        description="Launch TDT Explore",
    )
    ps = shortcuts.build_powershell(spec)
    assert "GetFolderPath('Desktop')" in ps
    assert "TDT Explore.lnk" in ps
    assert r"C:\venv\Scripts\pythonw.exe" in ps
    assert "-m tdt_ephyviewer_explorer" in ps
    assert r"C:\Users\lab" in ps
    assert "Launch TDT Explore" in ps


def test_build_powershell_escapes_single_quotes() -> None:
    spec = ShortcutSpec(
        name="TDT Explore",
        target=Path(r"C:\va'b\pythonw.exe"),
        arguments="-m x",
        working_dir=Path(r"C:\home"),
        description="d",
    )
    ps = shortcuts.build_powershell(spec)
    # A literal single quote is doubled for PowerShell single-quoted strings.
    assert "va''b" in ps
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shortcuts.py -v`
Expected: FAIL — `AttributeError` / `ImportError` (module `shortcuts` not found).

- [ ] **Step 3: Write minimal implementation**

```python
# src/tdt_ephyviewer_explorer/shortcuts.py
"""Create Windows desktop shortcuts for the tdt-explore and tdt-metadata GUIs.

Qt-free by design: this module only builds shortcut specs and the PowerShell that
creates the ``.lnk`` files, so it is importable and testable on any platform. The
actual shortcut creation (:func:`install`) is Windows-only.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShortcutSpec:
    """A single desktop shortcut to create.

    :ivar name: Shortcut display name (the ``.lnk`` stem).
    :ivar target: Executable the shortcut runs (the venv ``pythonw.exe``).
    :ivar arguments: Command-line arguments passed to ``target``.
    :ivar working_dir: Working directory set on the shortcut.
    :ivar description: Shortcut comment/tooltip.
    """

    name: str
    target: Path
    arguments: str
    working_dir: Path
    description: str


def find_pythonw(executable: Path | None = None) -> Path:
    """Locate ``pythonw.exe`` for launching a GUI without a console window.

    :param executable: Interpreter to derive from; defaults to ``sys.executable``.
    :returns: The sibling ``pythonw.exe`` if it exists, else ``executable`` itself.
    """
    exe = Path(executable) if executable is not None else Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return pythonw if pythonw.exists() else exe


def explorer_specs(pythonw: Path, working_dir: Path | None = None) -> list[ShortcutSpec]:
    """Build the shortcut specs for the two GUI apps.

    :param pythonw: Interpreter the shortcuts invoke (see :func:`find_pythonw`).
    :param working_dir: Working directory for the shortcuts; defaults to the user
        home (``Path.home()``). The apps read the packaged config and per-tank
        sessions, so cwd is not load-bearing.
    :returns: One spec per app, Explore first then Metadata.
    """
    home = working_dir if working_dir is not None else Path.home()
    return [
        ShortcutSpec(
            name="TDT Explore",
            target=pythonw,
            arguments="-m tdt_ephyviewer_explorer",
            working_dir=home,
            description="Launch TDT Explore",
        ),
        ShortcutSpec(
            name="TDT Metadata",
            target=pythonw,
            arguments="-m tdt_ephyviewer_explorer.metadata",
            working_dir=home,
            description="Launch TDT Metadata (session browser)",
        ),
    ]


def _ps_quote(value: str) -> str:
    """Quote a string as a PowerShell single-quoted literal (doubling ``'``)."""
    return "'" + value.replace("'", "''") + "'"


def build_powershell(spec: ShortcutSpec) -> str:
    """Generate the PowerShell that creates one shortcut on the Desktop.

    The Desktop directory is resolved inside PowerShell via
    ``[Environment]::GetFolderPath('Desktop')`` so OneDrive desktop redirection is
    honored.

    :param spec: The shortcut to create.
    :returns: A PowerShell script fragment.
    """
    name = _ps_quote(f"{spec.name}.lnk")
    target = _ps_quote(str(spec.target))
    arguments = _ps_quote(spec.arguments)
    working_dir = _ps_quote(str(spec.working_dir))
    description = _ps_quote(spec.description)
    return (
        "$ws = New-Object -ComObject WScript.Shell\n"
        "$desktop = [Environment]::GetFolderPath('Desktop')\n"
        f"$lnk = $ws.CreateShortcut((Join-Path $desktop {name}))\n"
        f"$lnk.TargetPath = {target}\n"
        f"$lnk.Arguments = {arguments}\n"
        f"$lnk.WorkingDirectory = {working_dir}\n"
        f"$lnk.Description = {description}\n"
        "$lnk.Save()\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_shortcuts.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/shortcuts.py tests/test_shortcuts.py
git commit -m "feat(shortcuts): spec + PowerShell generation core"
```

---

### Task 2: `install` + `main` entry point

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/shortcuts.py` (append `install` and `main`)
- Test: `tests/test_shortcuts.py` (add cases)

**Interfaces:**
- Consumes: `ShortcutSpec`, `find_pythonw`, `explorer_specs`, `build_powershell` from Task 1.
- Produces:
  - `install(specs: list[ShortcutSpec]) -> list[Path]`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_shortcuts.py
def test_install_raises_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortcuts.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows"):
        shortcuts.install(shortcuts.explorer_specs(_pythonw()))


def test_install_runs_powershell_per_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shortcuts.sys, "platform", "win32")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return None

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    specs = shortcuts.explorer_specs(_pythonw())
    created = shortcuts.install(specs)
    assert len(calls) == len(specs)
    assert all(cmd[0].lower().startswith("powershell") for cmd in calls)
    assert [p.name for p in created] == ["TDT Explore.lnk", "TDT Metadata.lnk"]


def test_main_invokes_install(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_install(specs):  # type: ignore[no-untyped-def]
        seen["specs"] = specs
        return [Path("TDT Explore.lnk"), Path("TDT Metadata.lnk")]

    monkeypatch.setattr(shortcuts, "install", fake_install)
    rc = shortcuts.main([])
    assert rc == 0
    assert len(seen["specs"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_shortcuts.py -v`
Expected: FAIL — `install` / `main` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `src/tdt_ephyviewer_explorer/shortcuts.py`:

```python
import argparse


def install(specs: list[ShortcutSpec]) -> list[Path]:
    """Create the given shortcuts on the current user's Desktop.

    :param specs: Shortcuts to create.
    :returns: Paths of the created ``.lnk`` files (Desktop-relative names).
    :raises RuntimeError: If not running on Windows.
    """
    if sys.platform != "win32":
        raise RuntimeError("Desktop shortcuts can only be installed on Windows.")
    created: list[Path] = []
    for spec in specs:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", build_powershell(spec)],
            check=True,
        )
        created.append(Path(f"{spec.name}.lnk"))
    return created


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``tdt-install-shortcuts`` console script.

    :param argv: CLI args (only ``-h`` is meaningful).
    :returns: Process exit code.
    """
    argparse.ArgumentParser(
        prog="tdt-install-shortcuts",
        description="Create desktop shortcuts for tdt-explore and tdt-metadata (Windows).",
    ).parse_args(argv)

    pythonw = find_pythonw()
    created = install(explorer_specs(pythonw))
    print("Created desktop shortcuts:")
    for path in created:
        print(f"  {path.name}")
    return 0
```

Move the `import argparse` line to the top of the file with the other imports (keep imports grouped; do not leave it mid-module).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_shortcuts.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/shortcuts.py tests/test_shortcuts.py
git commit -m "feat(shortcuts): install shortcuts and CLI entry point"
```

---

### Task 3: `__main__.py` for both packages

**Files:**
- Create: `src/tdt_ephyviewer_explorer/__main__.py`
- Create: `src/tdt_ephyviewer_explorer/metadata/__main__.py`

**Interfaces:**
- Consumes: `app.main` and `metadata.app.main` (existing).
- Produces: `python -m tdt_ephyviewer_explorer` and `python -m tdt_ephyviewer_explorer.metadata` launch the GUIs.

No unit test — these are one-line launch shims that would require a Qt event loop to exercise. They are verified in Task 5's manual check.

- [ ] **Step 1: Create the explore shim**

```python
# src/tdt_ephyviewer_explorer/__main__.py
"""``python -m tdt_ephyviewer_explorer`` launches the tdt-explore GUI."""
from __future__ import annotations

from tdt_ephyviewer_explorer.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create the metadata shim**

```python
# src/tdt_ephyviewer_explorer/metadata/__main__.py
"""``python -m tdt_ephyviewer_explorer.metadata`` launches the tdt-metadata GUI."""
from __future__ import annotations

from tdt_ephyviewer_explorer.metadata.app import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Verify imports resolve without launching Qt**

Run: `uv run python -c "import tdt_ephyviewer_explorer.__main__, tdt_ephyviewer_explorer.metadata.__main__; print('ok')"`
Expected: prints `ok` (module import must not call `main()`).

- [ ] **Step 4: Commit**

```bash
git add src/tdt_ephyviewer_explorer/__main__.py src/tdt_ephyviewer_explorer/metadata/__main__.py
git commit -m "feat: add -m launch shims for explore and metadata"
```

---

### Task 4: Register the console script

**Files:**
- Modify: `pyproject.toml` (`[project.scripts]`, lines 20-22)

**Interfaces:**
- Consumes: `shortcuts.main` from Task 2.
- Produces: `tdt-install-shortcuts` console command.

- [ ] **Step 1: Add the entry point**

In `pyproject.toml`, under `[project.scripts]`, add a third line:

```toml
[project.scripts]
tdt-explore = "tdt_ephyviewer_explorer.app:main"
tdt-metadata = "tdt_ephyviewer_explorer.metadata.app:main"
tdt-install-shortcuts = "tdt_ephyviewer_explorer.shortcuts:main"
```

- [ ] **Step 2: Re-sync so the script is installed**

Run: `uv sync`
Expected: completes; `tdt-install-shortcuts` becomes available.

- [ ] **Step 3: Verify the command resolves**

Run: `uv run tdt-install-shortcuts -h`
Expected: prints the argparse help for `tdt-install-shortcuts` and exits 0 (does not create shortcuts).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: register tdt-install-shortcuts console script"
```

---

### Task 5: Full suite + manual Windows verification + README

**Files:**
- Modify: `README.md` (add a shortcuts usage note near the run commands)

**Interfaces:**
- Consumes: everything above.
- Produces: user-facing docs; confirmed working shortcuts.

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest`
Expected: PASS, no new failures; `tests/test_shortcuts.py` included.

- [ ] **Step 2: Create the shortcuts for real (Windows)**

Run: `uv run tdt-install-shortcuts`
Expected: prints two created shortcut names; `TDT Explore.lnk` and `TDT Metadata.lnk` appear on the Desktop.

- [ ] **Step 3: Launch each shortcut**

Double-click **TDT Explore** and **TDT Metadata** on the Desktop.
Expected: each GUI opens with the in-window tank picker and **no console window** appears alongside it.

- [ ] **Step 4: Document usage in the README**

Add a short subsection near the existing run instructions:

```markdown
### Desktop shortcuts (Windows)

Create Desktop shortcuts for the two GUIs (run once, per machine):

    uv run tdt-install-shortcuts

This drops **TDT Explore** and **TDT Metadata** on your Desktop. They launch the
apps with no console window; pick a tank with the in-window picker. Re-run the
command after moving the project or recreating the virtual environment.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document tdt-install-shortcuts"
```
