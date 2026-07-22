"""Tests for stim-metadata label formatters."""
from tdt_ephyviewer_explorer.formatters.base import GenericFormatter
from tdt_ephyviewer_explorer.formatters.iz_voice import IZVoiceFormatter


def test_generic_formatter_lists_columns() -> None:
    fmt = GenericFormatter(["a", "b"])
    assert fmt.format_row({"a": 1, "b": 2}) == "a: 1\nb: 2"


def test_iz_voice_formatter_skips_inactive_channels() -> None:
    fmt = IZVoiceFormatter()
    row = {"chanA": 5, "ampA": 100, "chanB": 0, "ampB": 0,
           "chanC": 0, "ampC": 0, "chanD": 0, "ampD": 0}
    assert fmt.format_row(row) == "chA: 05 100 uA"
