"""Pulse and parameter-combination summaries for eStim parameter stores."""
from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from tdt_ephyviewer_explorer.stores import _get, load_store


class StimSchemaMismatch(ValueError):
    """Raised when a stim store's row count does not match its configured schema."""


@dataclass(frozen=True)
class VoiceSummary:
    """Parameters delivered by one active voice of a stim parameter store.

    :param voice: Voice suffix, e.g. ``"A"``.
    :param channels: Distinct channels stimulated, ascending.
    :param amp_min: Smallest amplitude *magnitude* delivered, in the configured units.
    :param amp_max: Largest amplitude magnitude delivered.
    :param amp_sign: ``"-"`` if every delivered amplitude was negative, ``"+"`` if
        every one was positive, ``"±"`` if both polarities appear, ``""`` if the
        schema names no amplitude column for this voice.
    :param freq_min_hz: Lowest within-train pulse frequency in Hz, or ``None`` when no
        event carried a positive period.
    :param freq_max_hz: Highest within-train pulse frequency in Hz, or ``None``.
    """

    voice: str
    channels: tuple[int, ...]
    amp_min: float
    amp_max: float
    amp_sign: str
    freq_min_hz: float | None
    freq_max_hz: float | None


@dataclass(frozen=True)
class StimSummary:
    """Headline stimulation figures for one parameter store.

    :param store: Store code, e.g. ``"eS1p"``.
    :param n_pulses: Total pulses delivered.
    :param n_combinations: Distinct parameter settings used.
    :param voices: One entry per active voice, in configured voice order.
    """

    store: str
    n_pulses: int
    n_combinations: int
    voices: tuple[VoiceSummary, ...] = ()


@dataclass(frozen=True)
class StimConfig:
    """Resolved ``metadata.stim`` settings.

    :param store_pattern: fnmatch pattern selecting parameter stores.
    :param schema: Name of the column schema in ``schemas``.
    :param voices: Voice suffixes appended to each parameter name.
    :param chan_prefix: Column prefix whose value marks a voice wired when ``> 0``.
    :param count_prefix: Column prefix giving pulses per train.
    :param amp_prefix: Column prefix giving amplitude; ``!= 0`` marks charge delivered.
    :param per_prefix: Column prefix giving the within-train interval.
    :param per_to_hz: Numerator of ``freq_Hz = per_to_hz / per``.
    :param amp_units: Amplitude unit label, for display only.
    :param max_channels_listed: Channel tokens shown before the list truncates.
    """

    store_pattern: str
    schema: str
    voices: tuple[str, ...]
    chan_prefix: str
    count_prefix: str
    amp_prefix: str
    per_prefix: str
    per_to_hz: float
    amp_units: str
    max_channels_listed: int


def stim_config_from(cfg: Any) -> tuple[StimConfig, list[str]]:
    """Extract the stim settings and their column names from a composed config.

    :param cfg: The composed Hydra config.
    :returns: The settings, and the ordered column names of the named schema.
    :raises KeyError: If the configured schema is not defined in ``schemas``.
    """
    node = cfg.metadata.stim
    schema = str(node.schema)
    columns = [str(c) for c in cfg.schemas[schema]]
    return (
        StimConfig(
            store_pattern=str(node.store_pattern),
            schema=schema,
            voices=tuple(str(v) for v in node.voices),
            chan_prefix=str(node.chan_prefix),
            count_prefix=str(node.count_prefix),
            amp_prefix=str(node.amp_prefix),
            per_prefix=str(node.per_prefix),
            per_to_hz=float(node.per_to_hz),
            amp_units=str(node.amp_units),
            max_channels_listed=int(node.max_channels_listed),
        ),
        columns,
    )


def format_channels(channels: Sequence[int], max_listed: int) -> str:
    """Render a channel set compactly, collapsing runs and capping the width.

    Runs of three or more consecutive channels become ``a–b`` tokens; shorter runs
    stay as individual numbers. Past ``max_listed`` tokens the list truncates with an
    ellipsis. A ``(N ch)`` suffix carries the distinct channel count whenever the text
    alone does not state it -- that is, when the list truncated or rendered as a
    single range.

    :param channels: Distinct channels, ascending.
    :param max_listed: Tokens to show before truncating.
    :returns: The rendered list, or ``""`` for no channels.
    """
    if not channels:
        return ""
    ordered = sorted(channels)
    tokens: list[str] = []
    start = prev = ordered[0]
    for value in list(ordered[1:]) + [None]:
        if value is not None and value == prev + 1:
            prev = value
            continue
        if prev - start >= 2:
            tokens.append(f"{start}–{prev}")
        else:
            tokens.extend(str(x) for x in range(start, prev + 1))
        if value is not None:
            start = prev = value

    truncated = len(tokens) > max_listed
    shown = tokens[:max(0, max_listed)]
    text = ",".join(shown)
    if truncated:
        if text:
            text += ",…"
        else:
            text = "…"
    lone_range = len(tokens) == 1 and "–" in tokens[0]
    if truncated or lone_range:
        text = f"{text} ({len(ordered)} ch)"
    return text


def _number(value: float) -> str:
    """Render one figure to a single decimal, dropping a trailing ``.0``.

    :param value: The figure.
    :returns: Its rendering, e.g. ``"20"`` or ``"12.5"``.
    """
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_range(lo: float, hi: float, unit: str, sign: str = "") -> str:
    """Render a range, collapsing it when both bounds agree.

    ``sign`` prefixes the whole range rather than each bound: ``-100–800 µA`` reads
    where ``-800–-100 µA`` does not.

    :param lo: Lower bound.
    :param hi: Upper bound.
    :param unit: Unit label appended after a space.
    :param sign: Polarity marker prefixed to the range, if any.
    :returns: The rendered range.
    """
    low, high = _number(lo), _number(hi)
    body = low if low == high else f"{low}–{high}"
    return f"{sign}{body} {unit}".strip()


def format_voice_line(voice: VoiceSummary, settings: StimConfig) -> str:
    """Render one voice's parameters as a single display line.

    Clauses the data could not supply are omitted rather than shown empty.

    :param voice: The per-voice summary.
    :param settings: Resolved stim settings, for the unit label and channel cap.
    :returns: e.g. ``"ch 1–8 · -100–800 µA · 10–50 Hz"``.
    """
    parts: list[str] = []
    if voice.channels:
        parts.append(f"ch {format_channels(voice.channels, settings.max_channels_listed)}")
    if voice.amp_sign:
        parts.append(
            format_range(voice.amp_min, voice.amp_max, settings.amp_units, voice.amp_sign)
        )
    if voice.freq_min_hz is not None and voice.freq_max_hz is not None:
        parts.append(format_range(voice.freq_min_hz, voice.freq_max_hz, "Hz"))
    return " · ".join(parts)


def schema_warnings(column_names: Sequence[str], settings: StimConfig) -> list[str]:
    """Report voices whose schema cannot supply a parameter this summary reports.

    The schema is the same for every store in a block, so this is checked once rather
    than per store. A missing amplitude column also weakens the activity test for that
    voice, which is why it is worth saying out loud.

    :param column_names: The named schema's column order.
    :param settings: Resolved stim settings.
    :returns: One warning per missing column, empty when the schema is complete.
    """
    present = set(column_names)
    out: list[str] = []
    for voice in settings.voices:
        if f"{settings.chan_prefix}{voice}" not in present:
            continue
        for prefix, reported in (
            (settings.amp_prefix, "amplitude"),
            (settings.per_prefix, "frequency"),
        ):
            column = f"{prefix}{voice}"
            if column not in present:
                out.append(
                    f"schema {settings.schema!r} has no {column}: "
                    f"voice {voice} reports no {reported}"
                )
    return out


def _voice_mask(
    data: np.ndarray, index: dict[str, int], voice: str, settings: StimConfig
) -> np.ndarray:
    """The per-event boolean mask of when one voice is delivering charge.

    ``chan == 0`` is Synapse's dummy value for "no stimulation" and ``amp == 0`` is a
    voice configured but delivering nothing. Amplitudes are negative for cathodic
    pulses, so the amplitude test is ``!= 0``. A schema without the voice's amplitude
    column degrades to the channel test alone.

    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param index: Column name to row number.
    :param voice: Voice suffix.
    :param settings: Resolved stim settings.
    :returns: Boolean array of length ``n_events``.
    """
    on = data[index[f"{settings.chan_prefix}{voice}"]] > 0
    amp_key = f"{settings.amp_prefix}{voice}"
    if amp_key in index:
        on = on & (data[index[amp_key]] != 0)
    return on


def _summarize_voice(
    voice: str,
    data: np.ndarray,
    index: dict[str, int],
    on: np.ndarray,
    settings: StimConfig,
) -> VoiceSummary:
    """Reduce one active voice's on-events to channels and parameter ranges.

    Every figure covers the on-events only; including the events where the voice is
    idle would pin each minimum to zero.

    :param voice: Voice suffix.
    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param index: Column name to row number.
    :param on: The voice's per-event mask, from :func:`_voice_mask`.
    :param settings: Resolved stim settings.
    :returns: The per-voice summary.
    """
    channels = tuple(
        int(c) for c in np.unique(data[index[f"{settings.chan_prefix}{voice}"]][on])
    )

    amp_min = amp_max = 0.0
    amp_sign = ""
    amp_key = f"{settings.amp_prefix}{voice}"
    if amp_key in index:
        amps = data[index[amp_key]][on]
        amps = amps[amps != 0]
        if amps.size:
            magnitudes = np.abs(amps)
            amp_min, amp_max = float(magnitudes.min()), float(magnitudes.max())
            negative, positive = bool((amps < 0).any()), bool((amps > 0).any())
            amp_sign = "±" if negative and positive else ("-" if negative else "+")

    freq_min: float | None = None
    freq_max: float | None = None
    per_key = f"{settings.per_prefix}{voice}"
    if per_key in index:
        periods = data[index[per_key]][on]
        periods = periods[periods > 0]
        if periods.size:
            frequencies = settings.per_to_hz / periods
            freq_min, freq_max = float(frequencies.min()), float(frequencies.max())

    return VoiceSummary(voice, channels, amp_min, amp_max, amp_sign, freq_min, freq_max)


def summarize_stim(
    store: str,
    data: np.ndarray,
    column_names: Sequence[str],
    settings: StimConfig,
) -> StimSummary:
    """Reduce a stim parameter block to headline figures and per-voice ranges.

    A voice is *active* when it delivers charge -- ``chan > 0`` and ``amp != 0`` -- for
    at least one event. Only active voices' columns take part, so an idle voice whose
    other parameters happen to vary cannot inflate the combination count, and a return
    electrode held at zero amplitude is not counted as stimulation.

    Pulses per event are the **maximum** ``count`` across that event's on voices, not
    the sum: voices fire concurrently, so a 3-pulse train on two voices is three pulses
    in time.

    :param store: Store code, carried into the result.
    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param column_names: Row labels, one per row of ``data``.
    :param settings: Resolved stim settings.
    :returns: The summary.
    :raises StimSchemaMismatch: If ``data`` has a different row count than
        ``column_names`` -- labelling the rows anyway would silently mis-report.
    """
    if data.shape[0] != len(column_names):
        raise StimSchemaMismatch(
            f"{store}: {data.shape[0]} rows but schema names {len(column_names)} columns"
        )
    index = {name: i for i, name in enumerate(column_names)}
    n_events = int(data.shape[1])

    masks: dict[str, np.ndarray] = {}
    for voice in settings.voices:
        if f"{settings.chan_prefix}{voice}" not in index:
            continue
        on = _voice_mask(data, index, voice, settings)
        if bool(on.any()):
            masks[voice] = on
    if not masks or n_events == 0:
        return StimSummary(store, 0, 0)

    any_on = np.zeros(n_events, dtype=bool)
    for on in masks.values():
        any_on |= on
    combo_rows = [i for name, i in index.items() if any(name.endswith(v) for v in masks)]
    block = data[np.ix_(combo_rows, np.flatnonzero(any_on))]
    n_combinations = int(np.unique(block.T, axis=0).shape[0])

    per_event = np.zeros(n_events, dtype=float)
    for voice, on in masks.items():
        count_key = f"{settings.count_prefix}{voice}"
        if count_key not in index:
            continue
        per_event = np.maximum(per_event, np.where(on, data[index[count_key]], 0.0))
    voices = tuple(
        _summarize_voice(voice, data, index, masks[voice], settings)
        for voice in settings.voices
        if voice in masks
    )
    return StimSummary(store, int(per_event.sum()), n_combinations, voices)


def read_stim_summaries(
    block_path: Path, cfg: Any, headers: Any | None = None
) -> tuple[list[StimSummary], list[str]]:
    """Load every stim parameter store in a block and summarize each.

    :param block_path: Path to the block directory.
    :param cfg: The composed Hydra config.
    :param headers: Pre-parsed ``.tsq`` headers to reuse; ``None`` parses them.
    :returns: The summaries, and any warnings raised while producing them.
    :raises KeyError: If the configured schema is not defined in ``schemas``.
    """
    settings, columns = stim_config_from(cfg)
    summaries: list[StimSummary] = []
    warnings: list[str] = schema_warnings(columns, settings)
    if headers is None:
        return summaries, ["stim summary skipped: block index not parsed"]

    names = [n for n in headers["stores"].keys() if fnmatchcase(n, settings.store_pattern)]
    for name in names:
        try:
            store = load_store(block_path, name, headers=headers)
            data = np.atleast_2d(np.asarray(_get(store, "data"), dtype=float))
            summaries.append(summarize_stim(name, data, columns, settings))
        except StimSchemaMismatch as exc:
            warnings.append(str(exc))
        except (KeyError, OSError, ValueError) as exc:
            warnings.append(f"{name}: could not read stim parameters ({exc})")
    return summaries, warnings
