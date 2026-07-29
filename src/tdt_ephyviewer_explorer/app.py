"""tdt-explore application entry point and orchestrator."""
from __future__ import annotations

import argparse
from pathlib import Path

from ephyviewer import MainViewer, mkQApp
from omegaconf import DictConfig

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.control_window import ControlWindow
from tdt_ephyviewer_explorer.launcher import launch_block
from tdt_ephyviewer_explorer.session import Session


class App:
    """Owns the control window and any open block windows."""

    def __init__(self, cfg: DictConfig | None = None) -> None:
        """Construct the control window and wire its launch signal.

        :param cfg: Configuration (default: loaded from config schema).
        """
        self._cfg = cfg if cfg is not None else load_config()
        self.control_window = ControlWindow(self._cfg)
        self.windows: list[MainViewer] = []
        self.control_window.launch_requested.connect(self._on_launch)

    def open_tank(self, tank_dir: Path, block: str | None = None) -> None:
        """Point the control window at a tank, populating its block selector.

        :param tank_dir: Tank directory containing block subdirectories.
        :param block: Block name to preselect; otherwise ``set_tank`` selects the
            first block (if any).
        :returns: None.
        """
        self.control_window.set_tank(tank_dir, block)

    def _on_launch(self, session: Session) -> None:
        """Launch a block window for the control window's current tank.

        :param session: Composed viewer session from the control window.
        :returns: None.
        """
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
