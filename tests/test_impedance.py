"""Tests for impedance CSV discovery, parsing, and per-frequency averaging."""
import shutil
from pathlib import Path

import numpy as np
import pytest

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.impedance import (
    classify_impedance_csv,
    read_impedance,
    scan_impedance,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_classify_reads_channels_and_units(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_1row.csv", cfg)
    assert info is not None
    assert info.name == "impedance_1row"
    assert info.channel_numbers == (1, 2, 3, 4)
    assert info.units == "kOhm"


def test_classify_collects_distinct_frequencies(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_2freq.csv", cfg)
    assert info is not None
    assert info.frequencies == (1000.0, 5000.0)  # sorted, deduplicated


def test_classify_reports_no_frequencies_without_the_column(cfg) -> None:
    info = classify_impedance_csv(FIXTURES / "impedance_nofreq.csv", cfg)
    assert info is not None
    assert info.frequencies == ()


def test_classify_rejects_non_impedance_csv(cfg) -> None:
    assert classify_impedance_csv(FIXTURES / "not_impedance.csv", cfg) is None


def test_classify_skips_header_only_file(cfg) -> None:
    # The real EMG.csv has a valid impedance header but no data rows.
    assert classify_impedance_csv(FIXTURES / "impedance_empty.csv", cfg) is None


def test_scan_impedance_finds_only_impedance_csvs(tmp_path, cfg) -> None:
    for name in ("impedance_1row.csv", "impedance_2freq.csv",
                 "impedance_empty.csv", "not_impedance.csv"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    (tmp_path / "Notes.txt").write_text("not a csv")

    infos = scan_impedance(tmp_path, cfg)
    assert [i.name for i in infos] == ["impedance_1row", "impedance_2freq"]


def test_scan_impedance_respects_auto_scan_false(tmp_path) -> None:
    shutil.copy(FIXTURES / "impedance_1row.csv", tmp_path / "impedance_1row.csv")
    cfg = load_config(overrides=["impedance.auto_scan=false"])
    assert scan_impedance(tmp_path, cfg) == []


def test_read_impedance_averages_rows_within_frequency(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_2freq.csv", cfg)
    assert [g.frequency for g in data.groups] == [1000.0, 5000.0]
    # 1000 Hz: mean of [10,20,30,40] and [20,30,40,50]
    assert list(data.groups[0].values) == [15.0, 25.0, 35.0, 45.0]
    assert list(data.groups[1].values) == [100.0, 200.0, 300.0, 400.0]


def test_read_impedance_single_group_without_frequency_column(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_nofreq.csv", cfg)
    assert len(data.groups) == 1
    assert data.groups[0].frequency is None
    assert list(data.groups[0].values) == [15.0, 25.0, 35.0, 45.0]


def test_read_impedance_carries_metadata_columns(cfg) -> None:
    # REF is not a numbered channel, so it must not become a grid cell; it is
    # averaged per frequency and surfaced for the viewer footer instead.
    data = read_impedance(FIXTURES / "impedance_2freq.csv", cfg)
    assert data.groups[0].metadata["REF (kOhm)"] == 6.0  # mean of 5.0 and 7.0
    assert data.groups[1].metadata["REF (kOhm)"] == 9.0
    assert "R1 (kOhm)" not in data.groups[0].metadata


def test_read_impedance_reports_units_and_channels(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    assert data.units == "kOhm"
    assert data.channel_numbers == (1, 2, 3, 4)
    assert list(data.groups[0].values) == [10.0, 20.0, 30.0, 40.0]


def test_read_impedance_coerces_unmeasured_cells_to_nan(cfg, tmp_path) -> None:
    # A rig that fails to measure a contact writes a blank or a marker string.
    # That column must become NaN (an empty cell) rather than crashing the mean.
    csv = tmp_path / "gappy.csv"
    csv.write_text(
        "TIME (S),R1 (kOhm),R2 (kOhm),R3 (kOhm),R4 (kOhm)\n"
        "1,10.0,,30.0,OL\n"
        "2,20.0,,50.0,OL\n"
    )
    values = read_impedance(csv, cfg).groups[0].values
    assert values[0] == 15.0
    assert np.isnan(values[1])  # entirely blank column
    assert values[2] == 40.0
    assert np.isnan(values[3])  # non-numeric column
