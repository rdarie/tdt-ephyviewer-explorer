"""Tests for Notes.txt parsing and rendering."""
from datetime import datetime
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.notes import (
    Note,
    NotesFile,
    parse_notes,
    read_notes,
    render_notes,
)

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"
NOTES = FIXTURES / "Notes.txt"
NO_NOTES = FIXTURES / "Notes_nonotes.txt"


def test_parses_header_fields() -> None:
    nf = parse_notes(NOTES.read_bytes().decode("utf-8"))
    assert nf.experiment == "cnn_gp_mep_all_udp_v2"
    assert nf.subject == "Epi_02_Green"
    assert nf.user == "User"
    assert nf.start == datetime(2026, 7, 27, 15, 48, 30)
    assert nf.stop == datetime(2026, 7, 27, 15, 57, 38)


def test_parses_notes_with_the_start_date_inferred() -> None:
    nf = parse_notes(NOTES.read_bytes().decode("utf-8"))
    assert nf.notes == (
        Note(1, datetime(2026, 7, 27, 15, 49, 37),
             "first run should be chan 5 but is chan 4"),
        Note(2, datetime(2026, 7, 27, 15, 50, 16),
             "will correctly set chan 6 to 6 to avoid confusion"),
    )
    assert nf.warnings == ()


def test_parses_an_explicit_date_on_a_note() -> None:
    text = (
        'Start: 3:48:30pm 07/27/2026\r\n\r\n'
        'Note-1: 2:02:14pm 07/29/2026 "EMG saturated"\r\n\r\n'
        'Stop: 3:57:38pm 07/27/2026\r\n'
    )
    nf = parse_notes(text)
    assert nf.notes[0].timestamp == datetime(2026, 7, 29, 14, 2, 14)


def test_note_text_may_contain_quotes() -> None:
    text = 'Start: 3:48:30pm 07/27/2026\r\n\r\nNote-1: 3:49:00pm "he said "ok" then"\r\n'
    assert parse_notes(text).notes[0].text == 'he said "ok" then'


def test_unparseable_note_line_is_warned_and_skipped() -> None:
    text = (
        'Start: 3:48:30pm 07/27/2026\r\n\r\n'
        'Note-1: not a time "bad"\r\n'
        'Note-2: 3:50:16pm "good"\r\n'
    )
    nf = parse_notes(text)
    assert [n.text for n in nf.notes] == ["good"]  # the good one survives
    assert len(nf.warnings) == 1
    assert "Note-1" in nf.warnings[0]


def test_no_notes_file_parses_to_no_notes() -> None:
    nf = parse_notes(NO_NOTES.read_bytes().decode("utf-8"))
    assert nf.notes == ()
    assert nf.subject == "Mickey"


def test_render_reproduces_the_source_bytes() -> None:
    original = NOTES.read_bytes().decode("utf-8")
    assert render_notes(parse_notes(original)) == original


def test_render_reproduces_the_no_notes_layout() -> None:
    # Two blank lines between Start and Stop when there are no notes.
    original = NO_NOTES.read_bytes().decode("utf-8")
    assert render_notes(parse_notes(original)) == original


def test_roundtrip_is_stable_across_two_passes() -> None:
    once = parse_notes(NOTES.read_bytes().decode("utf-8"))
    assert parse_notes(render_notes(once)) == once


def test_render_omits_the_date_when_it_matches_start() -> None:
    nf = NotesFile(
        experiment="e", subject="s", user="u",
        start=datetime(2026, 7, 27, 15, 48, 30),
        stop=datetime(2026, 7, 27, 15, 57, 38),
        notes=(Note(1, datetime(2026, 7, 27, 16, 0, 0), "same day"),),
        warnings=(),
    )
    assert 'Note-1: 4:00:00pm "same day"' in render_notes(nf)


def test_render_includes_the_date_when_it_differs_from_start() -> None:
    nf = NotesFile(
        experiment="e", subject="s", user="u",
        start=datetime(2026, 7, 27, 15, 48, 30),
        stop=datetime(2026, 7, 27, 15, 57, 38),
        notes=(Note(1, datetime(2026, 7, 29, 14, 2, 14), "two days later"),),
        warnings=(),
    )
    assert 'Note-1: 2:02:14pm 07/29/2026 "two days later"' in render_notes(nf)


def test_render_uses_crlf_and_a_trailing_newline() -> None:
    out = render_notes(parse_notes(NOTES.read_bytes().decode("utf-8")))
    assert "\r\n" in out
    assert out.endswith("\r\n")
    assert "\n" not in out.replace("\r\n", "")  # no bare LF anywhere


@pytest.mark.parametrize(
    "moment,expected",
    [
        (datetime(2026, 1, 1, 0, 5, 9), "12:05:09am"),   # midnight is 12am
        (datetime(2026, 1, 1, 12, 5, 9), "12:05:09pm"),  # noon is 12pm
        (datetime(2026, 1, 1, 9, 5, 9), "9:05:09am"),    # hour is not zero-padded
        (datetime(2026, 1, 1, 23, 5, 9), "11:05:09pm"),
    ],
)
def test_time_formatting_edges(moment: datetime, expected: str) -> None:
    nf = NotesFile(
        experiment=None, subject=None, user=None,
        start=datetime(2026, 1, 1, 0, 0, 0), stop=None,
        notes=(Note(1, moment, "x"),), warnings=(),
    )
    assert f"Note-1: {expected} " in render_notes(nf)


def test_read_notes_missing_file_is_empty(tmp_path: Path) -> None:
    nf = read_notes(tmp_path / "Notes.txt")
    assert nf.notes == ()
    assert nf.start is None


def test_read_notes_reads_a_real_file(tmp_path: Path) -> None:
    p = tmp_path / "Notes.txt"
    p.write_bytes(NOTES.read_bytes())
    assert read_notes(p).subject == "Epi_02_Green"
