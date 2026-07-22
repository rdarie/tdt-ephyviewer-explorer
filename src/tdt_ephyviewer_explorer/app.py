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
