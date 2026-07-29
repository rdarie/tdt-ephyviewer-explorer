"""Tests for the StoresListing.txt parser."""
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.listing import (
    Gizmo,
    parse_stores_listing,
    read_stores_listing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "metadata" / "StoresListing.txt"


def test_parses_gizmos_with_kinds_and_stores() -> None:
    gizmos = parse_stores_listing(FIXTURE.read_text())
    assert gizmos == [
        Gizmo("RZ2(1)", "RZn Processor", ("Tick",)),
        Gizmo("eStim1", "Electrical Stim Driver", ("eS1p", "eS1r")),
        Gizmo("Wave1", "Stream Data Storage", ("Wav1",)),
    ]


def test_stops_at_the_flat_listing() -> None:
    # The flat listing repeats every store; parsing into it would duplicate them.
    gizmos = parse_stores_listing(FIXTURE.read_text())
    assert sum(len(g.stores) for g in gizmos) == 4


def test_object_id_without_a_kind() -> None:
    text = "Object ID : Solo\n Store ID : ABCD\n"
    assert parse_stores_listing(text) == [Gizmo("Solo", None, ("ABCD",))]


def test_gizmo_with_no_stores_is_kept() -> None:
    text = "Object ID : Empty - Some Kind\n Rate : 100 Hz\n"
    assert parse_stores_listing(text) == [Gizmo("Empty", "Some Kind", ())]


def test_truncated_file_yields_what_it_can() -> None:
    text = "Object ID : eStim1 - Electrical Stim Driver\n Store ID : eS1p\n Store ID"
    assert parse_stores_listing(text) == [Gizmo("eStim1", "Electrical Stim Driver", ("eS1p",))]


def test_empty_text_yields_nothing() -> None:
    assert parse_stores_listing("") == []


def test_header_only_file_yields_nothing() -> None:
    assert parse_stores_listing("Experiment: x\nSubject: y\nUser: z\n") == []


def test_read_stores_listing_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_stores_listing(tmp_path) == []


def test_read_stores_listing_reads_the_block_file(tmp_path: Path) -> None:
    (tmp_path / "StoresListing.txt").write_bytes(FIXTURE.read_bytes())
    assert [g.object_id for g in read_stores_listing(tmp_path)] == [
        "RZ2(1)",
        "eStim1",
        "Wave1",
    ]
