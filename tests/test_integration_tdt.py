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
    assert store.data.ndim == 2
