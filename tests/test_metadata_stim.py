"""Tests for the eStim pulse/parameter-combination summary."""
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.metadata.stim import (
    StimConfig,
    StimSchemaMismatch,
    StimSummary,
    VoiceSummary,
    format_channels,
    format_range,
    format_voice_line,
    read_stim_summaries,
    schema_warnings,
    stim_config_from,
    summarize_stim,
)

VOICES = ("A", "B", "C", "D")
COLS = tuple(
    f"{field}{v}" for v in VOICES
    for field in ("per", "count", "amp", "dur", "delay", "chan")
)

SETTINGS = StimConfig(
    store_pattern="eS?p", schema="iz_param_names", voices=VOICES,
    chan_prefix="chan", count_prefix="count", amp_prefix="amp", per_prefix="per",
    per_to_hz=1000.0, amp_units="µA", max_channels_listed=5,
)


def _blank(n_events: int) -> np.ndarray:
    """A (24, n_events) all-zero parameter block."""
    return np.zeros((len(COLS), n_events), dtype=float)


def _row(name: str) -> int:
    return COLS.index(name)


def _summarize(data: np.ndarray, settings: StimConfig = SETTINGS) -> StimSummary:
    return summarize_stim("eS1p", data, COLS, settings)


def test_single_active_voice_one_pulse_each() -> None:
    data = _blank(10)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    summary = _summarize(data)
    assert (summary.n_pulses, summary.n_combinations) == (10, 1)


def test_sweeping_a_channel_counts_distinct_combinations() -> None:
    data = _blank(6)
    data[_row("chanA")] = [1, 1, 2, 2, 3, 3]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    summary = _summarize(data)
    assert (summary.n_pulses, summary.n_combinations) == (6, 3)


def test_two_active_voices_combine_into_pairs() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 1, 2, 2]
    data[_row("chanB")] = [5, 6, 5, 6]
    data[_row("countA")] = 1.0
    data[_row("countB")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("ampB")] = -100.0
    summary = _summarize(data)
    assert (summary.n_pulses, summary.n_combinations) == (4, 4)


def test_count_greater_than_one_yields_more_pulses_than_events() -> None:
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    data[_row("ampA")] = -100.0
    assert _summarize(data).n_pulses == 15


def test_concurrent_voices_do_not_double_count_pulses() -> None:
    # A and B fire together; a 3-pulse train is 3 pulses in time, not 6.
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = 2.0
    data[_row("countB")] = 3.0
    data[_row("ampB")] = -100.0
    assert _summarize(data).n_pulses == 15


def test_pulses_take_the_max_across_voices() -> None:
    data = _blank(1)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 2.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = 1.0
    data[_row("countB")] = 5.0
    data[_row("ampB")] = -100.0
    assert _summarize(data).n_pulses == 5


def test_idle_voice_with_nonzero_params_does_not_inflate_combinations() -> None:
    # C never has a channel, so its wobbling amp/per stay out of the combination count.
    data = _blank(3)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("ampC")] = [-1.0, -2.0, -3.0]
    data[_row("perC")] = 0.983
    summary = _summarize(data)
    assert (summary.n_pulses, summary.n_combinations) == (3, 1)


def test_inactive_voice_events_contribute_no_pulses() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 0, 1, 0]  # voice A idle on two events
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
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
    data[_row("ampA")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 0, 0)


def test_a_zero_amplitude_return_electrode_is_not_a_voice() -> None:
    # The reference block's voice B is the anode: chanB sweeps, but countB and ampB are
    # 0 throughout, so B delivers no charge. It is not stimulation, so it contributes
    # neither pulses nor combinations -- only chanA's single setting remains.
    data = _blank(5)
    data[_row("chanA")] = [1, 1, 0, 1, 0]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = [0, 5, 6, 0, 7]
    data[_row("countB")] = 0.0
    summary = _summarize(data)
    assert summary.n_pulses == 3  # only events 0, 1, 3 have chanA > 0
    assert summary.n_combinations == 1


def test_an_active_voice_with_zero_count_contributes_combinations_not_pulses() -> None:
    # B delivers charge (ampB != 0) but its trains are empty, so it joins the
    # combination count while adding no pulses of its own.
    data = _blank(5)
    data[_row("chanA")] = [1, 1, 0, 1, 0]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = [0, 5, 6, 0, 7]
    data[_row("countB")] = 0.0
    data[_row("ampB")] = -50.0
    summary = _summarize(data)
    assert summary.n_pulses == 3
    # Events where nothing is on are excluded; the four remaining (chanA, chanB) pairs
    # are (1,0), (1,5), (0,6), (1,0) again, (0,7) -- four distinct.
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
        data[_row("ampA")] = -100.0
        return {"data": data}

    monkeypatch.setattr(mod, "load_store", fake_load_store)
    summaries, warnings = read_stim_summaries(Path("ignored"), load_config(), headers=headers)
    assert [s.store for s in summaries] == ["eS2p"]
    assert summaries[0].n_pulses == 2
    assert any("eS1p" in w for w in warnings)


def test_format_channels_collapses_contiguous_runs() -> None:
    assert format_channels((1, 2, 3, 4, 5, 6, 7, 8, 12, 14), 5) == "1–8,12,14"


def test_format_channels_leaves_a_lone_range_bare() -> None:
    assert format_channels(tuple(range(1, 33)), 5) == "1–32"


def test_format_channels_truncates_a_long_scattered_list() -> None:
    assert format_channels((1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33), 5) == "1,3,5,7,9,… (17 ch)"


def test_format_channels_leaves_a_single_channel_bare() -> None:
    assert format_channels((12,), 5) == "12"


def test_format_channels_keeps_a_two_long_run_as_two_numbers() -> None:
    assert format_channels((4, 5), 5) == "4,5"


def test_format_channels_of_nothing_is_empty() -> None:
    assert format_channels((), 5) == ""


def test_format_channels_handles_zero_or_negative_max_listed() -> None:
    assert format_channels((1, 2, 3), 0) == "… (3 ch)"
    assert format_channels((1, 2, 3), -1) == "… (3 ch)"


def test_format_range_spans_two_values() -> None:
    assert format_range(100.0, 800.0, "µA") == "100–800 µA"


def test_format_range_collapses_when_the_bounds_match() -> None:
    assert format_range(200.0, 200.0, "µA") == "200 µA"


def test_format_range_prefixes_the_sign_once() -> None:
    assert format_range(100.0, 800.0, "µA", "-") == "-100–800 µA"
    assert format_range(100.0, 800.0, "µA", "±") == "±100–800 µA"


def test_format_range_strips_a_trailing_zero_decimal() -> None:
    assert format_range(20.0, 20.0, "Hz") == "20 Hz"


def test_format_range_keeps_a_meaningful_decimal() -> None:
    assert format_range(0.5, 12.5, "Hz") == "0.5–12.5 Hz"


def test_voice_rows_carry_channels_amplitude_and_frequency() -> None:
    data = _blank(3)
    data[_row("chanA")] = [1, 2, 3]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = [-100.0, -400.0, -800.0]
    data[_row("perA")] = [100.0, 50.0, 20.0]  # ms -> 10, 20, 50 Hz
    (voice,) = _summarize(data).voices
    assert voice == VoiceSummary("A", (1, 2, 3), 100.0, 800.0, "-", 10.0, 50.0)


def test_only_active_voices_get_a_row() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = 7.0  # wired, but ampB == 0: no charge, no row
    assert [v.voice for v in _summarize(data).voices] == ["A"]


def test_voice_rows_follow_configured_voice_order() -> None:
    data = _blank(1)
    for voice, channel in (("C", 3), ("A", 1)):
        data[_row(f"chan{voice}")] = float(channel)
        data[_row(f"count{voice}")] = 1.0
        data[_row(f"amp{voice}")] = -100.0
    assert [v.voice for v in _summarize(data).voices] == ["A", "C"]


def test_ranges_ignore_events_where_the_voice_is_off() -> None:
    # The stray -5 µA sits on an event where chanA is 0, so it must not lower amp_min.
    data = _blank(3)
    data[_row("chanA")] = [1, 0, 1]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = [-100.0, -5.0, -800.0]
    (voice,) = _summarize(data).voices
    assert (voice.amp_min, voice.amp_max) == (100.0, 800.0)
    assert voice.channels == (1,)


def test_mixed_polarity_is_marked() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = [-100.0, 800.0]
    (voice,) = _summarize(data).voices
    assert voice.amp_sign == "±"
    assert (voice.amp_min, voice.amp_max) == (100.0, 800.0)


def test_anodic_only_amplitudes_are_marked_positive() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = 300.0
    (voice,) = _summarize(data).voices
    assert voice.amp_sign == "+"


def test_a_nonpositive_period_yields_no_frequency() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("perA")] = 0.0  # never divide by it
    (voice,) = _summarize(data).voices
    assert voice.freq_min_hz is None
    assert voice.freq_max_hz is None


def test_a_zero_period_event_drops_out_of_the_frequency_range() -> None:
    data = _blank(3)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("perA")] = [100.0, 0.0, 25.0]
    (voice,) = _summarize(data).voices
    assert (voice.freq_min_hz, voice.freq_max_hz) == (10.0, 40.0)


def _voice(**kwargs: Any) -> VoiceSummary:
    fields: dict[str, Any] = dict(
        voice="A", channels=(1, 3, 5), amp_min=100.0, amp_max=800.0,
        amp_sign="-", freq_min_hz=10.0, freq_max_hz=50.0,
    )
    fields.update(kwargs)
    return VoiceSummary(**fields)


def test_voice_line_joins_channels_amplitude_and_frequency() -> None:
    assert format_voice_line(_voice(), SETTINGS) == "ch 1,3,5 · -100–800 µA · 10–50 Hz"


def test_voice_line_drops_the_frequency_clause_when_there_is_none() -> None:
    line = format_voice_line(_voice(freq_min_hz=None, freq_max_hz=None), SETTINGS)
    assert line == "ch 1,3,5 · -100–800 µA"


def test_voice_line_drops_the_amplitude_clause_when_the_schema_has_none() -> None:
    line = format_voice_line(_voice(amp_sign="", amp_min=0.0, amp_max=0.0), SETTINGS)
    assert line == "ch 1,3,5 · 10–50 Hz"


def test_voice_line_honours_the_channel_cap() -> None:
    voice = _voice(channels=tuple(range(1, 34, 2)))  # 17 odd channels, 1..33
    assert format_voice_line(voice, SETTINGS).startswith("ch 1,3,5,7,9,… (17 ch) · ")


def test_schema_warnings_name_the_missing_column() -> None:
    columns = [c for c in COLS if c != "ampA"]
    (warning,) = schema_warnings(columns, SETTINGS)
    assert "ampA" in warning


def test_a_complete_schema_warns_about_nothing() -> None:
    assert schema_warnings(COLS, SETTINGS) == []
