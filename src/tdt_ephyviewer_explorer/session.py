"""Per-tank session persistence (composition state only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from omegaconf import OmegaConf


@dataclass
class Session:
    """A saved composition: which viewers are attached to which stores.

    :param block: Block directory name.
    :param attachments: Store name -> list of serialized attachment dicts.
    """

    block: str
    attachments: dict[str, list[dict]] = field(default_factory=dict)


def save_session(session: Session, tank_dir: Path, name: str) -> Path:
    """Write a session to ``<tank>/tdt_explore/sessions/<name>.yaml``.

    :param session: The session to persist.
    :param tank_dir: Tank directory (raw block dirs are never written to).
    :param name: Session file stem.
    :returns: The written file path.
    """
    out_dir = tank_dir / "tdt_explore" / "sessions"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}.yaml"
    OmegaConf.save(config=OmegaConf.create(asdict(session)), f=out)
    return out


def load_session(path: Path) -> Session:
    """Load a session YAML written by :func:`save_session`."""
    cfg = OmegaConf.load(path)
    container = OmegaConf.to_container(cfg, resolve=True)
    assert isinstance(container, dict)
    return Session(block=container["block"], attachments=container["attachments"])
