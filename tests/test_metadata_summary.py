"""Tests for block summaries and the tiered reads."""
from datetime import datetime
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.listing import Gizmo
from tdt_ephyviewer_explorer.metadata.stim import StimSummary
from tdt_ephyviewer_explorer.metadata.summary import (
    BlockCache,
    BlockSummary,
    augment_with_headers,
    load_details,
    read_text_metadata,
    scan_tank,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"


def _block(tmp_path: Path, name: str = "Epi_02_Green-260727-154827",
           notes: bool = True, listing: bool = True) -> Path:
    blk = tmp_path / name
    blk.mkdir(parents=True)
    (blk / f"{name}.tsq").write_bytes(b"")
    if notes:
        (blk / "Notes.txt").write_bytes((FIXTURES / "Notes.txt").read_bytes())
    if listing:
        (blk / "StoresListing.txt").write_bytes((FIXTURES / "StoresListing.txt").read_bytes())
    return blk


class _Headers(dict):
    """Minimal stand-in for tdt's headers struct."""


def _headers(store_names: list[str], start: float = 1000.0, stop: float = 1600.0) -> _Headers:
    return _Headers(
        stores={n: {} for n in store_names},
        start_time=[start],
        stop_time=[stop],
    )


def test_text_metadata_reads_header_notes_and_gizmos(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    assert s.name == "Epi_02_Green-260727-154827"
    assert s.subject == "Epi_02_Green"
    assert s.experiment == "cnn_gp_mep_all_udp_v2"
    assert s.start == datetime(2026, 7, 27, 15, 48, 30)
    assert s.duration_s == pytest.approx(548.0)
    assert [n.text for n in s.notes] == [
        "first run should be chan 5 but is chan 4",
        "will correctly set chan 6 to 6 to avoid confusion",
    ]
    assert Gizmo("eStim1", "Electrical Stim Driver", ("eS1p", "eS1r")) in s.gizmos
    assert s.details_loaded is False


def test_text_metadata_without_notes_file(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path, notes=False))
    assert s.notes == ()
    assert s.start is None
    assert s.duration_s is None
    assert s.gizmos  # the listing still parsed


def test_text_metadata_without_stores_listing(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path, listing=False))
    assert s.gizmos == ()
    assert s.subject == "Epi_02_Green"


def test_augment_fills_duration_when_notes_did_not(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path, notes=False))
    out = augment_with_headers(s, _headers(["Wav1"], start=100.0, stop=250.0))
    assert out.duration_s == pytest.approx(150.0)


def test_augment_keeps_the_notes_duration(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    out = augment_with_headers(s, _headers(["Wav1"], start=0.0, stop=9999.0))
    assert out.duration_s == pytest.approx(548.0)  # Notes.txt wins


def test_augment_adds_unlisted_stores(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    out = augment_with_headers(s, _headers(["Tick", "eS1p", "eS1r", "Wav1", "Surprise"]))
    unlisted = [g for g in out.gizmos if g.object_id == "(unlisted)"]
    assert len(unlisted) == 1
    assert unlisted[0].stores == ("Surprise",)


def test_augment_adds_no_unlisted_gizmo_when_all_are_listed(tmp_path: Path) -> None:
    s = read_text_metadata(_block(tmp_path))
    out = augment_with_headers(s, _headers(["Tick", "eS1p", "eS1r", "Wav1"]))
    assert all(g.object_id != "(unlisted)" for g in out.gizmos)


def test_load_details_attaches_stim_and_marks_loaded(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    monkeypatch.setattr(mod, "read_headers", lambda p: _headers(["eS1p"]))
    monkeypatch.setattr(
        mod, "read_stim_summaries",
        lambda block_path, cfg, headers=None: ([StimSummary("eS1p", 15561, 1881)], []),
    )
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.stim == (StimSummary("eS1p", 15561, 1881),)
    assert out.details_loaded is True


def test_load_details_records_stim_warnings(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    monkeypatch.setattr(mod, "read_headers", lambda p: _headers(["eS1p"]))
    monkeypatch.setattr(
        mod, "read_stim_summaries",
        lambda block_path, cfg, headers=None: ([], ["eS1p: 23 rows but schema names 24"]),
    )
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.stim == ()
    assert any("23 rows" in w for w in out.warnings)


def test_load_details_survives_a_header_parse_failure(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    def boom(path):
        raise OSError("corrupt tsq")

    monkeypatch.setattr(mod, "read_headers", boom)
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.details_loaded is True  # done trying; not stuck on "loading…"
    assert any("corrupt tsq" in w for w in out.warnings)
    assert out.subject == "Epi_02_Green"  # tier-0 data survives


def test_load_details_survives_a_malformed_headers_object(tmp_path: Path, monkeypatch) -> None:
    """augment_with_headers can itself raise (e.g. no "stores" key); must degrade, not crash."""
    from tdt_ephyviewer_explorer.metadata import summary as mod

    monkeypatch.setattr(
        mod, "read_headers", lambda p: {"start_time": [0.0], "stop_time": [1.0]}
    )
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.details_loaded is True  # done trying; not stuck on "loading…"
    assert any("stores" in w for w in out.warnings)
    assert out.subject == "Epi_02_Green"  # tier-0 data survives


def test_load_details_survives_a_stim_summary_exception(tmp_path: Path, monkeypatch) -> None:
    """read_stim_summaries can raise (e.g. KeyError from a misconfigured schema)."""
    from tdt_ephyviewer_explorer.metadata import summary as mod

    monkeypatch.setattr(mod, "read_headers", lambda p: _headers(["eS1p"]))

    def boom(block_path, cfg, headers=None):
        raise KeyError("no such schema")

    monkeypatch.setattr(mod, "read_stim_summaries", boom)
    out = load_details(read_text_metadata(_block(tmp_path)), cfg=None)
    assert out.details_loaded is True
    assert out.stim == ()
    assert any("no such schema" in w for w in out.warnings)


def test_scan_tank_returns_one_summary_per_block(tmp_path: Path) -> None:
    _block(tmp_path, "blockB-2")
    _block(tmp_path, "blockA-1")
    assert [s.name for s in scan_tank(tmp_path)] == ["blockA-1", "blockB-2"]


def test_scan_tank_marks_a_block_it_cannot_read(tmp_path: Path, monkeypatch) -> None:
    from tdt_ephyviewer_explorer.metadata import summary as mod

    _block(tmp_path, "blockA-1")

    def boom(path):
        raise OSError("permission denied")

    monkeypatch.setattr(mod, "read_text_metadata", boom)
    out = scan_tank(tmp_path)
    assert len(out) == 1  # never silently dropped
    assert any("permission denied" in w for w in out[0].warnings)


def test_scan_tank_never_touches_tier_1_or_2(tmp_path: Path, monkeypatch) -> None:
    """Pins the tiering: scan_tank must not reach for the expensive reads."""
    from tdt_ephyviewer_explorer.metadata import summary as mod

    _block(tmp_path, "blockA-1")

    def boom(*args, **kwargs):
        raise AssertionError("scan_tank must not call tier-1/2 reads")

    monkeypatch.setattr(mod, "read_headers", boom)
    monkeypatch.setattr(mod, "read_stim_summaries", boom)
    out = scan_tank(tmp_path)
    assert [s.name for s in out] == ["blockA-1"]


def test_cache_returns_what_was_put(tmp_path: Path) -> None:
    cache = BlockCache()
    cache.use_tank(tmp_path)
    s = read_text_metadata(_block(tmp_path))
    cache.put(s)
    assert cache.get(s.name) is s


def test_cache_clears_on_a_different_tank(tmp_path: Path) -> None:
    cache = BlockCache()
    cache.use_tank(tmp_path)
    s = read_text_metadata(_block(tmp_path))
    cache.put(s)

    cache.use_tank(tmp_path / "other")
    assert cache.get(s.name) is None


def test_cache_survives_reselecting_the_same_tank(tmp_path: Path) -> None:
    cache = BlockCache()
    cache.use_tank(tmp_path)
    s = read_text_metadata(_block(tmp_path))
    cache.put(s)

    cache.use_tank(tmp_path)  # same tank: expensive details must not be thrown away
    assert cache.get(s.name) is s
