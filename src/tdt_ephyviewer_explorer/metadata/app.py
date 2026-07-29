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
