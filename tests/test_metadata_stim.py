"""Tests for the eStim pulse/parameter-combination summary."""
import numpy as np
import pytest

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.stim import (
    StimSchemaMismatch,
    StimSummary,
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


def test_stim_config_comes_from_the_packaged_config() -> None:
    sc, columns = stim_config_from(load_config())
    assert sc.store_pattern == "eS?p"
    assert sc.voices == ("A", "B", "C", "D")
    assert sc.chan_prefix == "chan"
    assert sc.count_prefix == "count"
    assert len(columns) == 24
    assert columns[:3] == ["perA", "countA", "ampA"]
