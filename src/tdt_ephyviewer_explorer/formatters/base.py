"""Formatter protocol and a generic column-listing formatter."""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@runtime_checkable
class StimFormatter(Protocol):
    """Turns one stim/event parameter row into a display label."""

    def format_row(self, row: Mapping[str, Any]) -> str:
        """Return the label string for ``row``."""
        ...


class GenericFormatter:
    """Lists ``name: value`` for each configured column, one per line."""

    def __init__(self, columns: Sequence[str]) -> None:
        """:param columns: Column names to render, in order."""
        self._columns = list(columns)

    def format_row(self, row: Mapping[str, Any]) -> str:
        return "\n".join(f"{c}: {row[c]}" for c in self._columns)
