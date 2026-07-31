"""Tests for the metadata browser window."""
import gc
import time
from datetime import datetime
from pathlib import Path

import pytest

ephyviewer = pytest.importorskip("ephyviewer")

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.stim import StimSummary, VoiceSummary
from tdt_ephyviewer_explorer.metadata.window import MetadataWindow, run_in_pool

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"


@pytest.fixture(scope="module")
def qapp():
    return ephyviewer.mkQApp()


def _sync(fn, on_done, on_error):
    """Runner that executes inline, so tests never wait on a thread pool."""
    try:
        on_done(fn())
    except Exception as exc:  # noqa: BLE001
        on_error(exc)


def _tank(tmp_path: Path, names=("Epi_02_Green-260727-154827", "Epi_02_Green-260727-152924")) -> Path:
    tank = tmp_path / "tank"
    for name in names:
        blk = tank / name
        blk.mkdir(parents=True)
        (blk / f"{name}.tsq").write_bytes(b"")
        (blk / "Notes.txt").write_bytes((FIXTURES / "Notes.txt").read_bytes())
        (blk / "StoresListing.txt").write_bytes((FIXTURES / "StoresListing.txt").read_bytes())
    return tank


def _window(monkeypatch, stim=(StimSummary("eS1p", 15561, 1881),), warnings=()):
    from tdt_ephyviewer_explorer.metadata import window as mod
    from dataclasses import replace

    monkeypatch.setattr(
        mod, "load_details",
        lambda summary, cfg: replace(
            summary, stim=tuple(stim),
            warnings=summary.warnings + tuple(warnings), details_loaded=True,
        ),
    )
    return MetadataWindow(load_config(), runner=_sync)


def test_set_tank_lists_blocks_in_order(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    assert win.block_names() == [
        "Epi_02_Green-260727-152924",
        "Epi_02_Green-260727-154827",
    ]


def test_collapsed_row_shows_start_and_duration(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    row = win.row_text("Epi_02_Green-260727-154827")
    assert row[2] == "15:48:30"
    assert row[3] == "9m08s"


def test_rows_carry_a_zero_indexed_counter(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    assert [win.row_text(name)[0] for name in win.block_names()] == ["0", "1"]


def test_the_counter_survives_a_row_refresh(qapp, monkeypatch, tmp_path) -> None:
    # Rows are rebuilt in place when details land; the counter must not be lost.
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    assert win.row_text("Epi_02_Green-260727-154827")[0] == "1"


def test_the_picker_does_not_eat_the_windows_height(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    win.resize(900, 900)
    win.layout().activate()

    assert win.picker.height() <= win.picker.sizeHint().height()


def test_expanding_shows_gizmos_and_stim(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert any("Electrical Stim Driver" in ln for ln in lines)
    assert any("15561 pulses · 1881 combinations" in ln for ln in lines)


def test_details_are_loaded_once_per_block(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import window as mod
    from dataclasses import replace

    calls: list[str] = []

    def counting(summary, cfg):
        calls.append(summary.name)
        return replace(summary, details_loaded=True)

    monkeypatch.setattr(mod, "load_details", counting)
    win = MetadataWindow(load_config(), runner=_sync)
    win.set_tank(_tank(tmp_path))

    win.expand_block("Epi_02_Green-260727-154827")
    win.expand_block("Epi_02_Green-260727-154827")
    assert calls == ["Epi_02_Green-260727-154827"]  # cached, not re-read


def test_details_are_not_reloaded_while_a_load_is_in_flight(qapp, monkeypatch, tmp_path) -> None:
    # The synchronous runner above finishes each load before the next check, so it
    # cannot see this: with the real pool the load is still running, details_loaded
    # is still False, and a second schedule re-reads the whole eS1p store.
    from tdt_ephyviewer_explorer.metadata import window as mod
    from dataclasses import replace

    scheduled: list[tuple] = []
    monkeypatch.setattr(mod, "load_details", lambda summary, cfg: replace(summary, details_loaded=True))
    win = MetadataWindow(
        load_config(), runner=lambda fn, on_done, on_error: scheduled.append((fn, on_done))
    )
    win.set_tank(_tank(tmp_path))

    win.expand_block("Epi_02_Green-260727-154827")
    win.expand_block("Epi_02_Green-260727-154827")
    assert len(scheduled) == 1

    fn, on_done = scheduled[0]
    on_done(fn())  # the load lands; a later expand must not re-read either
    win.expand_block("Epi_02_Green-260727-154827")
    assert len(scheduled) == 1


def test_a_failed_load_does_not_wedge_the_block_forever(qapp, monkeypatch, tmp_path) -> None:
    # The in-flight guard must release on failure too. It does not retry in place --
    # a failed load is recorded on the row -- but revisiting the tank re-scans, and a
    # guard still holding the name would leave the block permanently unloadable.
    from tdt_ephyviewer_explorer.metadata import window as mod

    name = "Epi_02_Green-260727-154827"
    scheduled: list[tuple] = []
    monkeypatch.setattr(mod, "load_details", lambda summary, cfg: None)
    win = MetadataWindow(
        load_config(), runner=lambda fn, on_done, on_error: scheduled.append((fn, on_error))
    )
    tank = _tank(tmp_path)
    win.set_tank(tank)

    win.expand_block(name)
    scheduled[0][1](OSError("corrupt tsq"))

    win.set_tank(_tank(tmp_path / "second", names=("Solo-260101-000000",)))
    win.set_tank(tank)  # back again: the cache is cold, so this must load afresh
    win.expand_block(name)
    assert len(scheduled) == 2


def test_a_late_result_for_a_previous_tank_is_dropped(qapp, monkeypatch, tmp_path) -> None:
    # Switching tanks with a load still running: the result names a block that is no
    # longer listed, so it must be discarded rather than indexed or cached.
    from tdt_ephyviewer_explorer.metadata import window as mod
    from dataclasses import replace

    scheduled: list[tuple] = []
    monkeypatch.setattr(mod, "load_details", lambda summary, cfg: replace(summary, details_loaded=True))
    win = MetadataWindow(
        load_config(), runner=lambda fn, on_done, on_error: scheduled.append((fn, on_done, on_error))
    )
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    win.set_tank(_tank(tmp_path / "second", names=("Solo-260101-000000",)))

    fn, on_done, on_error = scheduled[0]
    on_done(fn())
    on_error(OSError("corrupt tsq"))
    assert win.block_names() == ["Solo-260101-000000"]


def test_a_block_with_no_stim_shows_no_stim_line(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch, stim=())
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert not any("pulses" in ln for ln in lines)


def test_warnings_appear_on_the_row(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch, warnings=("eS1p: 23 rows but schema names 24",))
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert any("23 rows" in ln for ln in lines)
    assert "⚠" in win.row_text("Epi_02_Green-260727-154827")[1]


def test_a_worker_failure_is_reported_not_raised(qapp, monkeypatch, tmp_path) -> None:
    from tdt_ephyviewer_explorer.metadata import window as mod

    def boom(summary, cfg):
        raise OSError("corrupt tsq")

    monkeypatch.setattr(mod, "load_details", boom)
    win = MetadataWindow(load_config(), runner=_sync)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    assert any("corrupt tsq" in ln for ln in win.detail_lines("Epi_02_Green-260727-154827"))


def test_notes_expand_opens_the_read_only_panel(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_notes("Epi_02_Green-260727-154827")
    assert "Notes.txt" in win.panel.header_text
    assert win.panel.row_count == 2


def test_analysis_notes_expand_opens_the_editable_panel(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.set_tank(tank)
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_analysis_notes("Epi_02_Green-260727-154827")
    assert "Analysis notes" in win.panel.header_text
    assert win.panel.row_count == 1  # just the blank entry row


def test_saving_an_analysis_note_writes_into_the_block_dir(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.set_tank(tank)
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_analysis_notes("Epi_02_Green-260727-154827")
    win.panel.set_cell_text(0, 2, "EMG saturated")

    written = tank / "Epi_02_Green-260727-154827" / "analysis_notes.txt"
    assert written.is_file()
    assert "EMG saturated" in written.read_bytes().decode("utf-8")


def test_saving_a_note_never_touches_notes_txt(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    original = (tank / "Epi_02_Green-260727-154827" / "Notes.txt").read_bytes()
    win.set_tank(tank)
    win.expand_block("Epi_02_Green-260727-154827")
    win.open_analysis_notes("Epi_02_Green-260727-154827")
    win.panel.set_cell_text(0, 2, "EMG saturated")

    assert (tank / "Epi_02_Green-260727-154827" / "Notes.txt").read_bytes() == original


def test_open_in_explorer_emits_tank_and_block(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.set_tank(tank)
    seen: list[tuple] = []
    win.open_in_explorer_requested.connect(lambda t, b: seen.append((t, b)))

    win.request_open_in_explorer("Epi_02_Green-260727-154827")
    assert seen == [(tank, "Epi_02_Green-260727-154827")]


def test_switching_tanks_replaces_the_block_list(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    win.set_tank(_tank(tmp_path))
    other = _tank(tmp_path / "second", names=("Solo-260101-000000",))
    win.set_tank(other)
    assert win.block_names() == ["Solo-260101-000000"]


def test_picker_signal_drives_set_tank(qapp, monkeypatch, tmp_path) -> None:
    win = _window(monkeypatch)
    tank = _tank(tmp_path)
    win.picker.set_tank(tank)
    assert win.block_names()


def _drain(qapp, box: list, seconds: float = 5.0) -> None:
    """Pump the event loop until ``box`` fills or the deadline passes."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not box:
        qapp.processEvents()
        time.sleep(0.01)


def test_run_in_pool_delivers_the_result_to_the_gui_thread(qapp) -> None:
    # The window tests all inject a synchronous runner, so this is the only cover
    # for the real one. A worker collected before it emits delivers nothing at all,
    # which in the app looks like a block stuck on "loading…" forever.
    got: list[object] = []
    run_in_pool(lambda: 42, got.append, got.append)
    gc.collect()  # the runner must not depend on the worker surviving by luck
    _drain(qapp, got)
    assert got == [42]


def test_run_in_pool_delivers_a_failure(qapp) -> None:
    failures: list[BaseException] = []
    run_in_pool(_boom, lambda result: failures.append(AssertionError("unexpected")), failures.append)
    gc.collect()
    _drain(qapp, failures)
    assert isinstance(failures[0], OSError)


def _boom() -> None:
    """Work that always fails, for the failure path."""
    raise OSError("corrupt tsq")


def test_voice_rows_appear_under_their_store(qapp, monkeypatch, tmp_path) -> None:
    stim = (
        StimSummary(
            "eS1p", 15561, 1881,
            (
                VoiceSummary("A", (1, 2, 3, 4, 5, 6, 7, 8), 100.0, 800.0, "−", 10.0, 50.0),
                VoiceSummary("B", (12,), 200.0, 200.0, "−", 20.0, 20.0),
            ),
        ),
    )
    win = _window(monkeypatch, stim=stim)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert "voice A ch 1–8 · −100–800 µA · 10–50 Hz" in lines
    assert "voice B ch 12 · −200 µA · 20 Hz" in lines


def test_a_store_with_no_active_voice_shows_only_its_headline(
    qapp, monkeypatch, tmp_path
) -> None:
    win = _window(monkeypatch, stim=(StimSummary("eS1p", 0, 0),))
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert "eS1p 0 pulses · 0 combinations" in lines
    assert not any(ln.startswith("voice ") for ln in lines)
