"""Writable epoch-encoder annotations for launched blocks (Qt-free).

Mirrors :mod:`impedance` — all data logic here is unit-testable headless.
ephyviewer's :class:`CsvEpochSource` and :class:`EpochEncoder` provide the
machinery; this module only resolves paths, loads the possible-labels list, and
builds the source. The only block-dir write is the annotations CSV under
``<block>/tdt_explore/``; raw Synapse files are never touched.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ephyviewer import CsvEpochSource
from omegaconf import OmegaConf

from tdt_ephyviewer_explorer.config_schema import CONFIG_DIR
from tdt_ephyviewer_explorer.metadata.notes import BLOCK_SUBDIR

DEFAULT_CHANNEL_NAME = "annotations"


def load_labels(path: Path) -> list[str]:
    """Load the possible-labels YAML list.

    :param path: A YAML file whose top level is a non-empty list of strings.
    :returns: The label strings, in file order.
    :raises ValueError: If the file is not a list, is empty, or has a
        non-string entry.
    """
    data = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    if (
        not isinstance(data, list)
        or not data
        or not all(isinstance(x, str) for x in data)
    ):
        raise ValueError(
            f"labels file {path} must be a non-empty YAML list of strings, got {data!r}"
        )
    return list(data)


def resolve_labels_path(cfg: Any, path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve a possible-labels file path.

    Uses ``path`` when given (a session-carried value), else
    ``cfg.annotations.labels_path``. Absolute paths are returned as-is; a relative
    path is resolved against :data:`config_schema.CONFIG_DIR`, so the shipped
    default is found without any hardcoded absolute path.

    :param cfg: Composed config (uses ``cfg.annotations.labels_path`` as fallback).
    :param path: An explicit path override, or ``None`` to use the config default.
    :returns: An absolute path to the labels file.
    """
    raw = Path(path) if path else Path(str(cfg.annotations.labels_path))
    if raw.is_absolute():
        return raw
    return (CONFIG_DIR / raw).resolve()


def annotations_csv_path(block_path: Path, cfg: Any) -> Path:
    """Return the per-block annotations CSV path.

    :param block_path: Block directory.
    :param cfg: Composed config (uses ``cfg.annotations.filename``).
    :returns: ``<block>/tdt_explore/<filename>``.
    """
    return block_path / BLOCK_SUBDIR / str(cfg.annotations.filename)


def build_annotation_source(
    block_path: Path, labels_path: Path, cfg: Any
) -> CsvEpochSource:
    """Build the writable epoch source for a block, creating the CSV if absent.

    Resolves the CSV path under ``<block>/tdt_explore/``, ensures the subfolder
    exists, and builds a :class:`CsvEpochSource` with the possible labels loaded
    from ``labels_path``. When the CSV does not yet exist it is created empty via
    ``source.save()`` so first launch leaves a valid ``time,duration,label`` file.

    :param block_path: Block directory.
    :param labels_path: Resolved possible-labels YAML file.
    :param cfg: Composed config (uses ``cfg.annotations.restrict_to_possible_labels``).
    :returns: The writable epoch source.
    """
    csv = annotations_csv_path(block_path, cfg)
    csv.parent.mkdir(parents=True, exist_ok=True)
    existed = csv.exists()
    source = CsvEpochSource(
        str(csv),
        possible_labels=load_labels(labels_path),
        channel_name=DEFAULT_CHANNEL_NAME,
        restrict_to_possible_labels=bool(cfg.annotations.restrict_to_possible_labels),
    )
    if not existed:
        source.save()  # write an empty time,duration,label CSV
    return source
