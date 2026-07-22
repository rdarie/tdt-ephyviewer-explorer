"""Tests for tank/block discovery."""
from pathlib import Path

from tdt_ephyviewer_explorer.tank import list_blocks


def test_list_blocks_finds_dirs_with_tsq(tmp_path: Path) -> None:
    good = tmp_path / "blockA-1"
    good.mkdir()
    (good / "blockA-1.tsq").write_bytes(b"")
    empty = tmp_path / "not_a_block"
    empty.mkdir()
    (tmp_path / "loose.tsq").write_bytes(b"")  # not in a subdir

    blocks = list_blocks(tmp_path)
    assert blocks == [good]
