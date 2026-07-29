"""Real-tdt smoke test. Set TDT_EXPLORE_TEST_BLOCK to a block dir to run."""
import os
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.stores import load_store
from tdt_ephyviewer_explorer.tank import scan_block

BLOCK = os.environ.get("TDT_EXPLORE_TEST_BLOCK")
pytestmark = pytest.mark.skipif(BLOCK is None, reason="TDT_EXPLORE_TEST_BLOCK not set")


def test_scan_and_load_roundtrip() -> None:
    block = Path(BLOCK)  # type: ignore[arg-type]
    infos = scan_block(block)
    assert infos, "expected at least one store"
    stream = next(i for i in infos if i.tdt_type == "streams")
    store = load_store(block, stream.name)
    assert store.data.ndim in (1, 2)
    assert store.data.size > 0


def test_stim_summary_matches_the_reference_block() -> None:
    """The reference block delivers 15561 pulses under 1881 distinct settings.

    Voice B is the return electrode (``countB == 0`` for every event) and 438 of the
    15999 events have ``chanA == 0``, so they deliver nothing: 15999 - 438 = 15561.
    """
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.metadata.stim import read_stim_summaries
    from tdt_ephyviewer_explorer.tank import read_headers

    block = Path(BLOCK)  # type: ignore[arg-type]
    if block.name != "Epi_02_Green-260727-154827":
        pytest.skip("reference figures apply to Epi_02_Green-260727-154827 only")

    headers = read_headers(block)
    summaries, warnings = read_stim_summaries(block, load_config(), headers=headers)
    assert warnings == []
    assert [(s.store, s.n_pulses, s.n_combinations) for s in summaries] == [
        ("eS1p", 15561, 1881)
    ]


def test_text_metadata_reads_the_real_block() -> None:
    """The real block's text sidecars parse into a populated summary."""
    from tdt_ephyviewer_explorer.metadata.summary import read_text_metadata

    block = Path(BLOCK)  # type: ignore[arg-type]
    summary = read_text_metadata(block)
    assert summary.name == block.name
    assert summary.gizmos, "expected StoresListing.txt to yield gizmos"
