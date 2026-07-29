"""Parsing and rendering of Synapse ``Notes.txt`` and the ``analysis_notes.txt`` sidecar."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from tdt_ephyviewer_explorer.metadata.textio import read_text, write_text_atomic

NOTES_FILENAME = "Notes.txt"

LINE_END = "\r\n"
_TIME_FMT = "%I:%M:%S%p"
_DATE_FMT = "%m/%d/%Y"

_NOTE_RE = re.compile(
    r'^Note-(?P<index>\d+):\s+'
    r'(?P<time>\d{1,2}:\d{2}:\d{2}\s*[ap]m)'
    r'(?:\s+(?P<date>\d{1,2}/\d{1,2}/\d{4}))?'
    r'\s+"(?P<text>.*)"\s*$',
    re.IGNORECASE,
)
_HEADER_KEYS = {"Experiment": "experiment", "Subject": "subject", "User": "user"}


@dataclass(frozen=True)
class Note:
    """One timestamped note.

    :param index: 1-based position within its file.
    :param timestamp: When the note was taken (wall clock).
    :param text: The note body, without surrounding quotes.
    """

    index: int
    timestamp: datetime
    text: str


@dataclass(frozen=True)
class NotesFile:
    """A parsed notes file: its header block plus its notes.

    :param experiment: Experiment name, or ``None``.
    :param subject: Subject name, or ``None``.
    :param user: Synapse user, or ``None``.
    :param start: Recording start, or ``None``.
    :param stop: Recording stop, or ``None``.
    :param notes: The notes, in file order.
    :param warnings: Human-readable problems found while parsing.
    """

    experiment: str | None
    subject: str | None
    user: str | None
    start: datetime | None
    stop: datetime | None
    notes: tuple[Note, ...]
    warnings: tuple[str, ...]


EMPTY_NOTES = NotesFile(None, None, None, None, None, (), ())


def _parse_moment(time_token: str, date_token: str | None, fallback: datetime | None) -> datetime:
    """Combine a ``3:33:11pm`` token with a date, falling back to another date.

    :param time_token: The time-of-day token.
    :param date_token: An ``MM/DD/YYYY`` token, or ``None`` to use ``fallback``.
    :param fallback: Date to borrow when ``date_token`` is absent.
    :returns: The combined timestamp.
    :raises ValueError: If either token is malformed, or no date is available.
    """
    clock = datetime.strptime(time_token.replace(" ", ""), _TIME_FMT)
    if date_token is not None:
        day = datetime.strptime(date_token, _DATE_FMT)
    elif fallback is not None:
        day = fallback
    else:
        raise ValueError("no date available for a time-only entry")
    return day.replace(
        hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=0
    )


def _parse_header_moment(value: str) -> datetime:
    """Parse a ``Start:``/``Stop:`` value of the form ``3:29:27pm 07/27/2026``.

    :param value: The value after the colon.
    :returns: The parsed timestamp.
    :raises ValueError: If the value is malformed.
    """
    parts = value.split()
    if len(parts) != 2:
        raise ValueError(f"expected '<time> <date>', got {value!r}")
    return _parse_moment(parts[0], parts[1], None)


def parse_notes(text: str) -> NotesFile:
    """Parse a Synapse notes file.

    Accepts both entry forms: ``Note-1: 3:33:11pm "text"`` (date inferred from
    ``Start:``) and ``Note-1: 2:02:14pm 07/29/2026 "text"``. A line that will not
    parse is skipped and recorded in :attr:`NotesFile.warnings` rather than
    aborting the file.

    :param text: Full file contents.
    :returns: The parsed file.
    """
    fields: dict[str, str | None] = {"experiment": None, "subject": None, "user": None}
    start: datetime | None = None
    stop: datetime | None = None
    warnings: list[str] = []
    raw_notes: list[tuple[str, str | None, str]] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if sep and key in _HEADER_KEYS:
            fields[_HEADER_KEYS[key]] = value.strip()
            continue
        if sep and key in ("Start", "Stop"):
            try:
                moment = _parse_header_moment(value.strip())
            except ValueError as exc:
                warnings.append(f"{key}: {exc}")
                continue
            if key == "Start":
                start = moment
            else:
                stop = moment
            continue
        if line.startswith("Note-"):
            match = _NOTE_RE.match(line)
            if match is None:
                warnings.append(f"unparseable note line: {line}")
                continue
            raw_notes.append((match["time"], match["date"], match["text"]))

    # Notes are resolved after the loop because a time-only note borrows Start's
    # date, and Start may appear after some notes in a hand-edited file.
    notes: list[Note] = []
    for time_token, date_token, body in raw_notes:
        try:
            moment = _parse_moment(time_token, date_token, start)
        except ValueError as exc:
            warnings.append(f"unparseable note timestamp {time_token!r}: {exc}")
            continue
        notes.append(Note(len(notes) + 1, moment, body))

    return NotesFile(
        experiment=fields["experiment"],
        subject=fields["subject"],
        user=fields["user"],
        start=start,
        stop=stop,
        notes=tuple(notes),
        warnings=tuple(warnings),
    )


def format_clock(moment: datetime) -> str:
    """Format a timestamp as Synapse does: ``3:33:11pm``, hour not zero-padded.

    ``strftime('%I:%M:%S%p')`` yields ``03:33:11PM``, which does not match the file
    format, so this is hand-rolled.

    :param moment: The timestamp.
    :returns: The formatted time of day.
    """
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    return f"{hour}:{moment.minute:02d}:{moment.second:02d}{suffix}"


def format_day(moment: datetime) -> str:
    """Format a timestamp's date as ``MM/DD/YYYY``.

    :param moment: The timestamp.
    :returns: The formatted date.
    """
    return moment.strftime(_DATE_FMT)


def _render_note(note: Note, start: datetime | None) -> str:
    """Render one note line, including the date only when it differs from ``start``.

    Omitting a same-day date is what makes rendering a parsed ``Notes.txt`` produce
    the original bytes; including a differing date is what lets an analysis note
    written days later round-trip.

    :param note: The note to render.
    :param start: The file's recording start, for the same-day comparison.
    :returns: The rendered line, without a line terminator.
    """
    stamp = format_clock(note.timestamp)
    if start is None or note.timestamp.date() != start.date():
        stamp = f"{stamp} {format_day(note.timestamp)}"
    return f'Note-{note.index}: {stamp} "{note.text}"'


def render_notes(nf: NotesFile) -> str:
    """Render a notes file back to Synapse's format.

    Layout is header / blank / notes / blank / ``Stop``, which collapses to two
    consecutive blank lines when there are no notes — exactly what Synapse writes.
    Lines are CRLF-terminated, including the last.

    :param nf: The notes file to render.
    :returns: The full file text.
    """
    lines: list[str] = []
    if nf.experiment is not None:
        lines.append(f"Experiment: {nf.experiment}")
    if nf.subject is not None:
        lines.append(f"Subject: {nf.subject}")
    if nf.user is not None:
        lines.append(f"User: {nf.user}")
    if nf.start is not None:
        lines.append(f"Start: {format_clock(nf.start)} {format_day(nf.start)}")
    lines.append("")
    lines.extend(_render_note(n, nf.start) for n in nf.notes)
    lines.append("")
    if nf.stop is not None:
        lines.append(f"Stop: {format_clock(nf.stop)} {format_day(nf.stop)}")
    return LINE_END.join(lines) + LINE_END


def renumber(notes: tuple[Note, ...]) -> tuple[Note, ...]:
    """Reindex notes ``1..N`` in their current order.

    :param notes: Notes in the desired order.
    :returns: The same notes with contiguous 1-based indices.
    """
    return tuple(replace(n, index=i) for i, n in enumerate(notes, start=1))


def read_notes(path: Path) -> NotesFile:
    """Read and parse a notes file.

    :param path: Path to the notes file.
    :returns: The parsed file, or :data:`EMPTY_NOTES` when it does not exist.
    """
    if not path.is_file():
        return EMPTY_NOTES
    return parse_notes(read_text(path))


class NotesConflict(RuntimeError):
    """Raised when the notes file changed on disk since it was loaded."""


@dataclass(frozen=True)
class _Snapshot:
    """A fingerprint of the sidecar file at the moment it was last read.

    ``mtime`` alone is not a reliable staleness signal: two writes in quick
    succession can land within the same filesystem timestamp tick (observed on
    Windows), so ``size`` and a content ``digest`` are also captured and compared.

    :param mtime: The file's mtime.
    :param size: The file's size in bytes.
    :param digest: A SHA-256 hex digest of the file's bytes.
    """

    mtime: float
    size: int
    digest: str


def _snapshot(path: Path) -> _Snapshot:
    """Fingerprint an existing file's mtime, size, and content.

    :param path: The file to fingerprint; must exist.
    :returns: The fingerprint.
    :raises OSError: If the file cannot be read.
    """
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return _Snapshot(mtime=stat.st_mtime, size=stat.st_size, digest=digest)


class AnalysisNotes:
    """Mutable, savable view of a block's ``analysis_notes.txt``.

    Notes are stamped with the wall clock at the moment they are typed. The file is
    written whole and atomically, and a write is refused if the file changed on disk
    since it was loaded, so two open windows cannot silently clobber each other.
    """

    def __init__(self, path: Path, header: NotesFile, notes: tuple[Note, ...],
                 snapshot: _Snapshot | None) -> None:
        """:param path: The sidecar file path (may not exist yet).
        :param header: Header block to write with the notes.
        :param notes: Notes loaded from disk, if any.
        :param snapshot: Fingerprint of the file when loaded; ``None`` if it did
            not exist."""
        self._path = path
        self._header = header
        self._notes = notes
        self._snapshot = snapshot

    @classmethod
    def load(cls, block_path: Path, filename: str, header: NotesFile) -> AnalysisNotes:
        """Load a block's analysis notes, or start an empty set.

        An existing file's own header wins over ``header``: the file records the
        recording it belongs to, and a caller's fallback must not overwrite it.

        :param block_path: The block directory.
        :param filename: Sidecar filename, from config.
        :param header: Header to use when the file does not exist yet, normally
            taken from the block's ``Notes.txt``.
        :returns: The loaded editing model. No file is created.
        """
        path = block_path / filename
        if not path.is_file():
            return cls(path, header, (), None)
        existing = read_notes(path)
        return cls(path, existing, existing.notes, _snapshot(path))

    def reload(self) -> None:
        """Re-read the file from disk, replacing header, notes, and staleness snapshot.

        This is the recovery path for a :exc:`NotesConflict`: after another writer
        has saved, calling ``reload`` catches this instance up to the on-disk state
        (the same state :meth:`load` would produce for the same path) so the next
        :meth:`save` is no longer stale. Any local, unsaved edits are discarded by
        design -- the caller is expected to reapply a pending change on top, if any.

        :raises OSError: If the file exists but cannot be read.
        """
        if not self._path.is_file():
            self._notes = ()
            self._snapshot = None
            return
        existing = read_notes(self._path)
        self._header = existing
        self._notes = existing.notes
        self._snapshot = _snapshot(self._path)

    @property
    def path(self) -> Path:
        """The sidecar file path; may not exist until the first :meth:`save`."""
        return self._path

    @property
    def notes(self) -> tuple[Note, ...]:
        """The current notes, indexed ``1..N``."""
        return self._notes

    def append(self, text: str, now: datetime) -> None:
        """Add a note stamped with the current wall clock.

        :param text: The note body.
        :param now: The authoring timestamp (injected so tests are deterministic).
        """
        self._notes = self._notes + (Note(len(self._notes) + 1, now, text),)

    def edit(self, index: int, text: str) -> None:
        """Replace a note's text, keeping its timestamp.

        :param index: 1-based note index.
        :param text: The replacement body.
        :raises IndexError: If ``index`` is out of range.
        """
        self._require(index)
        self._notes = tuple(
            replace(n, text=text) if n.index == index else n for n in self._notes
        )

    def delete(self, index: int) -> None:
        """Delete a note and renumber the rest.

        :param index: 1-based note index.
        :raises IndexError: If ``index`` is out of range.
        """
        self._require(index)
        self._notes = renumber(tuple(n for n in self._notes if n.index != index))

    def save(self) -> None:
        """Write the notes atomically, refusing to clobber a newer file.

        :raises NotesConflict: If the file changed on disk since it was loaded.
        :raises OSError: If the directory is not writable.
        """
        if self._stale():
            raise NotesConflict(
                f"{self._path} changed on disk since it was loaded; reload before saving"
            )
        text = render_notes(
            NotesFile(
                experiment=self._header.experiment,
                subject=self._header.subject,
                user=self._header.user,
                start=self._header.start,
                stop=self._header.stop,
                notes=self._notes,
                warnings=(),
            )
        )
        write_text_atomic(self._path, text)
        self._snapshot = _snapshot(self._path)

    def _stale(self) -> bool:
        """Whether the on-disk file has moved on from the loaded snapshot.

        Compares mtime, size, and content digest rather than mtime alone: two
        writes in quick succession can share a filesystem timestamp tick, and
        relying on mtime only would let a same-tick clobber through undetected.
        """
        exists = self._path.is_file()
        if not exists:
            return False  # nothing to clobber
        if self._snapshot is None:
            return True  # appeared after we started with no file
        return _snapshot(self._path) != self._snapshot

    def _require(self, index: int) -> None:
        """Raise if ``index`` is not a current note index."""
        if not any(n.index == index for n in self._notes):
            raise IndexError(f"no note with index {index}")
