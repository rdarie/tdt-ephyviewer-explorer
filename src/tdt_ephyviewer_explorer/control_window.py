"""The per-tank Control Window and its (pure) parameter-tree spec."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf
from pyqtgraph.parametertree import Parameter, ParameterTree
from PySide6 import QtWidgets
from PySide6.QtCore import Signal

from tdt_ephyviewer_explorer.annotations import resolve_labels_path
from tdt_ephyviewer_explorer.config_schema import load_config
from tdt_ephyviewer_explorer.impedance import (
    ImpedanceInfo,
    classify_impedance_csv,
    scan_impedance,
)
from tdt_ephyviewer_explorer.processed import (
    ProcessedInfo,
    classify,
    scan_preprocessed,
    to_stored_path,
)
from tdt_ephyviewer_explorer.session import (
    ImpedanceSource,
    ProcessedSource,
    Session,
    load_session,
    save_session,
)
from tdt_ephyviewer_explorer.stores import ResolvedStore, resolve_role, rules_from_config
from tdt_ephyviewer_explorer.tank import list_blocks, read_headers, scan_block
from tdt_ephyviewer_explorer.tank_picker import TankPicker


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
        viewer_children: list[dict] = []
        for vt in rs.viewers:
            vchildren = _params_children(viewer_defaults.get(vt, {}))
            if vt == "eventlist" and rs.role == "stim":
                # Source-build option (not a widget param): surfaced/stripped in
                # _enabled_attachments so it never reaches EventList.params.
                vchildren.append(
                    {"name": "sort", "type": "list",
                     "limits": ["time", "channel"], "value": rs.sort}
                )
            viewer_children.append(
                {"name": vt, "type": "bool", "value": False, "children": vchildren}
            )
        children.append({"name": "Viewers", "type": "group", "children": viewer_children})
        groups.append({"name": rs.info.name, "type": "group", "children": children})
    return groups


def build_processed_param_spec(
    infos: list[ProcessedInfo], viewer_defaults: dict
) -> list[dict]:
    """Build parametertree groups for processed-parquet sources.

    Each group carries readonly ``source_path``/``source_kind``/``source_name`` so
    :func:`spec_to_session` can round-trip it into a :class:`~session.ProcessedSource`.

    :param infos: Classified processed sources.
    :param viewer_defaults: Per-viewer default params.
    :returns: A list of group-parameter dicts.
    """
    groups: list[dict] = []
    for info in infos:
        children: list[dict] = [
            {"name": "source_path", "type": "str", "value": str(info.path), "readonly": True},
            {"name": "source_kind", "type": "str", "value": info.kind, "readonly": True},
            {"name": "source_name", "type": "str", "value": info.name, "readonly": True},
            {"name": "fs", "type": "float", "value": info.sampling_rate or 0.0, "readonly": True},
            {"name": "delay_ms", "type": "float", "value": 0.0},
        ]
        if info.role == "timeseries":
            children.append({"name": "probe_file", "type": "str", "value": ""})
            children.append({"name": "reorder", "type": "bool", "value": False})
        viewer_children = [
            {"name": vt, "type": "bool", "value": False,
             "children": _params_children(viewer_defaults.get(vt, {}))}
            for vt in info.viewers
        ]
        children.append({"name": "Viewers", "type": "group", "children": viewer_children})
        groups.append({"name": info.name, "type": "group", "children": children})
    return groups


def build_impedance_param_spec(
    infos: list[ImpedanceInfo], viewer_defaults: dict
) -> list[dict]:
    """Build parametertree groups for impedance CSV sources.

    Each group carries readonly ``impedance_path``/``impedance_name`` so
    :func:`spec_to_session` can round-trip it into a
    :class:`~session.ImpedanceSource`. Unlike store and parquet groups there is no
    ``reorder`` checkbox: here the probe file *is* the grid layout, so a non-empty
    ``probe_file`` is used directly.

    :param infos: Classified impedance CSVs.
    :param viewer_defaults: Per-viewer default params.
    :returns: A list of group-parameter dicts.
    """
    groups: list[dict] = []
    for info in infos:
        frequencies = ", ".join(f"{f:g}" for f in info.frequencies) or "n/a"
        children: list[dict] = [
            {"name": "impedance_path", "type": "str", "value": str(info.path), "readonly": True},
            {"name": "impedance_name", "type": "str", "value": info.name, "readonly": True},
            {"name": "channels", "type": "int", "value": len(info.channel_numbers), "readonly": True},
            {"name": "frequencies", "type": "str", "value": frequencies, "readonly": True},
            {"name": "probe_file", "type": "str", "value": ""},
            {
                "name": "Viewers",
                "type": "group",
                "children": [
                    {
                        "name": "impedance",
                        "type": "bool",
                        "value": False,
                        "children": _params_children(viewer_defaults.get("impedance", {})),
                    }
                ],
            },
        ]
        groups.append({"name": info.name, "type": "group", "children": children})
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

    Groups carrying ``impedance_path`` become :class:`~session.ImpedanceSource`
    entries, groups carrying ``source_path`` become
    :class:`~session.ProcessedSource` entries; all others are TDT store attachments.

    :param block: Block name.
    :param param_state: Per-group tree state.
    :returns: The composition session (only enabled viewers included).
    """
    attachments: dict[str, list[dict]] = {}
    processed: list[ProcessedSource] = []
    impedance: list[ImpedanceSource] = []
    for name, state in param_state.items():
        entries = _enabled_attachments(state)
        if not entries:
            continue
        if "impedance_path" in state:
            impedance.append(
                ImpedanceSource(
                    path=str(state["impedance_path"]),
                    name=str(state.get("impedance_name", name)),
                    attachments=entries,
                )
            )
        elif "source_path" in state:
            fs = state.get("fs")
            processed.append(
                ProcessedSource(
                    path=str(state["source_path"]),
                    kind=str(state.get("source_kind", "")),
                    name=str(state.get("source_name", name)),
                    attachments=entries,
                    sampling_rate=float(fs) if fs else None,
                )
            )
        else:
            attachments[name] = entries
    return Session(
        block=block, attachments=attachments, processed=processed, impedance=impedance
    )


def _enabled_attachments(state: dict) -> list[dict]:
    """Extract enabled viewer attachments from one group's tree state.

    Store and parquet groups gate the probe behind an explicit ``reorder`` checkbox;
    impedance groups have no such key, because there the probe file *is* the grid
    layout rather than an optional reordering, so a non-empty ``probe_file`` is
    used directly.

    :param state: One group's tree state (``delay_ms``, optional ``probe_file``/
        ``reorder``, and a ``Viewers`` subgroup).
    :returns: Serialized attachment dicts for viewers with ``_enabled`` set.
    """
    viewers = state.get("Viewers", {})
    probe = state.get("probe_file") or None
    if "reorder" in state and not state["reorder"]:
        probe = None
    entries: list[dict] = []
    for vt, vstate in viewers.items():
        if not vstate.get("_enabled"):
            continue
        # `sort` is a source-build option, kept out of the widget param bag.
        params = {k: v for k, v in vstate.items() if k not in ("_enabled", "sort")}
        entry: dict = {
            "viewer_type": vt,
            "delay_ms": float(state.get("delay_ms", 0.0)),
            "probe_path": probe,
            "params": params,
        }
        if "sort" in vstate:
            entry["sort"] = vstate["sort"]
        entries.append(entry)
    return entries


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
        self._tank_dir: Path | None = None
        self._block_path: Path | None = None
        self._headers: Any | None = None

        # Global group: a block selector populated from list_blocks(). The tank path
        # itself is shown by the picker above, not duplicated here.
        self._picker = TankPicker()
        self._picker.tank_changed.connect(self.set_tank)
        self._global_tree = ParameterTree(showHeader=False)
        self._global_root = Parameter.create(
            name="global",
            type="group",
            children=[
                {"name": "block", "type": "list", "limits": [], "value": None},
                {
                    "name": "annotations_labels_path",
                    "type": "str",
                    "value": str(resolve_labels_path(self._cfg)),
                },
            ],
        )
        self._global_tree.setParameters(self._global_root, showTop=False)
        self._global_root.child("block").sigValueChanged.connect(self._on_block_changed)

        self._tree = ParameterTree()
        self._root = Parameter.create(name="stores", type="group", children=[])
        self._tree.setParameters(self._root, showTop=False)

        self._launch_btn = QtWidgets.QPushButton("Launch window")
        self._launch_btn.clicked.connect(self._on_launch)
        self._launch_btn.setEnabled(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._picker)
        layout.addWidget(self._global_tree)
        layout.addWidget(self._tree)
        layout.addWidget(self._launch_btn)

        save_btn = QtWidgets.QPushButton("Save session")
        save_btn.clicked.connect(self._on_save)
        load_btn = QtWidgets.QPushButton("Load session")
        load_btn.clicked.connect(self._on_load)
        layout.addWidget(save_btn)
        layout.addWidget(load_btn)

        add_btn = QtWidgets.QPushButton("Add processed…")
        add_btn.clicked.connect(self._on_add_processed)
        layout.addWidget(add_btn)

        add_imp_btn = QtWidgets.QPushButton("Add impedance CSV…")
        add_imp_btn.clicked.connect(self._on_add_impedance)
        layout.addWidget(add_imp_btn)
        self.setWindowTitle("tdt-explore")

    def set_tank(self, tank_dir: Path, block: str | None = None) -> None:
        """Point the window at a tank, populate the block selector, and load a block.

        Loading is done explicitly here rather than via the selector's change signal:
        pyqtgraph suppresses ``sigValueChanged`` when the value is unchanged, so
        switching to a tank whose chosen block shares a name with the previous
        selection would otherwise silently fail to reload. An empty tank clears any
        previously loaded block.

        :param tank_dir: Synapse tank directory.
        :param block: Block name to load; defaults to the first listed block.
        """
        self._tank_dir = tank_dir
        self._picker.show_tank(tank_dir)
        names = [p.name for p in list_blocks(tank_dir)]
        chosen = block if block in names else (names[0] if names else None)

        # Update the selector programmatically without firing the user-change handler,
        # then load exactly once (or clear, for an empty tank).
        block_param = self._global_root.child("block")
        block_param.sigValueChanged.disconnect(self._on_block_changed)
        try:
            block_param.setLimits(names)
            block_param.setValue(chosen)
        finally:
            block_param.sigValueChanged.connect(self._on_block_changed)

        if chosen is not None:
            self.set_block(tank_dir / chosen)
        else:
            self._block_path = None
            self._headers = None
            self._root.clearChildren()
        self._launch_btn.setEnabled(self._block_path is not None)

    def select_block(self, block: str) -> None:
        """Select a different block by name, loading its stores.

        Intended for switching blocks after :meth:`set_tank`; setting the selector
        value fires :meth:`_on_block_changed` (a no-op if already selected).

        :param block: Block directory name (must be one of the listed blocks).
        """
        self._global_root.child("block").setValue(block)

    def _on_block_changed(self, _param: Parameter, value: str | None) -> None:
        """Load the newly (user-)selected block's stores."""
        if self._tank_dir is not None and value:
            self.set_block(self._tank_dir / str(value))

    @property
    def picker(self) -> TankPicker:
        """The tank picker hosted at the top of the window."""
        return self._picker

    @property
    def launch_button(self) -> QtWidgets.QPushButton:
        """The launch button, disabled while no block is loaded."""
        return self._launch_btn

    @property
    def tank_dir(self) -> Path | None:
        """The current tank directory, or ``None`` before one is picked.

        This window is the single owner of the current tank; :class:`~app.App` reads
        it from here so that picking a new tank in the GUI cannot leave the launcher
        pointed at the previous one.
        """
        return self._tank_dir

    @property
    def headers(self) -> Any | None:
        """The current block's parsed ``.tsq`` headers, reused when launching.

        ``None`` until a block is loaded (or after an empty tank clears it).
        """
        return self._headers

    def set_block(self, block_path: Path) -> None:
        """Scan a block and rebuild the parameter tree for it.

        Parses the block index once here and keeps it (see :attr:`headers`) so the
        subsequent launch can reuse it instead of re-parsing.

        :param block_path: Path to the block directory.
        """
        self._block_path = block_path
        self._headers = read_headers(block_path)
        resolved = [resolve_role(i, self._rules) for i in scan_block(block_path, headers=self._headers)]
        spec = build_param_tree_spec(resolved, self._viewer_defaults)
        self._root.clearChildren()
        self._root.addChildren(spec)
        self._append_processed_groups(block_path)
        self._append_impedance_groups(block_path)
        self._launch_btn.setEnabled(True)

    def _append_processed_groups(self, block_path: Path) -> None:
        """Auto-scan the preprocessed dir for this block and add processed groups."""
        if not self._cfg.processed.auto_scan or self._tank_dir is None:
            return
        infos = scan_preprocessed(self._tank_dir, block_path.name, self._cfg)
        if infos:
            self._root.addChildren(
                build_processed_param_spec(self._with_stored_paths(infos), self._viewer_defaults)
            )

    def _with_stored_paths(self, infos: list[ProcessedInfo]) -> list[ProcessedInfo]:
        """Return copies of ``infos`` whose ``path`` is the stored (rel/abs) form."""
        from dataclasses import replace

        if self._tank_dir is None:
            return infos
        return [replace(i, path=Path(to_stored_path(i.path, self._tank_dir))) for i in infos]

    def _append_impedance_groups(self, block_path: Path) -> None:
        """Auto-scan the block dir for impedance CSVs and add their groups."""
        infos = scan_impedance(block_path, self._cfg)
        if infos:
            self._root.addChildren(
                build_impedance_param_spec(
                    self._with_stored_impedance(infos), self._viewer_defaults
                )
            )

    def _with_stored_impedance(self, infos: list[ImpedanceInfo]) -> list[ImpedanceInfo]:
        """Return copies of ``infos`` whose ``path`` is the stored (rel/abs) form."""
        from dataclasses import replace

        if self._tank_dir is None:
            return infos
        return [replace(i, path=Path(to_stored_path(i.path, self._tank_dir))) for i in infos]

    def _on_add_impedance(self) -> None:
        """Prompt for impedance CSVs and add them as groups."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add impedance CSV(s)", "", "CSV (*.csv)"
        )
        if paths:
            self.add_impedance_paths([Path(p) for p in paths])

    def add_impedance_paths(self, paths: list[Path]) -> None:
        """Classify each CSV and append it as an impedance group.

        A file that is not an impedance CSV, or that has a valid header but no data
        rows, is reported rather than silently dropped.

        :param paths: CSV file paths (any location).
        """
        infos: list[ImpedanceInfo] = []
        for path in paths:
            info = classify_impedance_csv(path, self._cfg)
            if info is None:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Not an impedance CSV",
                    f"{path.name} has no R<n> impedance columns, or no data rows.",
                )
                continue
            infos.append(info)
        if infos:
            self._root.addChildren(
                build_impedance_param_spec(
                    self._with_stored_impedance(infos), self._viewer_defaults
                )
            )

    def _on_add_processed(self) -> None:
        """Prompt for parquet files and add them as processed groups."""
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add processed parquet(s)", "", "Parquet (*.parquet)"
        )
        if paths:
            self.add_processed_paths([Path(p) for p in paths])

    def add_processed_paths(self, paths: list[Path]) -> None:
        """Classify each parquet and append it as a processed group.

        Files that classify (via contract or heuristic) are added directly. A file
        that cannot be classified as a timeseries for lack of a sample rate prompts
        for one; unrecognizable files are skipped.

        :param paths: Parquet file paths (any location).
        """
        infos: list[ProcessedInfo] = []
        for path in paths:
            info = classify(path, self._cfg)
            if info is None:
                info = self._prompt_processed_info(path)
            if info is not None:
                infos.append(info)
        if infos:
            self._root.addChildren(
                build_processed_param_spec(self._with_stored_paths(infos), self._viewer_defaults)
            )

    def _prompt_processed_info(self, path: Path) -> ProcessedInfo | None:
        """Ask for a sampling rate and treat a blob-less file as a timeseries.

        :param path: The parquet path.
        :returns: A timeseries :class:`ProcessedInfo`, or ``None`` if cancelled.
        """
        from tdt_ephyviewer_explorer.stores import VALID_VIEWERS

        rate, ok = QtWidgets.QInputDialog.getDouble(
            self, "Sampling rate", f"{path.name}: sampling rate (Hz)",
            float(self._cfg.processed.default_sampling_rate), 0.0, 1e9, 4,
        )
        if not ok:
            return None
        return ProcessedInfo(
            path=path, kind="timeseries", role="timeseries", name=path.stem,
            sampling_rate=rate, t_start=0.0, channel_names=None, time_column=None,
            time_units="seconds", label_column=None, schema=None, units=None,
            viewers=VALID_VIEWERS["timeseries"],
        )

    def _annotations_labels_path(self) -> str:
        """Current value of the global annotations labels-path box."""
        return str(self._global_root.child("annotations_labels_path").value())

    def _on_launch(self) -> None:
        """Read tree state, build a Session, and emit launch_requested signal."""
        if self._block_path is None:
            return
        state = self._read_state()
        session = spec_to_session(self._block_path.name, state)
        session.annotations_labels_path = self._annotations_labels_path()
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

    def _on_save(self) -> None:
        """Prompt for a name and save the current composition as a session."""
        if self._block_path is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save session", "Session name:")
        if ok and name:
            session = spec_to_session(self._block_path.name, self._read_state())
            session.annotations_labels_path = self._annotations_labels_path()
            save_session(session, self._block_path.parent, name)

    def _on_load(self) -> None:
        """Prompt for a session file and apply it to the tree."""
        if self._block_path is None:
            return
        start_dir = self._block_path.parent / "tdt_explore" / "sessions"
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load session", str(start_dir), "YAML (*.yaml)"
        )
        if path:
            session = load_session(Path(path))
            self._apply_session(session)

    def _apply_session(self, session: Session) -> None:
        """Set tree values from a loaded session (enabling the saved viewers)."""
        if session.annotations_labels_path:
            self._global_root.child("annotations_labels_path").setValue(
                session.annotations_labels_path
            )

        # Rebuild processed groups from the session so their viewer state can be applied.
        existing = {g.name() for g in self._root.children()}
        new_infos: list[ProcessedInfo] = []
        for ps in session.processed:
            if ps.name in existing:
                continue
            from tdt_ephyviewer_explorer.stores import VALID_VIEWERS
            new_infos.append(ProcessedInfo(
                path=Path(ps.path), kind=ps.kind, role=ps.kind, name=ps.name,
                sampling_rate=ps.sampling_rate, t_start=ps.t_start or 0.0,
                channel_names=None, time_column=ps.time_column,
                time_units=ps.time_units or "seconds", label_column=ps.label_column,
                schema=None, units=None, viewers=VALID_VIEWERS[ps.kind],
            ))
        if new_infos:
            self._root.addChildren(build_processed_param_spec(new_infos, self._viewer_defaults))

        new_impedance = [
            ImpedanceInfo(path=Path(i.path), name=i.name, frequencies=(),
                          channel_numbers=(), units="")
            for i in session.impedance
            if i.name not in existing
        ]
        if new_impedance:
            self._root.addChildren(
                build_impedance_param_spec(new_impedance, self._viewer_defaults)
            )

        by_name_processed = {ps.name: ps.attachments for ps in session.processed}
        by_name_impedance = {i.name: i.attachments for i in session.impedance}
        for store in self._root.children():
            entries = (
                session.attachments.get(store.name(), [])
                or by_name_processed.get(store.name(), [])
                or by_name_impedance.get(store.name(), [])
            )
            by_type = {e["viewer_type"]: e for e in entries}
            for child in store.children():
                if child.name() == "Viewers":
                    for v in child.children():
                        entry = by_type.get(v.name())
                        v.setValue(entry is not None)
                        if entry:
                            for p in v.children():
                                if p.name() == "sort" and "sort" in entry:
                                    p.setValue(entry["sort"])
                                elif p.name() in entry["params"]:
                                    p.setValue(entry["params"][p.name()])
                elif child.name() == "delay_ms" and entries:
                    child.setValue(entries[0]["delay_ms"])
                elif child.name() == "probe_file" and entries:
                    child.setValue(entries[0].get("probe_path") or "")
                elif child.name() == "reorder" and entries:
                    child.setValue(bool(entries[0].get("probe_path")))
