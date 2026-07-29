"""Tests for Hydra config loading."""
from tdt_ephyviewer_explorer.config_schema import load_config


def test_load_config_has_expected_groups() -> None:
    cfg = load_config()
    assert "trace" in cfg.viewers
    assert cfg.viewers.trace.scale_mode == "real_scale"
    assert any(r.role == "stim" for r in cfg.roles)
    assert len(cfg.schemas.iz_param_names) == 24


def test_load_config_has_startup_defaults() -> None:
    cfg = load_config()
    assert cfg.startup.auto_scale is True
    assert cfg.startup.trace_color_scheme == "Accent"


def test_load_config_has_processed_group() -> None:
    cfg = load_config()
    assert cfg.processed.preprocessed_subpath == "torpedo/preprocessed"
    assert cfg.processed.auto_scan is True
    assert cfg.processed.default_sampling_rate == 24414.0625
    assert list(cfg.processed.time_column_candidates) == ["timestamp"]
    assert cfg.processed.default_label_column == "stim_site"
    assert list(cfg.processed.ignore_globs) == []


def test_metadata_group_is_composed() -> None:
    from tdt_ephyviewer_explorer.config_schema import load_config

    cfg = load_config()
    assert cfg.metadata.analysis_notes_filename == "analysis_notes.txt"
    assert cfg.metadata.stim.schema == "iz_param_names"
