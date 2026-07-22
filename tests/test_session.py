"""Tests for session save/load."""
from pathlib import Path

from tdt_ephyviewer_explorer.session import Session, load_session, save_session


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
