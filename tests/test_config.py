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
