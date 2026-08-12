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
