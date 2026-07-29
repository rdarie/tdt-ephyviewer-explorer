"""Per-block metadata summaries, assembled in three increasingly expensive tiers."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from tdt_ephyviewer_explorer.metadata.listing import Gizmo, read_stores_listing
from tdt_ephyviewer_explorer.metadata.notes import NOTES_FILENAME, Note, read_notes
from tdt_ephyviewer_explorer.metadata.stim import StimSummary, read_stim_summaries
from tdt_ephyviewer_explorer.tank import list_blocks, read_headers

UNLISTED_GIZMO = "(unlisted)"


@dataclass(frozen=True)
class BlockSummary:
    """Everything the metadata browser knows about one block.

    :param name: Block directory name.
    :param path: Block directory path.
    :param experiment: Experiment name, or ``None``.
    :param subject: Subject name, or ``None``.
    :param user: Synapse user, or ``None``.
    :param start: Recording start, or ``None``.
    :param stop: Recording stop, or ``None``.
    :param duration_s: Recording duration in seconds, or ``None``.
    :param gizmos: Gizmos and the stores they wrote.
    :param notes: Notes read from ``Notes.txt``.
    :param stim: One summary per stim parameter store.
    :param warnings: Human-readable problems found while assembling this summary.
    :param details_loaded: Whether the header and stim tiers have been attempted.
    """

    name: str
    path: Path
    experiment: str | None
    subject: str | None
    user: str | None
    start: datetime | None
    stop: datetime | None
    duration_s: float | None
    gizmos: tuple[Gizmo, ...]
    notes: tuple[Note, ...]
    stim: tuple[StimSummary, ...]
    warnings: tuple[str, ...]
    details_loaded: bool = False


def read_text_metadata(block_path: Path) -> BlockSummary:
    """Tier 0: build a summary from the block's text sidecars alone.

    Reads no TDT binaries, so it is fast enough to run over every block in a tank
    before showing the window.

    :param block_path: Path to the block directory.
    :returns: The summary, with ``stim`` empty and ``details_loaded`` false.
    """
    nf = read_notes(block_path / NOTES_FILENAME)
    gizmos = read_stores_listing(block_path)
    duration = (
        (nf.stop - nf.start).total_seconds()
        if nf.start is not None and nf.stop is not None
        else None
    )
    return BlockSummary(
        name=block_path.name,
        path=block_path,
        experiment=nf.experiment,
        subject=nf.subject,
        user=nf.user,
        start=nf.start,
        stop=nf.stop,
        duration_s=duration,
        gizmos=tuple(gizmos),
        notes=nf.notes,
        stim=(),
        warnings=nf.warnings,
        details_loaded=False,
    )


def augment_with_headers(summary: BlockSummary, headers: Any) -> BlockSummary:
    """Tier 1: fill gaps from the parsed ``.tsq`` index.

    Supplies a duration when ``Notes.txt`` gave none, and appends any store present
    in the index but missing from ``StoresListing.txt`` under a synthetic
    ``(unlisted)`` gizmo, so a stale listing hides nothing.

    :param summary: The tier-0 summary.
    :param headers: Parsed headers from :func:`~tank.read_headers`.
    :returns: An updated copy.
    """
    duration = summary.duration_s
    if duration is None:
        try:
            duration = float(headers["stop_time"][0]) - float(headers["start_time"][0])
        except (KeyError, IndexError, TypeError, ValueError):
            duration = None

    listed = {code for g in summary.gizmos for code in g.stores}
    unlisted = tuple(n for n in headers["stores"].keys() if n not in listed)
    gizmos = summary.gizmos
    if unlisted:
        gizmos = gizmos + (Gizmo(UNLISTED_GIZMO, None, unlisted),)

    return replace(summary, duration_s=duration, gizmos=gizmos)


def load_details(summary: BlockSummary, cfg: Any) -> BlockSummary:
    """Tiers 1 and 2: parse the index, then summarize the stim stores.

    Runs on a worker thread. Any failure is recorded as a warning and the summary is
    still marked loaded, so the UI leaves the "loading…" state either way.

    :param summary: The tier-0 summary.
    :param cfg: The composed Hydra config.
    :returns: An updated copy with ``details_loaded`` set.
    """
    warnings = list(summary.warnings)
    try:
        headers = read_headers(summary.path)
    except Exception as exc:  # noqa: BLE001 - a bad block must not kill the window
        warnings.append(f"could not read block index: {exc}")
        return replace(summary, warnings=tuple(warnings), details_loaded=True)

    try:
        out = augment_with_headers(summary, headers)
    except Exception as exc:  # noqa: BLE001 - a bad block must not kill the window
        warnings.append(f"could not augment metadata from block index: {exc}")
        return replace(summary, warnings=tuple(warnings), details_loaded=True)

    try:
        stim, stim_warnings = read_stim_summaries(out.path, cfg, headers=headers)
    except Exception as exc:  # noqa: BLE001
        stim, stim_warnings = [], [f"could not summarize stimulation: {exc}"]
    warnings.extend(stim_warnings)
    return replace(
        out, stim=tuple(stim), warnings=tuple(warnings), details_loaded=True
    )


def scan_tank(tank_dir: Path) -> list[BlockSummary]:
    """Tier 0 over every block in a tank, in name order.

    :param tank_dir: The tank directory.
    :returns: One summary per block. A block that cannot be read still appears,
        carrying the reason as a warning.
    """
    out: list[BlockSummary] = []
    for block_path in list_blocks(tank_dir):
        try:
            out.append(read_text_metadata(block_path))
        except Exception as exc:  # noqa: BLE001
            out.append(
                BlockSummary(
                    name=block_path.name, path=block_path, experiment=None,
                    subject=None, user=None, start=None, stop=None, duration_s=None,
                    gizmos=(), notes=(), stim=(),
                    warnings=(f"could not read block: {exc}",), details_loaded=True,
                )
            )
    return out


class BlockCache:
    """Per-tank cache of block summaries, keyed by block name.

    Switching to a different tank drops everything; reselecting the current tank
    keeps it, so an expensive tier-2 read is not repeated.
    """

    def __init__(self) -> None:
        self._tank: Path | None = None
        self._by_name: dict[str, BlockSummary] = {}

    def use_tank(self, tank_dir: Path) -> None:
        """Point the cache at a tank, clearing it if the tank changed.

        :param tank_dir: The tank now being browsed.
        """
        if self._tank != tank_dir:
            self._tank = tank_dir
            self._by_name = {}

    def get(self, name: str) -> BlockSummary | None:
        """Return the cached summary for ``name``, or ``None``."""
        return self._by_name.get(name)

    def put(self, summary: BlockSummary) -> None:
        """Store ``summary`` under its block name."""
        self._by_name[summary.name] = summary
