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


def test_apply_trace_color_scheme_on_real_viewer(qapp) -> None:
    # Contract check: ephyviewer's real TraceViewer controller exposes combo_cmap
    # + on_automatic_color, and applying a scheme recolors channels distinctly.
    from tdt_ephyviewer_explorer.launcher import _apply_trace_color_scheme

    class S:
        data = np.zeros((3, 50))
        fs = 1000.0
        start_time = 0.0

    src = build_analog_source(S(), Attachment("trace"), probe=None)
    view = build_viewer("trace", src, name="Wav1:trace", params={})
    _apply_trace_color_scheme(view, "jet")
    from ephyviewer.myqt import QT

    colors = {QT.QColor(view.by_channel_params[f"ch{c}", "color"]).name() for c in range(3)}
    assert len(colors) == 3  # progressive colormap gave each channel its own color


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


# --- startup behavior: auto-scale + default trace color scheme (Qt-free via fakes) ---
from tdt_ephyviewer_explorer.launcher import _apply_trace_color_scheme, apply_startup

_CMAPS = ["Accent", "Dark2", "jet", "prism", "hsv"]


class _FakeCombo:
    def __init__(self, items):
        self._items = list(items)
        self._current = 0

    def count(self):
        return len(self._items)

    def itemText(self, i):
        return self._items[i]

    def setCurrentIndex(self, i):
        self._current = i

    def currentText(self):
        return self._items[self._current]


class _FakeController:
    def __init__(self, cmaps):
        self.combo_cmap = _FakeCombo(cmaps)
        self.applied = None

    def on_automatic_color(self):
        self.applied = self.combo_cmap.currentText()


class _FakeView:
    def __init__(self, controller=None):
        self.params_controller = controller


class _FakeWin:
    def __init__(self):
        self.auto_scaled = 0

    def auto_scale(self):
        self.auto_scaled += 1


def test_apply_trace_color_scheme_selects_and_applies() -> None:
    ctrl = _FakeController(_CMAPS)
    _apply_trace_color_scheme(_FakeView(ctrl), "Dark2")
    assert ctrl.combo_cmap.currentText() == "Dark2"
    assert ctrl.applied == "Dark2"  # controller applied the selected scheme


def test_apply_trace_color_scheme_skips_non_color_viewer() -> None:
    # Non-trace viewers have no controller or no combo_cmap: skip, don't raise.
    _apply_trace_color_scheme(_FakeView(None), "Accent")

    class _NoCombo:
        pass

    _apply_trace_color_scheme(_FakeView(_NoCombo()), "Accent")


def test_apply_trace_color_scheme_unknown_scheme_raises() -> None:
    view = _FakeView(_FakeController(_CMAPS))
    with pytest.raises(ValueError, match="nope"):
        _apply_trace_color_scheme(view, "nope")  # no silent failure


def test_apply_startup_applies_color_and_auto_scale() -> None:
    win = _FakeWin()
    trace, other = _FakeView(_FakeController(_CMAPS)), _FakeView(None)
    apply_startup(win, [trace, other], {"auto_scale": True, "trace_color_scheme": "jet"})
    assert trace.params_controller.applied == "jet"
    assert win.auto_scaled == 1


def test_apply_startup_disabled_does_nothing() -> None:
    win = _FakeWin()
    trace = _FakeView(_FakeController(_CMAPS))
    apply_startup(win, [trace], {"auto_scale": False, "trace_color_scheme": None})
    assert trace.params_controller.applied is None
    assert win.auto_scaled == 0


def test_plan_views_includes_processed_sources(tmp_path, monkeypatch) -> None:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import json

    from tdt_ephyviewer_explorer.processed import CONTRACT_KEY
    from tdt_ephyviewer_explorer.session import ProcessedSource

    # A tagged timeseries parquet under the tank.
    block = "blk"
    pdir = tmp_path / "torpedo" / "preprocessed" / block
    pdir.mkdir(parents=True)
    ppath = pdir / "raw_data_mep.parquet"
    table = pa.Table.from_pandas(pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]}))
    md = dict(table.schema.metadata or {})
    md[CONTRACT_KEY] = json.dumps({"contract_version": 1, "kind": "timeseries",
                                   "sampling_rate": 1000.0, "t_start": 0.0,
                                   "channel_names": ["a", "b"]}).encode()
    pq.write_table(table.replace_schema_metadata(md), ppath)

    # No TDT stores referenced; scan_block/read_headers are unused for a processed-only session.
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block=block,
        processed=[ProcessedSource(
            path="torpedo/preprocessed/blk/raw_data_mep.parquet",
            kind="timeseries", name="raw_data_mep",
            attachments=[{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}],
        )],
    )
    plans = plan_views(tmp_path / block, session, load_config())
    assert len(plans) == 1
    assert plans[0].name == "raw_data_mep:trace"
    assert plans[0].source.signals.shape == (2, 2)


def test_plan_views_builds_blob_less_timeseries_with_sampling_rate_override(
    tmp_path, monkeypatch
) -> None:
    """An UNTAGGED (blob-less) parquet must build via ProcessedSource.sampling_rate.

    Regression test: spec_to_session previously dropped the sampling rate a user
    typed into the "Add processed..." prompt, so _processed_info fell back to a
    ProcessedInfo with sampling_rate=None and build_processed_source raised.
    """
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from tdt_ephyviewer_explorer.session import ProcessedSource

    block = "blk"
    pdir = tmp_path / "torpedo" / "preprocessed" / block
    pdir.mkdir(parents=True)
    ppath = pdir / "manual_ts.parquet"
    table = pa.Table.from_pandas(pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]}))
    pq.write_table(table, ppath)  # no tdt_explore contract blob: blob-less/untagged

    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block=block,
        processed=[ProcessedSource(
            path="torpedo/preprocessed/blk/manual_ts.parquet",
            kind="timeseries", name="manual_ts", sampling_rate=30000.0,
            attachments=[{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}],
        )],
    )
    plans = plan_views(tmp_path / block, session, load_config())
    assert len(plans) == 1
    assert plans[0].name == "manual_ts:trace"
    assert plans[0].source.signals.shape == (2, 2)


def test_plan_views_includes_impedance_sources(tmp_path, monkeypatch) -> None:
    import shutil

    from tdt_ephyviewer_explorer.session import ImpedanceSource

    block = "blk"
    block_dir = tmp_path / block
    block_dir.mkdir()
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copy(fixtures / "impedance_2freq.csv", block_dir / "spinal.csv")

    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block=block,
        impedance=[ImpedanceSource(
            path="blk/spinal.csv", name="spinal",
            attachments=[{"viewer_type": "impedance", "delay_ms": 0.0,
                          "probe_path": None, "params": {"vmax": 300.0}}],
        )],
    )
    plans = plan_views(block_dir, session, load_config())
    assert len(plans) == 1
    assert plans[0].name == "spinal:impedance"
    assert plans[0].viewer_type == "impedance"
    assert plans[0].params["vmax"] == 300.0        # attachment override wins
    assert plans[0].params["cmap"] == "viridis"    # config default still merged in
    assert plans[0].source.frequencies == (1000.0, 5000.0)


def test_plan_views_missing_impedance_file_raises(tmp_path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.session import ImpedanceSource

    block_dir = tmp_path / "blk"
    block_dir.mkdir()
    monkeypatch.setattr(launcher_mod, "read_headers", lambda p: None)
    monkeypatch.setattr(launcher_mod, "scan_block", lambda p, headers=None: [])

    session = Session(
        block="blk",
        impedance=[ImpedanceSource(
            path="blk/gone.csv", name="gone",
            attachments=[{"viewer_type": "impedance", "delay_ms": 0.0,
                          "probe_path": None, "params": {}}],
        )],
    )
    with pytest.raises(FileNotFoundError, match="gone.csv"):
        plan_views(block_dir, session, load_config())
