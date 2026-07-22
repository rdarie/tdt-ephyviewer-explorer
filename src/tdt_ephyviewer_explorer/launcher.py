"""Launch a Block Window (MainViewer) from a session."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ephyviewer import MainViewer
from omegaconf import DictConfig, OmegaConf

from tdt_ephyviewer_explorer.builders import Attachment, build_source_for, build_viewer
from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import load_store, resolve_role, rules_from_config
from tdt_ephyviewer_explorer.tank import scan_block


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


def plan_views(block_path: Path, session: Session, cfg: DictConfig) -> list[ViewPlan]:
    """Resolve a session into an ordered list of viewers to build (Qt-free).

    Scans the block once, resolves each store's role, loads each referenced store
    exactly once (even with several viewers attached), and builds one source per
    attachment. Contains no Qt/GUI code so it is unit-testable headlessly.

    :param block_path: Block directory.
    :param session: The composition to realize.
    :param cfg: Composed Hydra config (viewers, roles, schemas).
    :returns: One :class:`ViewPlan` per attachment, in session order.
    :raises KeyError: If a session references a store absent from the block.
    """
    rules = rules_from_config(cfg)
    infos = {info.name: info for info in scan_block(block_path)}
    schemas = OmegaConf.to_container(cfg.schemas, resolve=True)
    viewer_defaults = OmegaConf.to_container(cfg.viewers, resolve=True)

    plans: list[ViewPlan] = []
    for store_name, attach_dicts in session.attachments.items():
        if store_name not in infos:
            raise KeyError(
                f"session references store {store_name!r} not present in block {block_path.name}"
            )
        resolved = resolve_role(infos[store_name], rules)
        raw = load_store(block_path, store_name)  # loaded once per store
        for d in attach_dicts:
            attachment = _attachment_from_dict(d)
            source = build_source_for(resolved, attachment, raw, schemas)
            name = f"{store_name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            plans.append(ViewPlan(name, attachment.viewer_type, params, source))
    return plans


def launch_block(block_path: Path, session: Session, cfg: DictConfig) -> MainViewer:
    """Build and populate a MainViewer for one block from a session.

    Thin Qt wrapper over :func:`plan_views`: docks the first viewer bare and
    tabifies the rest with it.

    :param block_path: Block directory.
    :param session: The composition to realize.
    :param cfg: Composed Hydra config (viewers, roles, schemas).
    :returns: The populated (but not yet shown) MainViewer.
    """
    win = MainViewer(debug=False)
    win.setWindowTitle(block_path.name)
    first_name: str | None = None
    for plan in plan_views(block_path, session, cfg):
        view = build_viewer(plan.viewer_type, plan.source, plan.name, plan.params)
        if first_name is None:
            win.add_view(view)
            first_name = plan.name
        else:
            win.add_view(view, tabify_with=first_name)
    return win
