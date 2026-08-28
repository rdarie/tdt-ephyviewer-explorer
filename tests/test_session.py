"""Tests for session save/load."""
from pathlib import Path

from tdt_ephyviewer_explorer.session import (
    ImpedanceSource,
    ProcessedSource,
    Session,
    load_session,
    save_session,
)


def test_session_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        attachments={
            "Wav1": [{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}],
            "eS1p": [{"viewer_type": "eventlist", "delay_ms": 20.0, "probe_path": None, "params": {}}],
        },
    )
    out = save_session(session, tmp_path, "mysession")
    assert out == tmp_path / "tdt_explore" / "sessions" / "mysession.yaml"
    assert out.exists()
    loaded = load_session(out)
    assert loaded == session


def test_session_processed_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        attachments={"Wav1": [{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}]},
        processed=[
            ProcessedSource(
                path="torpedo/preprocessed/rRew03-1/raw_data_mep.parquet",
                kind="timeseries",
                name="raw_data_mep",
                attachments=[{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}],
            )
        ],
    )
    out = save_session(session, tmp_path, "s")
    loaded = load_session(out)
    assert loaded == session
    assert isinstance(loaded.processed[0], ProcessedSource)


def test_session_defaults_empty_processed() -> None:
    assert Session(block="b").processed == []


def test_session_impedance_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        impedance=[
            ImpedanceSource(
                path="Epi_02_Green/spinal.csv",
                name="spinal",
                attachments=[{
                    "viewer_type": "impedance",
                    "delay_ms": 0.0,
                    "probe_path": "probes/tdt_64ch.json",
                    "params": {"vmax": 300.0},
                }],
            )
        ],
    )
    out = save_session(session, tmp_path, "imp")
    loaded = load_session(out)
    assert loaded == session
    assert isinstance(loaded.impedance[0], ImpedanceSource)


def test_session_defaults_empty_impedance() -> None:
    assert Session(block="b").impedance == []


def test_load_session_without_impedance_key(tmp_path: Path) -> None:
    # Sessions written before this feature have no 'impedance' key and must still load.
    path = tmp_path / "old.yaml"
    path.write_text(
        "block: rRew03-1\n"
        "attachments:\n"
        "  Wav1:\n"
        "  - viewer_type: trace\n"
        "    delay_ms: 0.0\n"
        "    probe_path: null\n"
        "    params: {}\n"
        "processed: []\n"
    )
    loaded = load_session(path)
    assert loaded.impedance == []
    assert loaded.block == "rRew03-1"


def test_session_annotations_labels_path_round_trip(tmp_path: Path) -> None:
    session = Session(
        block="rRew03-1",
        attachments={"Wav1": [{"viewer_type": "trace", "delay_ms": 0.0, "probe_path": None, "params": {}}]},
        annotations_labels_path="/abs/labels.yaml",
    )
    out = save_session(session, tmp_path, "ann")
    loaded = load_session(out)
    assert loaded == session
    assert loaded.annotations_labels_path == "/abs/labels.yaml"


def test_session_default_annotations_labels_path_is_none() -> None:
    assert Session(block="b").annotations_labels_path is None


def test_load_session_without_annotations_key(tmp_path: Path) -> None:
    # Sessions written before this feature have no key and must still load.
    path = tmp_path / "old.yaml"
    path.write_text(
        "block: rRew03-1\n"
        "attachments: {}\n"
        "processed: []\n"
        "impedance: []\n"
    )
    loaded = load_session(path)
    assert loaded.annotations_labels_path is None
