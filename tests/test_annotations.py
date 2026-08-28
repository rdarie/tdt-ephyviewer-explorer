"""Qt-free tests for the epoch-encoder annotation logic."""
from pathlib import Path

import pytest

pytest.importorskip("ephyviewer")

from ephyviewer import CsvEpochSource

from tdt_ephyviewer_explorer.annotations import (
    DEFAULT_CHANNEL_NAME,
    annotations_csv_path,
    build_annotation_source,
    load_labels,
    resolve_labels_path,
)
from tdt_ephyviewer_explorer.config_schema import CONFIG_DIR, load_config


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_load_labels_valid_list(tmp_path: Path) -> None:
    p = _write(tmp_path / "l.yaml", "- a\n- b\n")
    assert load_labels(p) == ["a", "b"]


def test_load_labels_rejects_mapping(tmp_path: Path) -> None:
    p = _write(tmp_path / "m.yaml", "k: v\n")
    with pytest.raises(ValueError):
        load_labels(p)


def test_load_labels_rejects_non_string_entries(tmp_path: Path) -> None:
    p = _write(tmp_path / "n.yaml", "- a\n- 3\n")
    with pytest.raises(ValueError):
        load_labels(p)


def test_resolve_labels_path_relative_against_config_dir() -> None:
    cfg = load_config()
    resolved = resolve_labels_path(cfg)
    assert resolved == (CONFIG_DIR / "annotations/labels.yaml").resolve()
    assert resolved.is_absolute()


def test_resolve_labels_path_absolute_unchanged(tmp_path: Path) -> None:
    cfg = load_config()
    abs_path = tmp_path / "custom.yaml"
    assert resolve_labels_path(cfg, abs_path) == abs_path


def test_annotations_csv_path(tmp_path: Path) -> None:
    cfg = load_config()
    block = tmp_path / "blk"
    assert annotations_csv_path(block, cfg) == block / "tdt_explore" / "annotations.csv"


def test_build_annotation_source_creates_empty_csv(tmp_path: Path) -> None:
    cfg = load_config()
    block = tmp_path / "blk"
    block.mkdir()
    labels = resolve_labels_path(cfg)
    src = build_annotation_source(block, labels, cfg)
    csv = annotations_csv_path(block, cfg)
    assert isinstance(src, CsvEpochSource)
    assert csv.exists()
    assert csv.read_text().splitlines()[0] == "time,duration,label"


def test_build_annotation_source_second_call_does_not_clobber(tmp_path: Path) -> None:
    cfg = load_config()
    block = tmp_path / "blk"
    block.mkdir()
    labels = resolve_labels_path(cfg)
    src = build_annotation_source(block, labels, cfg)
    src.add_epoch(1.0, 2.0, "exclude_from_analysis")
    src.save()
    # A fresh source over the same CSV must load the saved epoch.
    reloaded = build_annotation_source(block, labels, cfg)
    # WritableEpochSource.get_chunk (single-channel) returns a
    # (times, durations, labels, ids) tuple, not a dict-like row.
    _times, _durations, ep_labels, _ids = reloaded.get_chunk(chan=0)
    assert list(ep_labels) == ["exclude_from_analysis"]


def test_default_channel_name() -> None:
    assert DEFAULT_CHANNEL_NAME == "annotations"
