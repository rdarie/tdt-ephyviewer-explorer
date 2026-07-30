"""Tests for the eStim pulse/parameter-combination summary."""
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.stim import (
    StimSchemaMismatch,
    StimSummary,
    format_channels,
    read_stim_summaries,
    stim_config_from,
    summarize_stim,
)

VOICES = ("A", "B", "C", "D")
COLS = tuple(
    f"{field}{v}" for v in VOICES
    for field in ("per", "count", "amp", "dur", "delay", "chan")
)


def _blank(n_events: int) -> np.ndarray:
    """A (24, n_events) all-zero parameter block."""
    return np.zeros((len(COLS), n_events), dtype=float)


def _row(name: str) -> int:
    return COLS.index(name)


def _summarize(data: np.ndarray) -> StimSummary:
    return summarize_stim("eS1p", data, COLS, VOICES, "chan", "count")


def test_single_active_voice_one_pulse_each() -> None:
    data = _blank(10)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 10, 1)


def test_sweeping_a_channel_counts_distinct_combinations() -> None:
    data = _blank(6)
    data[_row("chanA")] = [1, 1, 2, 2, 3, 3]
    data[_row("countA")] = 1.0
    assert _summarize(data) == StimSummary("eS1p", 6, 3)


def test_two_active_voices_combine_into_pairs() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 1, 2, 2]
    data[_row("chanB")] = [5, 6, 5, 6]
    data[_row("countA")] = 1.0
    data[_row("countB")] = 1.0
    assert _summarize(data) == StimSummary("eS1p", 4, 4)


def test_count_greater_than_one_yields_more_pulses_than_events() -> None:
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    assert _summarize(data).n_pulses == 15


def test_concurrent_voices_do_not_double_count_pulses() -> None:
    # A and B fire together; a 3-pulse train is 3 pulses in time, not 6.
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    data[_row("chanB")] = 2.0
    data[_row("countB")] = 3.0
    assert _summarize(data).n_pulses == 15


def test_pulses_take_the_max_across_voices() -> None:
    data = _blank(1)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 2.0
    data[_row("chanB")] = 1.0
    data[_row("countB")] = 5.0
    assert _summarize(data).n_pulses == 5


def test_idle_voice_with_nonzero_params_does_not_inflate_combinations() -> None:
    # C has chan == 0 throughout (a dummy voice) but wobbling amp/per. Including
    # its columns would report 3 combinations instead of 1.
    data = _blank(3)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampC")] = [-1.0, -2.0, -3.0]
    data[_row("perC")] = 0.983
    assert _summarize(data) == StimSummary("eS1p", 3, 1)


def test_inactive_voice_events_contribute_no_pulses() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 0, 1, 0]  # voice A idle on two events
    data[_row("countA")] = 1.0
    assert _summarize(data).n_pulses == 2


def test_no_active_voice_anywhere_is_all_zeros() -> None:
    data = _blank(7)
    data[_row("ampA")] = -100.0  # amp set but chan == 0: not stimulation
    assert _summarize(data) == StimSummary("eS1p", 0, 0)


def test_zero_events() -> None:
    assert _summarize(_blank(0)) == StimSummary("eS1p", 0, 0)


def test_row_count_mismatch_raises() -> None:
    data = np.zeros((23, 4), dtype=float)
    with pytest.raises(StimSchemaMismatch):
        _summarize(data)


def test_negative_chan_is_not_active() -> None:
    data = _blank(3)
    data[_row("chanA")] = -1.0
    assert _summarize(data) == StimSummary("eS1p", 0, 0)


def test_active_voice_with_zero_count_never_contributes_pulses() -> None:
    # Models the real reference block: B is the return/anode electrode. chanB sweeps
    # (so B counts as globally "active" and its columns join the combination count),
    # but countB is 0 for every event, so B never delivers a pulse — even on events
    # where B is chan-active and A is not.
    data = _blank(5)
    data[_row("chanA")] = [1, 1, 0, 1, 0]
    data[_row("countA")] = 1.0
    data[_row("chanB")] = [0, 5, 6, 0, 7]
    data[_row("countB")] = 0.0
    summary = _summarize(data)
    # Only the 3 events with chanA > 0 (events 0, 1, 3) deliver a pulse. Events 2 and 4
    # have chanA == 0 and chanB > 0, but countB == 0 there too, so they contribute 0 —
    # this is exactly the 438-event gap between 15999 real events and 15561 real pulses.
    assert summary.n_pulses == 3
    # n_combinations still uses both voices' columns (B is active), so it distinguishes
    # the four distinct (chanA, chanB) pairs among the 5 events (0 and 3 coincide).
    assert summary.n_combinations == 4


def test_stim_config_comes_from_the_packaged_config() -> None:
    sc, columns = stim_config_from(load_config())
    assert sc.store_pattern == "eS?p"
    assert sc.voices == ("A", "B", "C", "D")
    assert sc.chan_prefix == "chan"
    assert sc.count_prefix == "count"
    assert sc.amp_prefix == "amp"
    assert sc.per_prefix == "per"
    assert sc.per_to_hz == 1000.0
    assert sc.amp_units == "µA"
    assert sc.max_channels_listed == 5
    assert len(columns) == 24
    assert columns[:3] == ["perA", "countA", "ampA"]


def test_read_stim_summaries_without_headers_returns_a_single_warning() -> None:
    summaries, warnings = read_stim_summaries(Path("ignored"), load_config(), headers=None)
    assert summaries == []
    assert len(warnings) == 1


def test_read_stim_summaries_only_loads_stores_matching_the_pattern(monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import stim as mod

    # store_pattern is "eS?p": eS1p/eS2p match, Wav1 and Tick do not.
    headers = {"stores": {"eS1p": {}, "Wav1": {}, "eS2p": {}, "Tick": {}}}
    requested: list[str] = []

    def fake_load_store(block_path: Path, name: str, headers: Any = None) -> dict[str, Any]:
        requested.append(name)
        data = _blank(1)
        data[_row("chanA")] = 1.0
        data[_row("countA")] = 1.0
        return {"data": data}

    monkeypatch.setattr(mod, "load_store", fake_load_store)
    summaries, warnings = read_stim_summaries(Path("ignored"), load_config(), headers=headers)
    assert warnings == []
    assert sorted(requested) == ["eS1p", "eS2p"]
    assert sorted(s.store for s in summaries) == ["eS1p", "eS2p"]


def test_read_stim_summaries_skips_a_mismatched_store_but_keeps_the_rest(monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import stim as mod

    headers = {"stores": {"eS1p": {}, "eS2p": {}}}

    def fake_load_store(block_path: Path, name: str, headers: Any = None) -> dict[str, Any]:
        if name == "eS1p":
            return {"data": np.zeros((23, 4))}  # one row short of the 24-column schema
        data = _blank(2)
        data[_row("chanA")] = 1.0
        data[_row("countA")] = 1.0
        return {"data": data}

    monkeypatch.setattr(mod, "load_store", fake_load_store)
    summaries, warnings = read_stim_summaries(Path("ignored"), load_config(), headers=headers)
    assert [s.store for s in summaries] == ["eS2p"]
    assert summaries[0].n_pulses == 2
    assert any("eS1p" in w for w in warnings)


def test_format_channels_collapses_contiguous_runs() -> None:
    assert format_channels((1, 2, 3, 4, 5, 6, 7, 8, 12, 14), 5) == "1–8,12,14"


def test_format_channels_names_the_count_for_a_lone_range() -> None:
    assert format_channels(tuple(range(1, 33)), 5) == "1–32 (32 ch)"


def test_format_channels_truncates_a_long_scattered_list() -> None:
    assert format_channels((1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33), 5) == "1,3,5,7,9,… (17 ch)"


def test_format_channels_leaves_a_single_channel_bare() -> None:
    assert format_channels((12,), 5) == "12"


def test_format_channels_keeps_a_two_long_run_as_two_numbers() -> None:
    assert format_channels((4, 5), 5) == "4,5"


def test_format_channels_of_nothing_is_empty() -> None:
    assert format_channels((), 5) == ""
