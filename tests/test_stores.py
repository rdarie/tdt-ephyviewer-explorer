"""Tests for store header parsing."""
import numpy as np
import pytest

from tdt_ephyviewer_explorer.stores import (
    StoreInfo,
    _store_from_block,
    store_info_from_header,
)


class _FakeTdtStore:
    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)

    def __getitem__(self, key):
        return getattr(self, key)  # AttributeError if absent, like tdt StructType


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
    assert resolved.sort == "time"  # default for unmatched stores


def test_resolve_role_carries_sort_from_rule() -> None:
    rules = [RoleRule("eS?p", "stim", "iz_param_names", ("eventlist",), None, "channel")]
    resolved = resolve_role(_info("eS1p", "scalars"), rules)
    assert resolved.sort == "channel"


def test_resolve_role_defaults_sort_to_time() -> None:
    rules = [RoleRule("eS?p", "stim", "iz_param_names", ("eventlist",))]
    resolved = resolve_role(_info("eS1p", "scalars"), rules)
    assert resolved.sort == "time"


def test_rules_from_config_reads_sort() -> None:
    rules = rules_from_config(load_config())
    stim = next(r for r in rules if r.role == "stim")
    assert stim.sort in ("time", "channel")


def test_rules_from_config_reads_packaged_rules() -> None:
    rules = rules_from_config(load_config())
    assert any(r.role == "stim" for r in rules)


def test_store_info_from_header_handles_missing_attribute() -> None:
    info = store_info_from_header(
        "eS1p", _FakeTdtStore(type_str="scalars", chan=np.array([1]))
    )
    assert info.fs is None
    assert info.tdt_type == "scalars"
    assert info.n_channels == 1


def test_store_from_block_finds_across_groups() -> None:
    blk = {"streams": {"Wav1": "W"}, "scalars": {"eS1p": "E"}}
    assert _store_from_block(blk, "eS1p") == "E"


def test_store_from_block_missing_raises() -> None:
    with pytest.raises(KeyError, match="not found"):
        _store_from_block({"streams": {}}, "Nope")


def test_load_store_reuses_headers(monkeypatch) -> None:
    from tdt_ephyviewer_explorer import stores as stores_mod
    from tdt_ephyviewer_explorer.stores import load_store

    calls: list[dict] = []

    def fake_read_block(path, **kwargs):
        calls.append(kwargs)
        return {"scalars": {"UDP1": "S"}}

    monkeypatch.setattr(stores_mod.tdt, "read_block", fake_read_block)
    heads = object()
    assert load_store(__import__("pathlib").Path("blk"), "UDP1", headers=heads) == "S"
    assert calls[0]["store"] == ["UDP1"]
    assert calls[0]["headers"] is heads  # reused, not re-parsed


def test_load_store_reads_own_index_without_headers(monkeypatch) -> None:
    from tdt_ephyviewer_explorer import stores as stores_mod
    from tdt_ephyviewer_explorer.stores import load_store

    calls: list[dict] = []

    def fake_read_block(path, **kwargs):
        calls.append(kwargs)
        return {"scalars": {"UDP1": "S"}}

    monkeypatch.setattr(stores_mod.tdt, "read_block", fake_read_block)
    assert load_store(__import__("pathlib").Path("blk"), "UDP1") == "S"
    assert "headers" not in calls[0]  # backward compatible: no headers kwarg


def test_impedance_role_allows_only_the_impedance_viewer() -> None:
    from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

    assert VALID_VIEWERS["impedance"] == ("impedance",)
