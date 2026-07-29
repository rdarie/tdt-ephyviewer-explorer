"""Tests for encoding-tolerant reads and atomic writes."""
from pathlib import Path

import pytest

from tdt_ephyviewer_explorer.metadata.textio import read_text, write_text_atomic


def test_read_text_reads_utf8(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes("café\r\n".encode("utf-8"))
    assert read_text(p) == "café\r\n"


def test_read_text_falls_back_to_latin1(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes(b"caf\xe9\r\n")  # latin-1, invalid as utf-8
    assert read_text(p) == "café\r\n"


def test_read_text_preserves_crlf(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes(b"one\r\ntwo\r\n")
    assert read_text(p) == "one\r\ntwo\r\n"  # no universal-newline translation


def test_write_text_atomic_roundtrips_and_leaves_no_temp(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    write_text_atomic(p, "one\r\ntwo\r\n")
    assert p.read_bytes() == b"one\r\ntwo\r\n"
    assert [f.name for f in tmp_path.iterdir()] == ["a.txt"]


def test_write_text_atomic_overwrites(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    write_text_atomic(p, "first\r\n")
    write_text_atomic(p, "second\r\n")
    assert p.read_bytes() == b"second\r\n"
