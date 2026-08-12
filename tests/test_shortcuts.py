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
