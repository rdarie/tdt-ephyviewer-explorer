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
