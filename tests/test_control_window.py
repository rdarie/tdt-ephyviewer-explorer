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
    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
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


def test_set_block_exposes_parsed_headers(qapp, monkeypatch) -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    heads = object()
    monkeypatch.setattr(cw_mod, "read_headers", lambda p: heads)
    scan_args: list[object] = []
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: (scan_args.append(headers), [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)])[1],
    )
    cw = ControlWindow(load_config())
    cw.set_block(Path("blk"))
    assert cw.headers is heads  # parsed once, kept for reuse at launch
    assert scan_args == [heads]  # scan reused the parsed headers (no second parse)


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
    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(cw_mod, "scan_block", lambda p, headers=None: [])
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

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    cw.set_tank(_make_tank(tmp_path))  # auto-selects blockA-1 -> loads its stores
    assert [c.name() for c in cw._root.children()] == ["Wav1"]
    assert cw._block_path == tmp_path / "blockA-1"


def test_set_tank_switch_reloads_same_named_block(qapp, monkeypatch, tmp_path) -> None:
    # Regression: switching to a tank whose chosen block shares a name with the
    # previous selection must still reload (pyqtgraph suppresses unchanged-value signals).
    from pathlib import Path

    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config

    calls: list[Path] = []
    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(cw_mod, "scan_block", lambda p, headers=None: (calls.append(Path(p)), [])[1])

    def _tank_with_block1(root: Path) -> Path:
        root.mkdir()
        blk = root / "Block-1"
        blk.mkdir()
        (blk / "Block-1.tsq").write_bytes(b"")
        return root

    tank_a = _tank_with_block1(tmp_path / "A")
    tank_b = _tank_with_block1(tmp_path / "B")
    cw = ControlWindow(load_config())
    cw.set_tank(tank_a)
    assert cw._block_path == tank_a / "Block-1"
    cw.set_tank(tank_b)  # same first-block name
    assert cw._block_path == tank_b / "Block-1"
    assert calls[-1] == tank_b / "Block-1"


def test_set_tank_with_explicit_block_loads_once(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config

    calls: list[object] = []
    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(cw_mod, "scan_block", lambda p, headers=None: (calls.append(p), [])[1])
    cw = ControlWindow(load_config())
    cw.set_tank(_make_tank(tmp_path), block="blockB-2")
    assert cw._block_path is not None and cw._block_path.name == "blockB-2"
    assert len(calls) == 1  # loaded the requested block once, no first-then-switch double scan


def test_build_processed_param_spec_group() -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer.control_window import build_processed_param_spec
    from tdt_ephyviewer_explorer.processed import ProcessedInfo
    from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

    info = ProcessedInfo(
        path=Path("torpedo/preprocessed/blk/raw_data_mep.parquet"),
        kind="timeseries", role="timeseries", name="raw_data_mep",
        sampling_rate=24414.0625, t_start=0.0, channel_names=["a", "b"],
        time_column=None, time_units="seconds", label_column=None, schema=None,
        units="uV", viewers=VALID_VIEWERS["timeseries"],
    )
    spec = build_processed_param_spec([info], {"trace": {}})
    grp = spec[0]
    assert grp["name"] == "raw_data_mep"
    names = {c["name"]: c for c in grp["children"]}
    assert names["source_path"]["readonly"] is True
    assert names["source_kind"]["value"] == "timeseries"
    assert "probe_file" in names  # timeseries -> probe controls
    viewers = next(c for c in grp["children"] if c["name"] == "Viewers")
    assert "trace" in {c["name"] for c in viewers["children"]}


def test_spec_to_session_emits_processed() -> None:
    from tdt_ephyviewer_explorer.control_window import spec_to_session

    state = {
        "raw_data_mep": {
            "source_path": "torpedo/preprocessed/blk/raw_data_mep.parquet",
            "source_kind": "timeseries",
            "source_name": "raw_data_mep",
            "delay_ms": 0.0, "probe_file": "", "reorder": False,
            "Viewers": {"trace": {"_enabled": True}},
        },
        "Wav1": {  # a normal TDT store still becomes an attachment
            "delay_ms": 5.0, "Viewers": {"trace": {"_enabled": True}},
        },
    }
    session = spec_to_session("blk", state)
    assert list(session.attachments) == ["Wav1"]
    assert len(session.processed) == 1
    ps = session.processed[0]
    assert ps.name == "raw_data_mep" and ps.kind == "timeseries"
    assert ps.path == "torpedo/preprocessed/blk/raw_data_mep.parquet"
    assert ps.attachments[0]["viewer_type"] == "trace"


def test_spec_to_session_wires_blob_less_sampling_rate() -> None:
    """A blob-less timeseries group's ``fs`` must survive into ProcessedSource.

    Regression test: ``spec_to_session`` used to drop the ``fs`` the user typed
    into the "Add processed..." prompt entirely, so an untagged manually-added
    file could never launch (see launcher._processed_info / processed.py).
    """
    from tdt_ephyviewer_explorer.control_window import spec_to_session

    state = {
        "manual_ts": {
            "source_path": "torpedo/preprocessed/blk/manual_ts.parquet",
            "source_kind": "timeseries",
            "source_name": "manual_ts",
            "fs": 30000.0, "delay_ms": 0.0, "probe_file": "", "reorder": False,
            "Viewers": {"trace": {"_enabled": True}},
        },
        "manual_evt": {  # event-style group: fs absent/0.0 must NOT become 0.0
            "source_path": "torpedo/preprocessed/blk/manual_evt.parquet",
            "source_kind": "event",
            "source_name": "manual_evt",
            "fs": 0.0, "delay_ms": 0.0,
            "Viewers": {"event": {"_enabled": True}},
        },
    }
    session = spec_to_session("blk", state)
    by_name = {ps.name: ps for ps in session.processed}
    assert by_name["manual_ts"].sampling_rate == 30000.0
    assert by_name["manual_evt"].sampling_rate is None


def test_set_block_auto_scans_processed(qapp, monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.processed import ProcessedInfo
    from tdt_ephyviewer_explorer.stores import StoreInfo, VALID_VIEWERS

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(cw_mod, "scan_block", lambda p, headers=None:
                        [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)])
    fake = ProcessedInfo(
        path=Path("torpedo/preprocessed/blk/raw_data_mep.parquet"),
        kind="timeseries", role="timeseries", name="raw_data_mep",
        sampling_rate=1000.0, t_start=0.0, channel_names=["a"], time_column=None,
        time_units="seconds", label_column=None, schema=None, units="uV",
        viewers=VALID_VIEWERS["timeseries"],
    )
    monkeypatch.setattr(cw_mod, "scan_preprocessed", lambda tank, block, cfg: [fake])

    cw = ControlWindow(load_config())
    cw._tank_dir = tmp_path
    cw.set_block(tmp_path / "blk")
    group_names = {g.name() for g in cw._root.children()}
    assert "Wav1" in group_names
    assert "raw_data_mep" in group_names


def test_set_tank_empty_clears_previous_block(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    cw.set_tank(_make_tank(tmp_path))
    assert [c.name() for c in cw._root.children()] == ["Wav1"]
    empty = tmp_path / "empty_tank"
    empty.mkdir()
    cw.set_tank(empty)  # no blocks -> clear stale state
    assert cw._block_path is None
    assert list(cw._root.children()) == []


def test_control_window_exposes_tank_dir(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    assert cw.tank_dir is None  # nothing picked yet

    tank = _make_tank(tmp_path)
    cw.set_tank(tank)
    assert cw.tank_dir == tank


def test_picker_signal_loads_the_tank(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    tank = _make_tank(tmp_path)

    cw.picker.set_tank(tank)  # as if the user browsed to it
    assert cw.tank_dir == tank
    assert [c.name() for c in cw._root.children()] == ["Wav1"]


def test_launch_button_disabled_until_a_block_loads(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    assert cw.launch_button.isEnabled() is False  # no tank yet

    cw.set_tank(_make_tank(tmp_path))
    assert cw.launch_button.isEnabled() is True

    empty = tmp_path / "empty_tank"
    empty.mkdir()
    cw.set_tank(empty)
    assert cw.launch_button.isEnabled() is False  # cleared again


def test_set_tank_updates_the_picker_without_reentering(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer import control_window as cw_mod
    from tdt_ephyviewer_explorer.control_window import ControlWindow
    from tdt_ephyviewer_explorer.config_schema import load_config
    from tdt_ephyviewer_explorer.stores import StoreInfo

    monkeypatch.setattr(cw_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        cw_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("Wav1", "streams", 1000.0, 4, None, 0.0, None)],
    )
    cw = ControlWindow(load_config())
    calls: list[object] = []
    cw.picker.tank_changed.connect(calls.append)

    tank = _make_tank(tmp_path)
    cw.set_tank(tank)  # programmatic: picker must display it, not re-emit
    assert cw.picker.tank_dir == tank
    assert calls == []
