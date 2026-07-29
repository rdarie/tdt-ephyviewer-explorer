"""Tests for encoding-tolerant reads and atomic writes."""
from pathlib import Path
from unittest.mock import patch

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


def test_write_text_atomic_cleanup_on_replace_failure(tmp_path: Path) -> None:
    """Verify crash-safety: OSError on rename leaves original intact and no temp file."""
    p = tmp_path / "a.txt"
    original = "original\r\n"
    write_text_atomic(p, original)

    # Monkeypatch os.replace to raise OSError during the rename phase
    with patch("tdt_ephyviewer_explorer.metadata.textio.os.replace", side_effect=OSError("Rename failed")):
        with pytest.raises(OSError, match="Rename failed"):
            write_text_atomic(p, "new content\r\n")

    # Verify: original file unchanged, no .tmp file left
    assert p.read_bytes() == original.encode("utf-8")
    assert [f.name for f in tmp_path.iterdir()] == ["a.txt"]
