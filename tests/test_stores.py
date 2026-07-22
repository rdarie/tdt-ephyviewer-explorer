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


from tdt_ephyviewer_explorer.stores import (
    RoleRule,
    resolve_role,
    rules_from_config,
)
from tdt_ephyviewer_explorer.config_schema import load_config


def _info(name: str, tdt_type: str) -> StoreInfo:
    return StoreInfo(name, tdt_type, None, 1, None, 0.0, None)


def test_resolve_role_matches_pattern() -> None:
    rules = [RoleRule("eS?p", "stim", "iz_param_names", ("eventlist",), {"_target_": "x"})]
    resolved = resolve_role(_info("eS1p", "scalars"), rules)
    assert resolved.role == "stim"
    assert resolved.schema == "iz_param_names"
    assert resolved.viewers == ("eventlist",)


def test_resolve_role_falls_back_to_tdt_type() -> None:
    resolved = resolve_role(_info("Wav1", "streams"), [])
    assert resolved.role == "timeseries"
    assert resolved.viewers == ("trace", "timefreq", "spectrogram")


def test_rules_from_config_reads_packaged_rules() -> None:
    rules = rules_from_config(load_config())
    assert any(r.role == "snip" for r in rules)
