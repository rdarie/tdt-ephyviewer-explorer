"""Tank/block discovery and header scanning."""
from __future__ import annotations

from pathlib import Path
from typing import Any

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


def read_headers(block_path: Path) -> Any:
    """Parse a block's ``.tsq`` event index once, returning the raw tdt headers.

    ``tdt.read_block`` re-parses the whole index on every call; the returned struct
    can be threaded into :func:`scan_block` and :func:`~stores.load_store` (via their
    ``headers`` argument) so the index is parsed a single time per block.

    :param block_path: Path to the block directory.
    :returns: The raw tdt headers struct (accepted as ``read_block(headers=...)``).
    """
    return tdt.read_block(str(block_path), headers=1)


def scan_block(block_path: Path, headers: Any | None = None) -> list[StoreInfo]:
    """Header-only scan of a block, listing its stores without bulk data.

    :param block_path: Path to the block directory.
    :param headers: Pre-parsed headers from :func:`read_headers` to reuse; when
        ``None`` the index is parsed here.
    :returns: One :class:`StoreInfo` per store.
    """
    hdr = headers if headers is not None else read_headers(block_path)
    stores = hdr["stores"]
    return [store_info_from_header(name, stores[name]) for name in stores.keys()]
