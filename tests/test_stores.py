"""Tests for store header parsing."""
import numpy as np

from tdt_ephyviewer_explorer.stores import StoreInfo, store_info_from_header


def test_store_info_from_stream_header() -> None:
    fake = {
        "type_str": "streams",
        "fs": 24414.0625,
        "chan": np.array([8, 7, 6, 5, 4, 3, 2, 1]),
        "start_time": 0.0,
    }
    info = store_info_from_header("Wav1", fake)
    assert info == StoreInfo(
        name="Wav1",
        tdt_type="streams",
        fs=24414.0625,
        n_channels=8,
        n_samples=None,
        t_start=0.0,
        duration=None,
    )


def test_store_info_from_scalar_header() -> None:
    fake = {"type_str": "scalars", "chan": np.array([1])}
    info = store_info_from_header("eS1p", fake)
    assert info.tdt_type == "scalars"
    assert info.fs is None
    assert info.n_channels == 1
