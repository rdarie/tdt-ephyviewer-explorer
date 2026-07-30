# Very important Context & Coding Guidelines

## 1. Project Overview & Role
* **Role:** You are a research engineer preparing a data exploration app meant for small-scall use in a research laboratory.

## 2. Concise communication
In all interactions and commit messages, be extremely concise.

## 3. Tech Stack & Environment
* **Language:** Python 3.12+ Always activate the virtual environment before running any Python commands (e.g., `source .venv/bin/activate` or equivalent). Never run pytest, python, or pip outside the venv.
* **Package manager:** use `uv` as your package manager of choice.
* **Configuration:** `Hydra` (structured configs). Do not hardcode hyperparameters.
* **GUI Framework:** Custom fork of ([`ephyviewer`](https://github.com/rdarie/ephyviewer)).
* * **Data Handling:** `NumPy`, `Pandas`, [`tdt`](https://pypi.org/project/tdt/).
  
## 4. Creating design specifications and implementation plans
* *Crucial*: After producing a design spec and implementation plan for a new feature, explicitly list any important missing details or design decisions you need from me before finalizing. Organize plans into clear sections with headings, and include a proposed module tree where helpful. Consider system boundaries and future extensibility.

## 5. Coding Conventions
* **Type Hinting:** Use strict `typing` (e.g., `def train(loader: DataLoader, model: nn.Module) -> float:`).
* **Docstrings:** Use reStructuredText (reST) style docstrings.
* **Test Driven Development:**
  * When implementing from a plan document, follow the plan phases/tasks exactly in order. After each phase, run tests before proceeding to the next. If a test fails, fix it before moving on.

## 6. Git Workflow section
* When committing changes, never `git add` files that are in `.gitignore`. Always check `.gitignore` before staging. If config files appear tracked despite gitignore, they likely need to be removed from tracking with `git rm --cached`.
* Do not use git worktrees - too complicated for this repo where we only ever work on one feature at a time.
  
## 7. Negative Constraints ("Do Not" Rules)
* **No Hardcoded Paths:** Never use absolute paths like `/home/user/data`. Use relative paths or environment variables.
* **No "Magic Numbers":** Do not put hyperparameters (learning rate, batch size) in the middle of code. Move them to the config.
* **No Jupyter Logic:** Do not generate code that relies on global state typical of Notebooks. Scripts must be self-contained executables.
* **No Silent Failures:** If a gradient is NaN, fail immediately and log the error. Do not ignore it.

## 8. Codebase Map (for agentic coders)

### Commands
* Install (dev, editable ephyviewer from `../ephyviewer`): `uv sync`. Standard (ephyviewer from git fork): `uv sync --no-sources`.
* Run app: `uv run tdt-explore --tank "<tank dir>" [--block <name>]`.
* Run metadata browser: `uv run tdt-metadata [--tank "<tank dir>"]`.
* All tests: `uv run pytest`. Single file/test: `uv run pytest tests/test_builders.py::test_name`.
* Suite is Qt-free & headless. The one real-`tdt` test is skipped unless `TDT_EXPLORE_TEST_BLOCK=<tank>/<block>` is set (see README).
* Each `src/` module has a mirror `tests/test_<module>.py`; add tests there.

### Architecture — two windows, one Qt-free core
The app is deliberately split so all data logic is unit-testable without Qt:
* **Control Window** (`control_window.py`, Qt): per-tank. Pick a block, compose viewers per store via a pyqtgraph ParameterTree, save/load sessions, emit `launch_requested(Session)`.
* **Block Window** = ephyviewer `MainViewer` (`launcher.py`, thin Qt wrapper): one per launched block, holds the synchronized viewers.
* **`app.py`** `App` orchestrates: owns the Control Window, connects `launch_requested` → `launch_block`, tracks open windows.

### The pipeline (store → viewer), and where each step lives
1. **Discover** (`tank.py`): `list_blocks` (dirs with a `*.tsq`), `read_headers` (parse the `.tsq` index **once**), `scan_block` → `list[StoreInfo]` (header-only, no bulk data).
2. **Resolve role** (`stores.py`): `resolve_role(StoreInfo, rules)` → `ResolvedStore`. First matching fnmatch `RoleRule` wins; else fall back by tdt type via `TDT_TYPE_TO_ROLE`. `VALID_VIEWERS` maps role → allowed viewer types.
3. **Load** (`stores.py`): `load_store(block_path, name, headers=…)` pulls one store's full data (reuses parsed `headers`).
4. **Build sources** (`builders.py`): `build_source_for` dispatches by viewer type → `build_analog_source` / `build_event_source` / `build_epoch_source` / `build_spike_source` → in-memory ephyviewer sources. `build_viewer` wraps a source in a viewer class (`_VIEWER_CLASSES`).
5. **Plan & launch** (`launcher.py`): `plan_views` (Qt-free) resolves a `Session` → ordered `ViewPlan`s, loading each store **once** even with multiple viewers; `launch_block` docks the first viewer and tabifies the rest.

* **Impedance CSVs** (`impedance.py`, Qt-free + `viewers/impedance_view.py`, Qt): a third
  source category beside TDT stores and processed parquets. `scan_impedance` header-sniffs
  the block dir's CSVs, `read_impedance` averages rows within each frequency, and
  `build_grid_source` places channels onto the probe grid from `probe.probe_layout`
  (`topo_x`/`topo_y`, else inferred from `contact_positions`). Not time-synced: the source
  has no `t_start`, which is what keeps `MainViewer` from widening the nav range.

### The metadata browser (`metadata/`)
A second app (`tdt-metadata`) that browses session metadata without opening viewers, built
on the same Qt-free-core rule: `listing.py` (StoresListing → gizmos), `notes.py` (Notes.txt
parse/render plus the editable `AnalysisNotes` model), `stim.py` (eS1p → pulses and unique
parameter combinations), `summary.py` (`BlockSummary` and the three read tiers), with
`window.py`/`notes_panel.py` as the Qt shell. `tank_picker.py` is shared with the Control
Window. Reads are tiered — text sidecars for all blocks, `.tsq` headers and `eS1p` only on
expand — so don't move the expensive reads into the eager path.

### Key concepts
* **`.tsq` index reuse (perf):** parse once via `read_headers`, then thread the `headers` object through `scan_block` / `load_store` / `plan_views`. The Control Window caches it on `ControlWindow.headers` and `app.py` passes it into `launch_block`. Don't reintroduce per-read re-parsing.
* **Session** (`session.py`): a pure composition record (`block` + `{store: [attachment dicts]}`), NOT viewer state. Persisted as YAML under `<tank>/tdt_explore/sessions/`. **Raw block dirs are never written to.** Conversion: `spec_to_session` (tree state → Session), `_apply_session` (Session → tree).
  **Exception:** `tdt-metadata` writes `<block>/analysis_notes.txt` — the one sanctioned
  write into a raw block dir, for post-hoc annotations. Nothing else may write there.
* **Config** (Hydra, `config/`): `config.yaml` composes `viewer/`, `roles/`, `schema/`, `startup/`, `processed/`, `impedance/`, `metadata/` groups (all `# @package _global_`). `startup` drives one-time launch behavior (`auto_scale`, `trace_color_scheme`) applied by `launcher.apply_startup`. Loaded read-only via `config_schema.load_config`; GUI seeds its tree from it and saves tweaks to sessions. Add hyperparameters/patterns here, never in code.
* **Roles/schemas/formatters:** a `RoleRule` may pin a column `schema` (named list in `schema/default.yaml`) and a `formatter` (Hydra `_target_`, instantiated for event labels). Formatters implement `StimFormatter.format_row` (`formatters/base.py`); `GenericFormatter` is the fallback, `IZVoiceFormatter` the example.
* **Probes** (`probe.py`): optional probeinterface JSON reorders analog channels into contact order (timeseries only); no probe = acquisition order.
* **delay_ms:** unit-agnostic alignment offset applied to every store type in the source builders.

### Gotchas
* `set_tank` loads the block **explicitly**, not via the selector's change signal — pyqtgraph suppresses `sigValueChanged` when the value is unchanged, so a same-named block on a new tank would silently fail to reload.
* `tdt` store objects are accessed dict-or-attribute style; use the `_get` helper in `stores.py`.
