"""Launch a Block Window (MainViewer) from a session."""
from __future__ import annotations

from pathlib import Path

from ephyviewer import MainViewer
from omegaconf import OmegaConf

from tdt_ephyviewer_explorer.builders import Attachment, build_source_for, build_viewer
from tdt_ephyviewer_explorer.session import Session
from tdt_ephyviewer_explorer.stores import load_store, resolve_role, rules_from_config
from tdt_ephyviewer_explorer.tank import scan_block


def _attachment_from_dict(d: dict) -> Attachment:
    probe = d.get("probe_path")
    return Attachment(
        viewer_type=d["viewer_type"],
        delay_ms=float(d.get("delay_ms", 0.0)),
        probe_path=Path(probe) if probe else None,
        params=dict(d.get("params", {})),
    )


def launch_block(block_path: Path, session: Session, cfg) -> MainViewer:
    """Build and populate a MainViewer for one block from a session.

    :param block_path: Block directory.
    :param session: The composition to realize.
    :param cfg: Composed Hydra config (viewers, roles, schemas).
    :returns: The populated (but not yet shown) MainViewer.
    """
    rules = rules_from_config(cfg)
    infos = {info.name: info for info in scan_block(block_path)}
    schemas = OmegaConf.to_container(cfg.schemas, resolve=True)
    viewer_defaults = OmegaConf.to_container(cfg.viewers, resolve=True)

    win = MainViewer(debug=False)
    win.setWindowTitle(block_path.name)
    first_name: str | None = None
    for store_name, attach_dicts in session.attachments.items():
        resolved = resolve_role(infos[store_name], rules)
        raw = load_store(block_path, store_name)
        for d in attach_dicts:
            attachment = _attachment_from_dict(d)
            source = build_source_for(resolved, attachment, raw, schemas)
            name = f"{store_name}:{attachment.viewer_type}"
            params = {**viewer_defaults.get(attachment.viewer_type, {}), **attachment.params}
            view = build_viewer(attachment.viewer_type, source, name, params)
            if first_name is None:
                win.add_view(view)
                first_name = name
            else:
                win.add_view(view, tabify_with=first_name)
    return win
