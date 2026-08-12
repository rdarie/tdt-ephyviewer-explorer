# Impedance Annotation Keywords Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the impedance heatmap annotate each cell with a GUI-editable, keyword-driven format string drawing on impedance-CSV and probe-file fields (`channel`, `impedance`, `units`, `name`, `contact_id`, `region`).

**Architecture:** Static per-cell fields are assembled in the Qt-free source builder (`impedance.py`); the impedance value (frequency-dependent) is injected by the viewer at render time. A Qt-free `format_cell` helper performs robust named substitution. The viewer stays a thin Qt shell.

**Tech Stack:** Python 3.12, NumPy, pandas, probeinterface, pyqtgraph/ephyviewer (viewer only), pytest, `uv`.

## Global Constraints

- Run everything through the venv via `uv` (`uv run pytest ...`). Never call `python`/`pip`/`pytest` bare.
- reST docstrings; strict type hints.
- No magic numbers/paths in code bodies; no silent failures except the one deliberate "keep going" path specified here.
- The test suite is Qt-free and headless — do **not** add tests that construct `ImpedanceViewer` or any Qt widget.
- Keyword set is exactly: `channel`, `impedance`, `units` (always); `name`, `contact_id`, `region` (probe only).

---

### Task 1: Extend `ProbeMap` with `contact_ids` and `regions`

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/probe.py` (`ProbeMap`, `load_probe`)
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ProbeMap(order: np.ndarray, names: list[str], contact_ids: list[str] | None = None, regions: list[str] | None = None)`. `load_probe(path)` populates `contact_ids`/`regions` (both `None` when the probe file omits them).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_probe.py`:

```python
def test_load_probe_carries_contact_ids_and_regions() -> None:
    probe = load_probe(FIXTURE)
    assert probe.contact_ids == ["00", "01", "02", "03"]
    assert probe.regions == ["A", "B", "C", "D"]


def test_load_probe_leaves_ids_and_regions_none_when_absent(tmp_path) -> None:
    path = tmp_path / "bare.json"
    path.write_text(
        '{"specification": "probeinterface", "version": "0.3.2", "probes": [{'
        '"ndim": 2, "si_units": "um", "annotations": {}, "contact_annotations": {}, '
        '"contact_positions": [[0, 0], [0, 100]], '
        '"contact_plane_axes": [[0, 1], [0, 1]], '
        '"contact_shapes": ["circle", "circle"], '
        '"contact_shape_params": [{"radius": 5}, {"radius": 5}], '
        '"device_channel_indices": [0, 1]}]}'
    )
    probe = load_probe(path)
    assert probe.contact_ids is None
    assert probe.regions is None
    assert probe.names == ["ch00", "ch01"]  # fallback unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_probe.py::test_load_probe_carries_contact_ids_and_regions tests/test_probe.py::test_load_probe_leaves_ids_and_regions_none_when_absent -v`
Expected: FAIL — `ProbeMap` has no `contact_ids`/`regions` (AttributeError / unexpected keyword).

- [ ] **Step 3: Extend `ProbeMap` and `load_probe`**

In `probe.py`, add two fields to `ProbeMap` (defaults keep existing constructions valid):

```python
@dataclass(frozen=True)
class ProbeMap:
    """Channel reordering map derived from a probeinterface file.

    :param order: For displayed channel ``k``, the raw acquisition channel index
        (``device_channel_indices`` in contact order).
    :param names: Display name per contact-ordered channel.
    :param contact_ids: probeinterface ``contact_id`` per channel, or ``None``
        when the file omits them.
    :param regions: ``brain_region`` annotation per channel, or ``None`` when
        absent.
    """

    order: np.ndarray
    names: list[str]
    contact_ids: list[str] | None = None
    regions: list[str] | None = None
```

Rewrite the body of `load_probe` (after `order` is computed) to capture both and reuse them for `names`:

```python
    regions_raw = probe.contact_annotations.get("brain_region")
    ids_raw = probe.contact_ids
    contact_ids = [str(i) for i in ids_raw] if ids_raw is not None else None
    regions = [str(r) for r in regions_raw] if regions_raw is not None else None
    if regions is not None and contact_ids is not None:
        names = [f"{r} {i}" for r, i in zip(regions, contact_ids)]
    elif contact_ids is not None:
        names = list(contact_ids)
    else:
        names = [f"ch{k:0>2d}" for k in range(order.size)]
    return ProbeMap(order=order, names=names, contact_ids=contact_ids, regions=regions)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_probe.py -v`
Expected: PASS (all probe tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/probe.py tests/test_probe.py
git commit -m "feat(probe): expose contact_ids and regions on ProbeMap"
```

---

### Task 2: Replace `labels` with a per-cell `fields` array on the source

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/impedance.py` (`ImpedanceGridSource`, `build_grid_source`)
- Test: `tests/test_impedance.py`

**Interfaces:**
- Consumes: `ProbeMap.contact_ids`/`regions` from Task 1.
- Produces: `ImpedanceGridSource.fields: np.ndarray` — a `(n_rows, n_cols)` object array; each occupied cell holds `{"channel": int, "units": str, "name": str}` plus `"contact_id"` and `"region"` when a probe supplied them; empty cells hold `None`. The old `labels` attribute is removed.

- [ ] **Step 1: Write/adjust the tests**

In `tests/test_impedance.py`, **replace** the two `source.labels` assertions:

- In `test_build_grid_source_no_probe_is_a_strip`, replace the `labels` line with:

```python
    assert [source.fields[0, c]["name"] for c in range(4)] == ["R1", "R2", "R3", "R4"]
    assert source.fields[0, 0] == {"channel": 1, "units": "kOhm", "name": "R1"}
    assert "contact_id" not in source.fields[0, 0]  # no probe -> no probe keys
```

- In `test_build_grid_source_maps_via_device_channel_indices`, replace the `labels` line with:

```python
    assert [source.fields[r, 0]["name"] for r in range(4)] == ["A 00", "B 01", "C 02", "D 03"]
    # contact 0 -> acquisition channel order[0]+1 = 4, region "A", id "00"
    assert source.fields[0, 0] == {
        "channel": 4, "units": "kOhm", "name": "A 00", "contact_id": "00", "region": "A",
    }
```

Add a new test for empty cells in a topo grid (all four cells filled here, so assert None never appears where a contact sits and dict shape is right):

```python
def test_build_grid_source_fields_align_with_grid(cfg) -> None:
    data = read_impedance(FIXTURES / "impedance_1row.csv", cfg)
    source = build_grid_source(data, load_probe(PROBE_TOPO), probe_layout(PROBE_TOPO))
    assert source.fields.shape == source.grids[0].shape == (2, 2)
    # topo places contact with region "A" (id "00", channel 4) at grid (row1,col1)
    assert source.fields[1, 1]["region"] == "A"
    assert source.fields[1, 1]["channel"] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_impedance.py -v`
Expected: FAIL — `ImpedanceGridSource` has no `fields` attribute.

- [ ] **Step 3: Implement the source change**

In `impedance.py`, in `ImpedanceGridSource` replace the `labels` field with `fields` and update its docstring:

```python
    :param fields: ``(n_rows, n_cols)`` object array of per-cell field dicts for
        annotation templating (``channel``/``units``/``name`` always, plus
        ``contact_id``/``region`` when a probe was supplied); ``None`` for empty
        cells.
```

```python
    fields: np.ndarray
```

In `build_grid_source`, replace the `cell_labels` block with a `cell_fields` builder (keep the existing `labels`/`wanted` locals that feed it):

```python
    cell_fields = np.full((n_rows, n_cols), None, dtype=object)
    for k in range(len(wanted)):
        cell = {"channel": int(wanted[k]), "units": data.units, "name": labels[k]}
        if probe is not None:
            if probe.contact_ids is not None:
                cell["contact_id"] = probe.contact_ids[k]
            if probe.regions is not None:
                cell["region"] = probe.regions[k]
        cell_fields[row[k], col[k]] = cell
```

Update the constructor call to pass `fields=cell_fields` instead of `labels=cell_labels`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_impedance.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/impedance.py tests/test_impedance.py
git commit -m "feat(impedance): carry per-cell annotation fields on the source"
```

---

### Task 3: Add the Qt-free `format_cell` helper

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/impedance.py` (add helper + `import string`)
- Test: `tests/test_impedance.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `format_cell(template: str, fields: Mapping[str, Any]) -> str` — named substitution where a missing key renders `""` and a format spec that fails on an empty value also renders `""` (never raises).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_impedance.py` (import `format_cell` in the existing import block):

```python
def test_format_cell_named_and_multiline() -> None:
    out = format_cell("R{channel}\n{impedance:.0f}", {"channel": 4, "impedance": 40.0})
    assert out == "R4\n40"


def test_format_cell_missing_key_is_empty() -> None:
    assert format_cell("{region}", {"channel": 1}) == ""


def test_format_cell_bad_spec_on_missing_value_is_empty() -> None:
    # typo: 'impdance' is absent, and the numeric spec must not raise
    assert format_cell("{impdance:.0f}", {"impedance": 40.0}) == ""


def test_format_cell_formats_present_numeric() -> None:
    assert format_cell("{impedance:.1f}", {"impedance": 15.0}) == "15.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_impedance.py -k format_cell -v`
Expected: FAIL — `format_cell` is not defined.

- [ ] **Step 3: Implement the helper**

Add `import string` to the imports of `impedance.py`, then add:

```python
class _BlankMissingFormatter(string.Formatter):
    """``str.Formatter`` that renders unknown/unformattable fields as empty.

    Keeps a live-edited GUI annotation template usable across blocks with and
    without a probe: an absent keyword, or a numeric spec applied to an absent
    (empty) value, yields ``""`` rather than raising.
    """

    def get_value(self, key: Any, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        if isinstance(key, str):
            return kwargs.get(key, "")
        return super().get_value(key, args, kwargs)

    def format_field(self, value: Any, format_spec: str) -> str:
        try:
            return super().format_field(value, format_spec)
        except (ValueError, TypeError):
            return ""


_CELL_FORMATTER = _BlankMissingFormatter()


def format_cell(template: str, fields: Mapping[str, Any]) -> str:
    """Render one annotation cell from a named-field template.

    :param template: A ``str.format``-style template using named fields, e.g.
        ``"R{channel}\\n{impedance:.0f}"``.
    :param fields: The available field values for this cell.
    :returns: The formatted label; missing fields and failed specs render empty.
    """
    return _CELL_FORMATTER.vformat(template, (), dict(fields))
```

Ensure `Mapping` is imported from `typing` (it is: line uses `from typing import Any, Sequence` — add `Mapping`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_impedance.py -k format_cell -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/impedance.py tests/test_impedance.py
git commit -m "feat(impedance): add format_cell keyword templating helper"
```

---

### Task 4: Render keyword annotations in the viewer

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/viewers/impedance_view.py` (`_default_params`, `_refresh_annotations`)

**Interfaces:**
- Consumes: `ImpedanceGridSource.fields` (Task 2) and `format_cell` (Task 3).
- Produces: no new interface; viewer behavior only.

No automated test — the suite is Qt-free (see Global Constraints). Verification is the full headless suite (must stay green) plus a manual launch.

- [ ] **Step 1: Update the default annotation format**

In `_default_params`, change:

```python
        {"name": "annotation_format", "type": "str", "value": "R{channel}\n{impedance:.0f}"},
```

- [ ] **Step 2: Use fields + `format_cell` in `_refresh_annotations`**

Replace the body of the `col` loop so it merges the cell's static fields with the frequency-dependent `impedance` value, formats via the Qt-free helper (imported **locally** to avoid the `builders` ⇄ `impedance_view` import cycle), and skips blank results:

```python
        from tdt_ephyviewer_explorer.impedance import format_cell

        template = str(self.params["annotation_format"])
        for row in range(grid.shape[0]):
            for col in range(grid.shape[1]):
                value = grid[row, col]
                if np.isnan(value):
                    continue
                fields = self.source.fields[row, col] or {}
                text = format_cell(template, {**fields, "impedance": float(value)})
                if not text.strip():
                    continue
                fraction = float(np.clip((value - vmin) / (vmax - vmin), 0.0, 1.0))
                red, green, blue = colormap.map(fraction, mode="float")[:3]
                luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                item = pg.TextItem(
                    text, color="k" if luminance > 0.5 else "w", anchor=(0.5, 0.5)
                )
                item.setPos(col + 0.5, row + 0.5)
                self.plot.addItem(item)
                self._texts.append(item)
```

(Drop the now-unused `template = str(self.params["annotation_format"])` line that preceded the loop, and delete the old value-only `TextItem` construction it replaces.)

- [ ] **Step 3: Run the full suite (must stay green) and confirm the module imports**

Run: `uv run pytest`
Expected: PASS (no regressions; suite is Qt-free).

Run: `uv run python -c "import tdt_ephyviewer_explorer.viewers.impedance_view"`
Expected: exits 0 — confirms no circular-import regression.

- [ ] **Step 4: Manual smoke check**

Launch a block with an impedance CSV and confirm each cell shows `R<channel>` over the impedance, and that editing `annotation_format` in the GUI (e.g. `"{region}\n{contact_id}\n{impedance:.0f} {units}"`) re-renders without crashing on a probe-less block.

Run: `uv run tdt-explore --tank "<tank dir>"`
Expected: cells annotated with channel + impedance; format edits apply live; missing fields render blank.

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/viewers/impedance_view.py
git commit -m "feat(impedance-view): keyword-driven cell annotations"
```

---

## Self-Review

**Spec coverage:**
- Keyword set (`channel`/`impedance`/`units`/`name`/`contact_id`/`region`) → Tasks 1–2 (fields) + `impedance` injected in Task 4.
- Named-field `format_map` model → Task 3 (`format_cell`).
- Default cell `R{channel}` / `{impedance:.0f}` → Task 4 Step 1.
- Missing/typo field → empty, keep drawing → Task 3 helper + Task 4 skip-blank.
- `ProbeMap` gains `contact_ids`/`regions` → Task 1.
- `labels` replaced by `fields` (name folded in) → Task 2.
- Non-goals (no Hydra seeding, footer unchanged) → untouched.
- Tests enumerated in spec → Tasks 1–3 (probe ids/regions, fields shape/content with & without probe, `format_cell` behaviors).

**Placeholder scan:** none — every code/test step is concrete.

**Type consistency:** `format_cell(template, fields)`, `ProbeMap(order, names, contact_ids, regions)`, and `source.fields` used identically across Tasks 1–4. `channel` is `int`, `impedance` injected as `float`, probe keys are `str`.
