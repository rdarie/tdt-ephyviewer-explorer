"""Hydra configuration loading for tdt-explore."""
from __future__ import annotations

from pathlib import Path

from hydra import compose, initialize_config_dir
from hydra.core.global_hydra import GlobalHydra
from omegaconf import DictConfig

CONFIG_DIR: Path = Path(__file__).parent / "config"


def load_config(overrides: list[str] | None = None) -> DictConfig:
    """Compose the packaged Hydra config.

    :param overrides: Hydra dotlist overrides (e.g. ``["viewers.trace.antialias=false"]``).
    :returns: The composed configuration.
    """
    GlobalHydra.instance().clear()
    with initialize_config_dir(version_base=None, config_dir=str(CONFIG_DIR)):
        return compose(config_name="config", overrides=overrides or [])
