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
