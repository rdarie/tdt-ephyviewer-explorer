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
class StimSummary:
    """Headline stimulation figures for one parameter store.

    :param store: Store code, e.g. ``"eS1p"``.
    :param n_pulses: Total pulses delivered.
    :param n_combinations: Distinct parameter settings used.
    """

    store: str
    n_pulses: int
    n_combinations: int


@dataclass(frozen=True)
class StimConfig:
    """Resolved ``metadata.stim`` settings.

    :param store_pattern: fnmatch pattern selecting parameter stores.
    :param schema: Name of the column schema in ``schemas``.
    :param voices: Voice suffixes appended to each parameter name.
    :param chan_prefix: Column prefix whose value marks a voice active when ``> 0``.
    :param count_prefix: Column prefix giving pulses per train.
    """

    store_pattern: str
    schema: str
    voices: tuple[str, ...]
    chan_prefix: str
    count_prefix: str


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
        ),
        columns,
    )


def summarize_stim(
    store: str,
    data: np.ndarray,
    column_names: Sequence[str],
    voices: Sequence[str],
    chan_prefix: str,
    count_prefix: str,
) -> StimSummary:
    """Reduce a stim parameter block to a pulse count and a combination count.

    A voice is *active* when its ``chan`` column exceeds zero for at least one event
    (``chan == 0`` is Synapse's dummy value for "no stimulation"). Only active
    voices' columns take part, so an idle voice whose other parameters happen to
    vary cannot inflate the combination count.

    Pulses per event are the **maximum** ``count`` across that event's active voices,
    not the sum: voices fire concurrently, so a 3-pulse train on two voices is three
    pulses in time.

    :param store: Store code, carried into the result.
    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param column_names: Row labels, one per row of ``data``.
    :param voices: Voice suffixes to consider.
    :param chan_prefix: Prefix of the channel column.
    :param count_prefix: Prefix of the pulses-per-train column.
    :returns: The summary.
    :raises StimSchemaMismatch: If ``data`` has a different row count than
        ``column_names`` — labelling the rows anyway would silently mis-report.
    """
    if data.shape[0] != len(column_names):
        raise StimSchemaMismatch(
            f"{store}: {data.shape[0]} rows but schema names {len(column_names)} columns"
        )
    index = {name: i for i, name in enumerate(column_names)}
    n_events = int(data.shape[1])

    active = [
        v for v in voices
        if f"{chan_prefix}{v}" in index and bool((data[index[f"{chan_prefix}{v}"]] > 0).any())
    ]
    if not active or n_events == 0:
        return StimSummary(store, 0, 0)

    combo_rows = [i for name, i in index.items() if any(name.endswith(v) for v in active)]
    n_combinations = int(np.unique(data[combo_rows].T, axis=0).shape[0])

    per_event = np.zeros(n_events, dtype=float)
    for v in active:
        channel = data[index[f"{chan_prefix}{v}"]]
        count = data[index[f"{count_prefix}{v}"]]
        per_event = np.maximum(per_event, np.where(channel > 0, count, 0.0))
    return StimSummary(store, int(per_event.sum()), n_combinations)


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
    warnings: list[str] = []
    if headers is None:
        return summaries, ["stim summary skipped: block index not parsed"]

    names = [n for n in headers["stores"].keys() if fnmatchcase(n, settings.store_pattern)]
    for name in names:
        try:
            store = load_store(block_path, name, headers=headers)
            data = np.atleast_2d(np.asarray(_get(store, "data"), dtype=float))
            summaries.append(
                summarize_stim(
                    name, data, columns, settings.voices,
                    settings.chan_prefix, settings.count_prefix,
                )
            )
        except StimSchemaMismatch as exc:
            warnings.append(str(exc))
        except (KeyError, OSError, ValueError) as exc:
            warnings.append(f"{name}: could not read stim parameters ({exc})")
    return summaries, warnings
