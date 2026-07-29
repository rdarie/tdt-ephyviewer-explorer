"""Encoding-tolerant text reads and crash-safe writes for the metadata sidecar files."""
from __future__ import annotations

import os
from pathlib import Path


def read_text(path: Path) -> str:
    """Read a text file as UTF-8, falling back to latin-1.

    Synapse sidecar files are Windows-authored and occasionally carry a stray
    non-UTF-8 byte; latin-1 decodes any byte sequence, so this never raises on
    content. Newlines are returned verbatim (no universal-newline translation) so a
    parsed file can be re-rendered byte-for-byte.

    :param path: File to read.
    :returns: The decoded text.
    :raises OSError: If the file cannot be read.
    """
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as UTF-8 via a same-directory temp file and rename.

    A crash mid-write leaves the previous file intact rather than a truncated one.
    The temp file is a sibling so the rename stays on one filesystem.

    :param path: Destination file.
    :param text: Full file content, newlines already as intended.
    :raises OSError: If the directory is not writable or the rename fails.
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
