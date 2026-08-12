# Design: `tdt-install-shortcuts` — Windows desktop shortcuts

**Date:** 2026-08-12
**Status:** Approved

## Goal

Give lab users a one-command way to put desktop shortcuts for `tdt-explore` and
`tdt-metadata` on their Windows desktop, so they can launch the GUIs by
double-clicking instead of typing `uv run …`.

## Scope decisions (settled)

- **Platform:** Windows only. No macOS/Linux launchers.
- **Trigger:** a separate console-script entry point (`tdt-install-shortcuts`),
  run manually once. *Not* auto-on-`uv sync` — the `uv_build` backend has no
  post-install hook, so that path is not available without changing build systems.
- **What the shortcuts launch:** the bare apps (no `--tank`); the user picks a
  tank with the in-window picker each time.
- **Placement:** Desktop only, two `.lnk` files.
- **Console window:** suppressed by launching through the venv's `pythonw.exe`
  rather than the console-mode `tdt-explore.exe`.
- **Dependencies:** none added. Shortcut creation goes through PowerShell's
  built-in `WScript.Shell` COM object via `subprocess`, avoiding `pywin32`.

## Components

### 1. `src/tdt_ephyviewer_explorer/shortcuts.py` (Qt-free, unit-testable)

- `ShortcutSpec` dataclass: `name: str`, `target: Path`, `arguments: str`,
  `working_dir: Path`, `description: str`.
- `find_pythonw() -> Path` — resolve `pythonw.exe` as a sibling of
  `sys.executable` (the venv interpreter). Fall back to `python.exe` if
  `pythonw.exe` is absent (with the console-flash caveat).
- `explorer_specs(pythonw: Path) -> list[ShortcutSpec]` — build the two specs:
  - **TDT Explore** → `pythonw.exe -m tdt_ephyviewer_explorer`
  - **TDT Metadata** → `pythonw.exe -m tdt_ephyviewer_explorer.metadata`
  - `working_dir` set to the user profile (`%USERPROFILE%`); the apps read the
    packaged config and per-tank sessions, so cwd is not load-bearing.
- `build_powershell(spec: ShortcutSpec) -> str` — generate the PowerShell snippet
  that creates one `.lnk`. The Desktop directory is resolved *inside* PowerShell
  via `[Environment]::GetFolderPath('Desktop')`, which correctly follows OneDrive
  desktop redirection. This function is the primary testable seam (pure string in,
  pure string out).
- `install(specs: list[ShortcutSpec]) -> list[Path]` — run the generated
  PowerShell, return the created `.lnk` paths. Guard on `sys.platform == "win32"`;
  raise a clear error on other platforms.
- `main(argv: list[str] | None = None) -> int` — the console entry point. No
  arguments beyond `-h`. Prints the shortcuts it created.

### 2. `__main__.py` in both packages

- `src/tdt_ephyviewer_explorer/__main__.py` → calls `app.main()`.
- `src/tdt_ephyviewer_explorer/metadata/__main__.py` → calls `metadata.app.main()`.

These let `pythonw.exe -m tdt_ephyviewer_explorer` and
`pythonw.exe -m tdt_ephyviewer_explorer.metadata` launch the GUIs without a
console window. Each is a thin `raise SystemExit(main())` wrapper.

### 3. `pyproject.toml`

Add under `[project.scripts]`:

```toml
tdt-install-shortcuts = "tdt_ephyviewer_explorer.shortcuts:main"
```

### 4. `tests/test_shortcuts.py` (mirror test, Qt-free, headless)

- `find_pythonw` returns a sibling of a given interpreter path (monkeypatch
  `sys.executable`); falls back correctly when `pythonw.exe` is missing.
- `explorer_specs` produces two specs with the expected `-m` module targets and
  names.
- `build_powershell` embeds the target, arguments, shortcut name, working dir,
  and the `GetFolderPath('Desktop')` call; properly quotes/escapes values.
- No `.lnk` is written by the suite and PowerShell is not invoked.

## Flow

```
uv run tdt-install-shortcuts
  → find_pythonw()            # venv pythonw.exe
  → explorer_specs(pythonw)   # two ShortcutSpec
  → install(specs)            # PowerShell writes two .lnk to Desktop
  → prints created paths
```

Double-clicking a shortcut launches the Qt GUI with the in-window tank picker and
no console flash.

## Out of scope (YAGNI)

- Auto-creation on `uv sync` (no build-backend hook available).
- Start Menu entries.
- `--tank` / pinned-tank shortcuts.
- Custom `.ico` icons.
- macOS / Linux launchers.

## Testing strategy

Unit tests cover spec construction and PowerShell generation on any platform.
Actual `.lnk` creation is exercised manually on a Windows machine
(`uv run tdt-install-shortcuts`, then double-click each shortcut).
