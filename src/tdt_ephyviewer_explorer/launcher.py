"""Launch a Block Window (MainViewer) from a session."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ephyviewer import MainViewer
from omegaconf import DictConfig, OmegaConf

from tdt_ephyviewer_explorer.annotations import (
    DEFAULT_CHANNEL_NAME,
    build_annotation_source,
    resolve_labels_path,
)
from tdt_ephyviewer_explorer.builders import Attachment, build_source_for, build_viewer
from tdt_ephyviewer_explorer.impedance import (
    ImpedanceInfo,
    build_impedance_source,
    classify_impedance_csv,
)
from tdt_ephyviewer_explorer.processed import (
    ProcessedInfo,
    build_processed_source,
    classify,
    from_stored_path,
)
from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import load_store, resolve_role, rules_from_config
from tdt_ephyviewer_explorer.tank import read_headers, scan_block


@dataclass
class ViewPlan:
    """One viewer to build, resolved from a session (Qt-free).

    :param name: Unique dock name (``"<store>:<viewer_type>"``).
    :param viewer_type: Viewer key to construct.
    :param params: Merged viewer parameters (defaults + per-attachment overrides).
    :param source: The built ephyviewer source to wrap.
    """

    name: str
    viewer_type: str
    params: dict[str, Any]
    source: Any


def _attachment_from_dict(d: dict[str, Any]) -> Attachment:
    probe = d.get("probe_path")
    return Attachment(
        viewer_type=d["viewer_type"],
        delay_ms=float(d.get("delay_ms", 0.0)),
        probe_path=Path(probe) if probe else None,
        params=dict(d.get("params", {})),
    )


def _processed_info(ps: Any, tank_dir: Path, cfg: DictConfig) -> ProcessedInfo:
    """Resolve a :class:`~session.ProcessedSource` to a :class:`~processed.ProcessedInfo`.

    Classifies the file at its stored path; applies any blob-less overrides carried
    on the source.

    :param ps: The session's ProcessedSource.
    :param tank_dir: Tank directory (for relative-path resolution).
    :param cfg: Composed config.
    :raises FileNotFoundError: If the stored parquet no longer exists.
    """
    path = from_stored_path(ps.path, tank_dir)
    if not path.exists():
        raise FileNotFoundError(f"processed source {ps.path!r} not found under {tank_dir}")
    info = classify(path, cfg)
    if info is None:
        from tdt_ephyviewer_explorer.stores import VALID_VIEWERS
        info = ProcessedInfo(
            path=path, kind=ps.kind, role=ps.kind, name=ps.name,
            sampling_rate=ps.sampling_rate, t_start=ps.t_start or 0.0,
            channel_names=None, time_column=ps.time_column,
            time_units=ps.time_units or "seconds", label_column=ps.label_column,
            schema=None, units=None, viewers=VALID_VIEWERS[ps.kind],
        )
    return info


def _impedance_info(source: Any, tank_dir: Path, cfg: DictConfig) -> ImpedanceInfo:
    """Resolve a :class:`~session.ImpedanceSource` to an :class:`~impedance.ImpedanceInfo`.

    :param source: The session's ImpedanceSource.
    :param tank_dir: Tank directory (for relative-path resolution).
    :param cfg: Composed config.
    :raises FileNotFoundError: If the stored CSV no longer exists.
    :raises ValueError: If the file is no longer a readable impedance CSV.
    """
    path = from_stored_path(source.path, tank_dir)
    if not path.exists():
        raise FileNotFoundError(f"impedance source {source.path!r} not found under {tank_dir}")
    info = classify_impedance_csv(path, cfg)
    if info is None:
        raise ValueError(
            f"impedance source {source.path!r} is not a readable impedance CSV "
            "(no R<n> columns, or no data rows)"
        )
    return info


def plan_views(
    block_path: Path, session: Session, cfg: DictConfig, headers: Any | None = None
) -> list[ViewPlan]:
    """Resolve a session into an ordered list of viewers to build (Qt-free).

    Parses the block's ``.tsq`` index once and reuses it for the header scan and
    every store load (rather than re-parsing per read), resolves each store's role,
    loads each referenced store exactly once (even with several viewers attached),
    and builds one source per attachment. Processed parquets and impedance CSV
    sidecars are appended after the TDT stores, in session order. Contains no
    Qt/GUI code so it is unit-testable headlessly.

    :param block_path: Block directory.
    :param session: The composition to realize.
    :param cfg: Composed Hydra config (viewers, roles, schemas).
    :param headers: Pre-parsed headers (see :func:`~tank.read_headers`) to reuse;
        when ``None`` the index is parsed here, once.
    :returns: One :class:`ViewPlan` per attachment, in session order.
    :raises KeyError: If a session references a store absent from the block.
    """
    rules = rules_from_config(cfg)
    heads = headers if headers is not None else read_headers(block_path)
    infos = {info.name: info for info in scan_block(block_path, headers=heads)}
    schemas = OmegaConf.to_container(cfg.schemas, resolve=True)
    viewer_defaults = OmegaConf.to_container(cfg.viewers, resolve=True)

    plans: list[ViewPlan] = []
    for store_name, attach_dicts in session.attachments.items():
        if store_name not in infos:
            raise KeyError(
                f"session references store {store_name!r} not present in block {block_path.name}"
            )
        resolved = resolve_role(infos[store_name], rules)
        raw = load_store(block_path, store_name, headers=heads)  # loaded once per store
        for d in attach_dicts:
            attachment = _attachment_from_dict(d)
            source = build_source_for(resolved, attachment, raw, schemas)
            name = f"{store_name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            plans.append(ViewPlan(name, attachment.viewer_type, params, source))

    tank_dir = block_path.parent
    for ps in session.processed:
        info = _processed_info(ps, tank_dir, cfg)
        for d in ps.attachments:
            attachment = _attachment_from_dict(d)
            source = build_processed_source(info, attachment, cfg)
            name = f"{ps.name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            plans.append(ViewPlan(name, attachment.viewer_type, params, source))

    for isource in session.impedance:
        info = _impedance_info(isource, tank_dir, cfg)
        for d in isource.attachments:
            attachment = _attachment_from_dict(d)
            source = build_impedance_source(info, attachment, cfg)
            name = f"{isource.name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            plans.append(ViewPlan(name, attachment.viewer_type, params, source))

    # Always-on writable annotation encoder, one per launched block.
    labels_path = resolve_labels_path(cfg, session.annotations_labels_path)
    plans.append(
        ViewPlan(
            name=DEFAULT_CHANNEL_NAME,
            viewer_type="epochencoder",
            params=dict(viewer_defaults.get("epochencoder", {})),
            source=build_annotation_source(block_path, labels_path, cfg),
        )
    )
    return plans


def _apply_trace_color_scheme(view: Any, scheme_name: str) -> None:
    """Auto-apply a named colormap to a TraceViewer via its params controller.

    Selects ``scheme_name`` in the controller's ``combo_cmap`` and triggers the
    same progressive coloring the "Progressive" button performs. Viewers without a
    color-scheme control (e.g. epoch/event/spike) are skipped.

    :param view: A built ephyviewer viewer.
    :param scheme_name: Colormap name; must be one of the controller's combo entries.
    :raises ValueError: If ``scheme_name`` is not among the controller's schemes.
    """
    controller = getattr(view, "params_controller", None)
    combo = getattr(controller, "combo_cmap", None)
    if combo is None:
        return  # not a color-capable viewer
    names = [combo.itemText(i) for i in range(combo.count())]
    if scheme_name not in names:
        raise ValueError(
            f"startup.trace_color_scheme {scheme_name!r} not in available schemes {names}"
        )
    combo.setCurrentIndex(names.index(scheme_name))
    controller.on_automatic_color()


def apply_startup(win: Any, views: list[Any], startup: dict[str, Any]) -> None:
    """Apply one-time startup behavior to a freshly populated block window (Qt-free).

    :param win: The populated MainViewer (only ``auto_scale`` is invoked here).
    :param views: The built viewers, in launch order.
    :param startup: The ``startup`` config section (``trace_color_scheme``, ``auto_scale``).
    """
    scheme = startup.get("trace_color_scheme")
    if scheme:
        for view in views:
            _apply_trace_color_scheme(view, scheme)
    if startup.get("auto_scale", False):
        win.auto_scale()  # MainViewer fans out to every viewer that supports it


def launch_block(
    block_path: Path, session: Session, cfg: DictConfig, headers: Any | None = None
) -> MainViewer:
    """Build and populate a MainViewer for one block from a session.

    Thin Qt wrapper over :func:`plan_views`: docks the first viewer bare and
    tabifies the rest with it, then applies startup behavior (see
    :func:`apply_startup`).

    :param block_path: Block directory.
    :param session: The composition to realize.
    :param cfg: Composed Hydra config (viewers, roles, schemas, startup).
    :param headers: Pre-parsed headers (see :func:`~tank.read_headers`) to reuse.
    :returns: The populated (but not yet shown) MainViewer.
    """
    win = MainViewer(debug=False)
    win.setWindowTitle(block_path.name)
    views: list[Any] = []
    first_name: str | None = None
    for plan in plan_views(block_path, session, cfg, headers=headers):
        view = build_viewer(plan.viewer_type, plan.source, plan.name, plan.params)
        if first_name is None:
            win.add_view(view)
            first_name = plan.name
        else:
            win.add_view(view, tabify_with=first_name)
        views.append(view)
    startup = OmegaConf.to_container(cfg.startup, resolve=True) if "startup" in cfg else {}
    apply_startup(win, views, startup)
    return win
