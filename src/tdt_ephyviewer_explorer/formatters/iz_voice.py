"""IZ multi-voice stim formatter (port of the reference chan_formatter)."""
from __future__ import annotations

from typing import Any, Mapping, Sequence


class IZVoiceFormatter:
    """Renders active A/B/C/D stim voices as ``chX: NN amp units`` lines."""

    def __init__(
        self, voices: Sequence[str] = ("A", "B", "C", "D"), amp_units: str = "uA"
    ) -> None:
        """:param voices: Voice suffixes to inspect.
        :param amp_units: Amplitude unit label."""
        self._voices = list(voices)
        self._amp_units = amp_units

    def format_row(self, row: Mapping[str, Any]) -> str:
        parts: list[str] = []
        for v in self._voices:
            ch = int(row[f"chan{v}"])
            if ch > 0:
                amp = row[f"amp{v}"]
                parts.append(f"ch{v}: {ch:0>2d} {amp} {self._amp_units}")
        return "\n".join(parts)
