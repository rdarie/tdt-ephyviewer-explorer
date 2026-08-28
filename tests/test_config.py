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


def test_load_config_has_impedance_group() -> None:
    cfg = load_config()
    assert cfg.impedance.auto_scan is True
    assert list(cfg.impedance.globs) == ["*.csv"]
    assert cfg.impedance.frequency_column == "FREQUENCY (Hz)"
    assert cfg.impedance.min_channels == 4


def test_load_config_has_impedance_viewer_defaults() -> None:
    cfg = load_config()
    assert cfg.viewers.impedance.vmin == 0.0
    assert cfg.viewers.impedance.vmax == 200.0
    assert cfg.viewers.impedance.annotate is True
    assert cfg.viewers.impedance.annotation_format == "R{channel}\n{impedance:.0f}"
    assert cfg.viewers.impedance.cmap == "viridis"


def test_impedance_channel_regex_matches_rig_headers() -> None:
    # The rig writes "R1 (kOhm)" ... "R64 (kOhm)"; TIME/FREQUENCY/TARGET/REF are metadata.
    import re

    rx = re.compile(load_config().impedance.channel_regex)
    match = rx.match("R12 (kOhm)")
    assert match is not None
    assert match.group(1) == "12"
    assert match.group(2) == "kOhm"
    assert rx.match("REF (kOhm)") is None
    assert rx.match("TIME (S)") is None
    assert rx.match("TARGET (uA)") is None


def test_config_has_annotations_group() -> None:
    cfg = load_config()
    assert cfg.annotations.labels_path == "annotations/labels.yaml"
    assert cfg.annotations.filename == "annotations.csv"
    assert cfg.annotations.restrict_to_possible_labels is False


def test_config_has_epochencoder_viewer_defaults() -> None:
    cfg = load_config()
    assert "epochencoder" in cfg.viewers
