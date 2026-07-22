"""Tank/block discovery and header scanning."""
from __future__ import annotations

from pathlib import Path

import tdt

from tdt_ephyviewer_explorer.stores import StoreInfo, store_info_from_header


def list_blocks(tank_dir: Path) -> list[Path]:
    """List block directories inside a tank.

    A block directory is any immediate subdirectory containing a ``*.tsq`` file.

    :param tank_dir: Path to the Synapse tank directory.
    :returns: Sorted list of block directory paths.
    """
    return sorted(
        p for p in tank_dir.iterdir() if p.is_dir() and any(p.glob("*.tsq"))
    )


def scan_block(block_path: Path) -> list[StoreInfo]:
    """Header-only scan of a block, listing its stores without bulk data.

    :param block_path: Path to the block directory.
    :returns: One :class:`StoreInfo` per store.
    """
    hdr = tdt.read_block(str(block_path), headers=1)
    stores = hdr["stores"]
    return [store_info_from_header(name, stores[name]) for name in stores.keys()]
