"""The per-tank Control Window and its (pure) parameter-tree spec."""
from __future__ import annotations

from pathlib import Path

from omegaconf import DictConfig, OmegaConf
from pyqtgraph.parametertree import Parameter, ParameterTree
from PySide6 import QtWidgets
from PySide6.QtCore import Signal

from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import ResolvedStore, resolve_role, rules_from_config
from tdt_ephyviewer_explorer.tank import scan_block


def build_param_tree_spec(
    resolved_stores: list[ResolvedStore], viewer_defaults: dict
) -> list[dict]:
    """Build a pyqtgraph-parametertree spec: one group per store.

    :param resolved_stores: Stores with resolved roles.
    :param viewer_defaults: Per-viewer default params, seeded into viewer subgroups.
    :returns: A list of group-parameter dicts.
    """
    groups: list[dict] = []
    for rs in resolved_stores:
        children: list[dict] = [
            {"name": "role", "type": "str", "value": rs.role, "readonly": True},
            {"name": "fs", "type": "float", "value": rs.info.fs or 0.0, "readonly": True},
            {"name": "channels", "type": "int", "value": rs.info.n_channels or 0, "readonly": True},
            {"name": "delay_ms", "type": "float", "value": 0.0},
        ]
        if rs.role == "timeseries":
            children.append({"name": "probe_file", "type": "str", "value": ""})
            children.append({"name": "reorder", "type": "bool", "value": False})
        if rs.schema is not None:
            children.append(
                {"name": "schema", "type": "str", "value": rs.schema, "readonly": True}
            )
        viewer_children: list[dict] = [
            {"name": vt, "type": "bool", "value": False, "children": _params_children(
                viewer_defaults.get(vt, {})
            )}
            for vt in rs.viewers
        ]
        children.append({"name": "Viewers", "type": "group", "children": viewer_children})
        groups.append({"name": rs.info.name, "type": "group", "children": children})
    return groups


def _params_children(defaults: dict) -> list[dict]:
    """Turn a flat viewer-defaults dict into parametertree children."""
    out: list[dict] = []
    for key, value in defaults.items():
        ptype = {bool: "bool", int: "int", float: "float"}.get(type(value), "str")
        out.append({"name": key, "type": ptype, "value": value})
    return out


def spec_to_session(block: str, param_state: dict) -> Session:
    """Convert a saved parametertree state into a :class:`Session`.

    :param block: Block name.
    :param param_state: ``{store_name: {"delay_ms": float, "probe_file": str,
        "Viewers": {viewer_type: {"_enabled": bool, **params}}}}``.
    :returns: The composition session (only enabled viewers included).
    """
    attachments: dict[str, list[dict]] = {}
    for store_name, state in param_state.items():
        viewers = state.get("Viewers", {})
        entries: list[dict] = []
        probe = state.get("probe_file") or None
        for vt, vstate in viewers.items():
            if not vstate.get("_enabled"):
                continue
            params = {k: v for k, v in vstate.items() if k != "_enabled"}
            entries.append(
                {
                    "viewer_type": vt,
                    "delay_ms": float(state.get("delay_ms", 0.0)),
                    "probe_path": probe if state.get("reorder") else None,
                    "params": params,
                }
            )
        if entries:
            attachments[store_name] = entries
    return Session(block=block, attachments=attachments)


class ControlWindow(QtWidgets.QWidget):
    """Per-tank control window: pick a block, compose viewers, launch."""

    launch_requested = Signal(object)  # emits a Session

    def __init__(self, cfg: DictConfig | None = None, parent: QtWidgets.QWidget | None = None) -> None:
        """Initialize the control window with a parameter tree and launch button.

        :param cfg: Configuration (default: loaded from config schema).
        :param parent: Parent Qt widget.
        """
        super().__init__(parent)
        self._cfg = cfg if cfg is not None else load_config()
        self._rules = rules_from_config(self._cfg)
        self._viewer_defaults = OmegaConf.to_container(self._cfg.viewers, resolve=True)
        self._block_path: Path | None = None
        self._tree = ParameterTree()
        self._root = Parameter.create(name="stores", type="group", children=[])
        self._tree.setParameters(self._root, showTop=False)

        launch_btn = QtWidgets.QPushButton("Launch window")
        launch_btn.clicked.connect(self._on_launch)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._tree)
        layout.addWidget(launch_btn)

    def set_block(self, block_path: Path) -> None:
        """Scan a block and rebuild the parameter tree for it.

        :param block_path: Path to the block directory.
        """
        self._block_path = block_path
        resolved = [resolve_role(i, self._rules) for i in scan_block(block_path)]
        spec = build_param_tree_spec(resolved, self._viewer_defaults)
        self._root.clearChildren()
        self._root.addChildren(spec)

    def _on_launch(self) -> None:
        """Read tree state, build a Session, and emit launch_requested signal."""
        if self._block_path is None:
            return
        state = self._read_state()
        session = spec_to_session(self._block_path.name, state)
        self.launch_requested.emit(session)

    def _read_state(self) -> dict:
        """Read the current tree values into the shape expected by :func:`spec_to_session`."""
        out: dict = {}
        for store in self._root.children():
            s: dict = {}
            viewers: dict = {}
            for child in store.children():
                if child.name() == "Viewers":
                    for v in child.children():
                        params = {p.name(): p.value() for p in v.children()}
                        viewers[v.name()] = {"_enabled": v.value(), **params}
                else:
                    s[child.name()] = child.value()
            s["Viewers"] = viewers
            out[store.name()] = s
        return out
