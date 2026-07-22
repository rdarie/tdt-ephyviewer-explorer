"""Tests for tank/block discovery."""
from pathlib import Path

from tdt_ephyviewer_explorer.tank import list_blocks


def test_scan_block_maps_header_stores(monkeypatch) -> None:
    import numpy as np
    from tdt_ephyviewer_explorer import tank as tank_mod

    fake_hdr = {"stores": {
        "Wav1": {"type_str": "streams", "fs": 1000.0, "chan": np.array([1, 2])},
        "eS1p": {"type_str": "scalars", "chan": np.array([1])},
    }}
    monkeypatch.setattr(tank_mod.tdt, "read_block", lambda *a, **k: fake_hdr)
    infos = tank_mod.scan_block(Path("ignored"))
    by_name = {i.name: i for i in infos}
    assert by_name["Wav1"].tdt_type == "streams"
    assert by_name["Wav1"].n_channels == 2
    assert by_name["eS1p"].fs is None


def test_list_blocks_finds_dirs_with_tsq(tmp_path: Path) -> None:
    good = tmp_path / "blockA-1"
    good.mkdir()
    (good / "blockA-1.tsq").write_bytes(b"")
    empty = tmp_path / "not_a_block"
    empty.mkdir()
    (tmp_path / "loose.tsq").write_bytes(b"")  # not in a subdir

    blocks = list_blocks(tmp_path)
    assert blocks == [good]
