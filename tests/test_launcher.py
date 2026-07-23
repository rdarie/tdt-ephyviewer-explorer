"""Qt smoke tests for viewer building and the block launcher."""
import numpy as np
import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.builders import Attachment, build_viewer, build_analog_source


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def test_build_viewer_returns_trace_viewer(qapp) -> None:
    class S:
        data = np.zeros((2, 50))
        fs = 1000.0
        start_time = 0.0

    src = build_analog_source(S(), Attachment("trace"), probe=None)
    view = build_viewer("trace", src, name="Wav1:trace", params={"display_labels": True})
    assert view.name == "Wav1:trace"
    assert view.params["display_labels"] is True


# --- plan_views: Qt-free orchestration (no MainViewer, so safe headless) ---
from pathlib import Path

from tdt_ephyviewer_explorer import launcher as launcher_mod
from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.launcher import plan_views
from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import StoreInfo


class _FakeScalar:
    data = np.zeros((2, 3))
    ts = np.array([0.0, 1.0, 2.0])


def _patch_block(monkeypatch, loads):
    """Patch read_headers/scan_block/load_store so plan_views runs without real tdt."""
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(
        launcher_mod,
        "scan_block",
        lambda p, headers=None: [StoreInfo("UDP1", "scalars", None, 1, None, 0.0, None)],
    )

    def fake_load(block_path, name, headers=None):
        loads.append(name)
        return _FakeScalar()

    monkeypatch.setattr(launcher_mod, "load_store", fake_load)


def test_plan_views_loads_store_once_for_multiple_viewers(monkeypatch) -> None:
    # "UDP1" matches no role rule -> falls back to tdt type scalars -> event role.
    loads: list[str] = []
    _patch_block(monkeypatch, loads)
    session = Session(
        block="blk",
        attachments={
            "UDP1": [
                {"viewer_type": "eventlist", "delay_ms": 0.0, "probe_path": None, "params": {}},
                {"viewer_type": "spiketrain", "delay_ms": 0.0, "probe_path": None, "params": {}},
            ]
        },
    )
    plans = plan_views(Path("tank/blk"), session, load_config())
    assert loads == ["UDP1"]  # loaded once despite two viewers on the same store
    assert [p.name for p in plans] == ["UDP1:eventlist", "UDP1:spiketrain"]
    from ephyviewer import InMemoryEventSource, InMemorySpikeSource

    assert isinstance(plans[0].source, InMemoryEventSource)
    assert isinstance(plans[1].source, InMemorySpikeSource)


def test_plan_views_parses_block_index_once(monkeypatch) -> None:
    # Regression: two viewers on one store must parse the .tsq index a single time
    # (one header read, reused for the store load) rather than re-parsing per read.
    from tdt_ephyviewer_explorer import stores as stores_mod
    from tdt_ephyviewer_explorer import tank as tank_mod

    heads = {"stores": {"UDP1": {"type_str": "scalars", "chan": np.array([1])}}}
    block = {"scalars": {"UDP1": _FakeScalar()}}
    calls: list[dict] = []

    def fake_read_block(path, **kwargs):
        calls.append(kwargs)
        return heads if kwargs.get("headers") == 1 else block

    monkeypatch.setattr(tank_mod.tdt, "read_block", fake_read_block)
    monkeypatch.setattr(stores_mod.tdt, "read_block", fake_read_block)
    session = Session(
        block="blk",
        attachments={
            "UDP1": [
                {"viewer_type": "eventlist", "delay_ms": 0.0, "probe_path": None, "params": {}},
                {"viewer_type": "spiketrain", "delay_ms": 0.0, "probe_path": None, "params": {}},
            ]
        },
    )
    plan_views(Path("tank/blk"), session, load_config())
    index_parses = [c for c in calls if c.get("headers") == 1]
    assert len(index_parses) == 1  # index parsed exactly once
    store_reads = [c for c in calls if "store" in c]
    assert store_reads and all(c.get("headers") is heads for c in store_reads)  # loads reuse it


def test_plan_views_uses_supplied_headers(monkeypatch) -> None:
    # When the caller (control window) already parsed the index, plan_views must not
    # parse it again.
    from tdt_ephyviewer_explorer import stores as stores_mod
    from tdt_ephyviewer_explorer import tank as tank_mod

    heads = {"stores": {"UDP1": {"type_str": "scalars", "chan": np.array([1])}}}
    block = {"scalars": {"UDP1": _FakeScalar()}}
    calls: list[dict] = []

    def fake_read_block(path, **kwargs):
        calls.append(kwargs)
        return heads if kwargs.get("headers") == 1 else block

    monkeypatch.setattr(tank_mod.tdt, "read_block", fake_read_block)
    monkeypatch.setattr(stores_mod.tdt, "read_block", fake_read_block)
    session = Session(
        block="blk",
        attachments={
            "UDP1": [{"viewer_type": "eventlist", "delay_ms": 0.0, "probe_path": None, "params": {}}]
        },
    )
    plan_views(Path("tank/blk"), session, load_config(), headers=heads)
    assert [c for c in calls if c.get("headers") == 1] == []  # no fresh header parse


def test_plan_views_missing_store_raises(monkeypatch) -> None:
    _patch_block(monkeypatch, [])
    session = Session(
        block="blk",
        attachments={"Nope": [{"viewer_type": "eventlist", "delay_ms": 0.0, "probe_path": None, "params": {}}]},
    )
    with pytest.raises(KeyError, match="not present"):
        plan_views(Path("tank/blk"), session, load_config())
