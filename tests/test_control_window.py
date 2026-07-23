"""Tests for the control-tree spec and window."""
import pytest

from tdt_ephyviewer_explorer.control_window import build_param_tree_spec
from tdt_ephyviewer_explorer.stores import ResolvedStore, StoreInfo


def _resolved(name: str, role: str, viewers: tuple[str, ...]) -> ResolvedStore:
    info = StoreInfo(name, "streams", 1000.0, 4, None, 0.0, None)
    return ResolvedStore(info, role, None, viewers, None)


def test_build_param_tree_spec_makes_group_per_store() -> None:
    spec = build_param_tree_spec(
        [_resolved("Wav1", "timeseries", ("trace", "timefreq"))], {"trace": {}, "timefreq": {}}
    )
    assert spec[0]["name"] == "Wav1"
    child_names = {c["name"] for c in spec[0]["children"]}
    assert "delay_ms" in child_names
    assert "probe_file" in child_names  # timeseries only
    viewers_group = next(c for c in spec[0]["children"] if c["name"] == "Viewers")
    assert {c["name"] for c in viewers_group["children"]} == {"trace", "timefreq"}


def test_build_param_tree_spec_omits_probe_for_events() -> None:
    spec = build_param_tree_spec(
        [_resolved("eS1p", "stim", ("eventlist",))], {"eventlist": {}}
    )
    child_names = {c["name"] for c in spec[0]["children"]}
    assert "probe_file" not in child_names


def test_spec_to_session_includes_only_enabled() -> None:
    from tdt_ephyviewer_explorer.control_window import spec_to_session

    state = {
        "Wav1": {
            "delay_ms": 5.0,
            "probe_file": "",
            "reorder": False,
            "Viewers": {"trace": {"_enabled": True, "display_labels": True},
                        "timefreq": {"_enabled": False}},
        }
    }
    session = spec_to_session("blk", state)
    assert list(session.attachments) == ["Wav1"]
    assert session.attachments["Wav1"][0]["viewer_type"] == "trace"
    assert session.attachments["Wav1"][0]["delay_ms"] == 5.0


@pytest.fixture(scope="module")
def qapp():
    import ephyviewer
    return ephyviewer.mkQApp()


def test_apply_session_round_trip_restores_viewers_delay_probe(qapp, monkeypatch) -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow, spec_to_session
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.session import Session
    from tdt_ephyviewer_explorer.stores import StoreInfo

    # A timeseries store -> tree gets delay_ms, probe_file, reorder, and a Viewers group.
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    cw.set_block(Path("blk"))

    session = Session(
        block="blk",
        attachments={
            "Wav1": [
                {
                    "viewer_type": "trace",
                    "delay_ms": 12.0,
                    "probe_path": "C:/probes/p.json",
                    "params": {},
                }
            ]
        },
    )
    cw._apply_session(session)
    round_tripped = spec_to_session("blk", cw._read_state())
    entry = round_tripped.attachments["Wav1"][0]
    assert entry["viewer_type"] == "trace"
    assert entry["delay_ms"] == 12.0
    assert entry["probe_path"] == "C:/probes/p.json"  # reorder+probe restored on load


def _make_tank(tmp_path):
    """Create a tank dir with two block subdirs, each holding a .tsq file."""
    for name in ("blockB-2", "blockA-1"):  # unsorted on purpose
        blk = tmp_path / name
        blk.mkdir()
        (blk / f"{name}.tsq").write_bytes(b"")
    return tmp_path


def test_set_tank_populates_block_selector(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config

    # No stores, so auto-selecting the first block builds an empty tree (no real tdt).
    monkeypatch.setattr(cw_mod, "scan_block", lambda p: [])
    cw = ControlWindow(load_config())
    cw.set_tank(_make_tank(tmp_path))

    block_param = cw._global_root.child("block")
    assert list(block_param.opts["limits"]) == ["blockA-1", "blockB-2"]  # sorted
    assert block_param.value() == "blockA-1"  # first auto-selected


def test_selecting_block_loads_its_stores(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    cw.set_tank(_make_tank(tmp_path))  # auto-selects blockA-1 -> loads its stores
    assert [c.name() for c in cw._root.children()] == ["Wav1"]
    assert cw._block_path == tmp_path / "blockA-1"
