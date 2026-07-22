"""Tests for the control-tree spec and window."""
from tdt_ephyviewer_explorer.control_window import build_param_tree_spec
from tdt_ephyviewer_explorer.stores import ResolvedStore, StoreInfo


def _resolved(name: str, role: str, viewers: tuple[str, ...]) -> ResolvedStore:
    info = StoreInfo(name, "streams", 1000.0, 4, None, 0.0, None)
    return ResolvedStore(info, role, None, viewers, None)


def test_build_param_tree_spec_makes_group_per_store() -> None:
    spec = build_param_tree_spec(
        [_resolved("Wav1", "timeseries", ("trace", "timefreq"))], {"trace": {}, "timefreq": {}}
    )
    assert spec[0]["name"] == "Wav1"
    child_names = {c["name"] for c in spec[0]["children"]}
    assert "delay_ms" in child_names
    assert "probe_file" in child_names  # timeseries only
    viewers_group = next(c for c in spec[0]["children"] if c["name"] == "Viewers")
    assert {c["name"] for c in viewers_group["children"]} == {"trace", "timefreq"}


def test_build_param_tree_spec_omits_probe_for_events() -> None:
    spec = build_param_tree_spec(
        [_resolved("eS1p", "stim", ("eventlist",))], {"eventlist": {}}
    )
    child_names = {c["name"] for c in spec[0]["children"]}
    assert "probe_file" not in child_names


import pytest

ephyviewer = pytest.importorskip("ephyviewer")


def test_spec_to_session_includes_only_enabled() -> None:
    from tdt_ephyviewer_explorer.control_window import spec_to_session

    state = {
        "Wav1": {
            "delay_ms": 5.0,
            "probe_file": "",
            "reorder": False,
            "Viewers": {"trace": {"_enabled": True, "display_labels": True},
                        "timefreq": {"_enabled": False}},
        }
    }
    session = spec_to_session("blk", state)
    assert list(session.attachments) == ["Wav1"]
    assert session.attachments["Wav1"][0]["viewer_type"] == "trace"
    assert session.attachments["Wav1"][0]["delay_ms"] == 5.0
