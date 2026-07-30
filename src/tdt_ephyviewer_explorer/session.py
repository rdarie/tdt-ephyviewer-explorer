"""Per-tank session persistence (composition state only)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from omegaconf import OmegaConf


@dataclass
class ProcessedSource:
    """A processed-parquet source composed into a session.

    :param path: Stored path (tank-relative when under the tank, else absolute).
    :param kind: ``"timeseries"`` or ``"event"``.
    :param name: Display / dock-prefix name.
    :param attachments: Serialized attachment dicts (same shape as TDT attachments).
    :param sampling_rate: Override used only for blob-less manually-added files.
    :param t_start: Override for blob-less files.
    :param time_column: Override for blob-less event files.
    :param time_units: Override for blob-less event files.
    :param label_column: Override for blob-less event files.
    """

    path: str
    kind: str
    name: str
    attachments: list[dict] = field(default_factory=list)
    sampling_rate: float | None = None
    t_start: float | None = None
    time_column: str | None = None
    time_units: str | None = None
    label_column: str | None = None


@dataclass
class ImpedanceSource:
    """An impedance CSV composed into a session.

    :param path: Stored path (tank-relative when under the tank, else absolute).
    :param name: Display / dock-prefix name.
    :param attachments: Serialized attachment dicts (same shape as TDT attachments).
    """

    path: str
    name: str
    attachments: list[dict] = field(default_factory=list)


@dataclass
class Session:
    """A saved composition: which viewers are attached to which stores.

    :param block: Block directory name.
    :param attachments: TDT store name -> list of serialized attachment dicts.
    :param processed: Processed-parquet sources composed into this session.
    :param impedance: Impedance CSV sidecars composed into this session.
    """

    block: str
    attachments: dict[str, list[dict]] = field(default_factory=dict)
    processed: list[ProcessedSource] = field(default_factory=list)
    impedance: list[ImpedanceSource] = field(default_factory=list)


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
    processed = [ProcessedSource(**ps) for ps in container.get("processed", [])]
    impedance = [ImpedanceSource(**i) for i in container.get("impedance", [])]
    return Session(
        block=container["block"],
        attachments=container["attachments"],
        processed=processed,
        impedance=impedance,
    )
