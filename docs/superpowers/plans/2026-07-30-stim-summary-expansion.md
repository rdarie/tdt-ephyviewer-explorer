# Expanded Stimulation Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report, per active stim voice, the channels stimulated and the amplitude and frequency ranges delivered, as child rows under each store in the `tdt-metadata` browser.

**Architecture:** All reduction and formatting lives in `metadata/stim.py`, which is Qt-free and unit-tested without a block on disk. `metadata/window.py` only places strings into tree rows. No new I/O: every figure comes from the parameter array the tier-2 read already loads.

**Tech Stack:** Python 3.12, NumPy, Hydra (OmegaConf), PySide/Qt via ephyviewer, pytest.

**Spec:** `docs/superpowers/specs/2026-07-30-stim-summary-expansion-design.md`

## Global Constraints

- Run everything through the venv: `uv run pytest`, `uv run python`. Never bare `python`/`pip`.
- reST docstrings with `:param:`/`:returns:` on every public function and dataclass.
- Strict type hints on every signature.
- No magic numbers: unit conversions, unit labels, and display caps live in `config/metadata/default.yaml`, never as literals in `stim.py` or `window.py`.
- The test suite stays Qt-free and headless except `tests/test_metadata_window.py`, which already gates on `pytest.importorskip("ephyviewer")`.
- Commit after each task. Never `git add` a path listed in `.gitignore`.
- The en dash `–` separates range bounds; the middot `·` separates clauses. Both are literal in the source.
- Amplitudes are stored **negative** for cathodic pulses. Any amplitude test is `!= 0`, never `> 0`.

---

### Task 1: Config keys and `StimConfig` fields

Adds the five settings the later tasks read, and widens `StimConfig` to carry them. Nothing consumes them yet.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/config/metadata/default.yaml:14-16`
- Modify: `src/tdt_ephyviewer_explorer/metadata/stim.py:32-69`
- Test: `tests/test_metadata_stim.py:147-155`

**Interfaces:**
- Consumes: nothing.
- Produces: `StimConfig` fields `amp_prefix: str`, `per_prefix: str`, `per_to_hz: float`, `amp_units: str`, `max_channels_listed: int`, all populated by `stim_config_from(cfg)`.

- [ ] **Step 1: Write the failing test**

Replace the body of `test_stim_config_comes_from_the_packaged_config` in `tests/test_metadata_stim.py`:

```python
def test_stim_config_comes_from_the_packaged_config() -> None:
    sc, columns = stim_config_from(load_config())
    assert sc.store_pattern == "eS?p"
    assert sc.voices == ("A", "B", "C", "D")
    assert sc.chan_prefix == "chan"
    assert sc.count_prefix == "count"
    assert sc.amp_prefix == "amp"
    assert sc.per_prefix == "per"
    assert sc.per_to_hz == 1000.0
    assert sc.amp_units == "µA"
    assert sc.max_channels_listed == 5
    assert len(columns) == 24
    assert columns[:3] == ["perA", "countA", "ampA"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_metadata_stim.py::test_stim_config_comes_from_the_packaged_config -v`
Expected: FAIL with `AttributeError: 'StimConfig' object has no attribute 'amp_prefix'`

- [ ] **Step 3: Add the config keys**

In `src/tdt_ephyviewer_explorer/config/metadata/default.yaml`, replace the two `*_prefix` lines and their comment with:

```yaml
    # Column prefixes: a voice is stimulating at an event when chan{V} > 0 and
    # amp{V} != 0 (amplitudes are stored negative for cathodic pulses). count{V} is
    # pulses per train, per{V} the within-train interval.
    chan_prefix: chan
    count_prefix: count
    amp_prefix: amp
    per_prefix: per
    # freq_Hz = per_to_hz / per{V}. per is in milliseconds.
    per_to_hz: 1000.0
    # Amplitude unit label. Display only; no conversion is applied.
    amp_units: "µA"
    # Channel tokens listed per voice before the list truncates to a count.
    max_channels_listed: 5
```

- [ ] **Step 4: Widen `StimConfig`**

In `stim.py`, extend the dataclass and its docstring:

```python
@dataclass(frozen=True)
class StimConfig:
    """Resolved ``metadata.stim`` settings.

    :param store_pattern: fnmatch pattern selecting parameter stores.
    :param schema: Name of the column schema in ``schemas``.
    :param voices: Voice suffixes appended to each parameter name.
    :param chan_prefix: Column prefix whose value marks a voice wired when ``> 0``.
    :param count_prefix: Column prefix giving pulses per train.
    :param amp_prefix: Column prefix giving amplitude; ``!= 0`` marks charge delivered.
    :param per_prefix: Column prefix giving the within-train interval.
    :param per_to_hz: Numerator of ``freq_Hz = per_to_hz / per``.
    :param amp_units: Amplitude unit label, for display only.
    :param max_channels_listed: Channel tokens shown before the list truncates.
    """

    store_pattern: str
    schema: str
    voices: tuple[str, ...]
    chan_prefix: str
    count_prefix: str
    amp_prefix: str
    per_prefix: str
    per_to_hz: float
    amp_units: str
    max_channels_listed: int
```

and extend the constructor call in `stim_config_from`:

```python
        StimConfig(
            store_pattern=str(node.store_pattern),
            schema=schema,
            voices=tuple(str(v) for v in node.voices),
            chan_prefix=str(node.chan_prefix),
            count_prefix=str(node.count_prefix),
            amp_prefix=str(node.amp_prefix),
            per_prefix=str(node.per_prefix),
            per_to_hz=float(node.per_to_hz),
            amp_units=str(node.amp_units),
            max_channels_listed=int(node.max_channels_listed),
        ),
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_metadata_stim.py tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/config/metadata/default.yaml src/tdt_ephyviewer_explorer/metadata/stim.py tests/test_metadata_stim.py
git commit -m "feat(stim): config for amplitude, period and channel display"
```

---

### Task 2: `format_channels`

A pure function turning a channel set into a bounded string. No dependency on the rest of the feature.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/stim.py`
- Test: `tests/test_metadata_stim.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `format_channels(channels: Sequence[int], max_listed: int) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metadata_stim.py`, and add `format_channels` to the import block at the top of the file:

```python
def test_format_channels_collapses_contiguous_runs() -> None:
    assert format_channels((1, 2, 3, 4, 5, 6, 7, 8, 12, 14), 5) == "1–8,12,14"


def test_format_channels_names_the_count_for_a_lone_range() -> None:
    assert format_channels(tuple(range(1, 33)), 5) == "1–32 (32 ch)"


def test_format_channels_truncates_a_long_scattered_list() -> None:
    assert format_channels((1, 3, 5, 7, 9, 11, 13, 15, 17), 5) == "1,3,5,7,9,… (17 ch)"


def test_format_channels_leaves_a_single_channel_bare() -> None:
    assert format_channels((12,), 5) == "12"


def test_format_channels_keeps_a_two_long_run_as_two_numbers() -> None:
    assert format_channels((4, 5), 5) == "4,5"


def test_format_channels_of_nothing_is_empty() -> None:
    assert format_channels((), 5) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_stim.py -k format_channels -v`
Expected: FAIL with `ImportError: cannot import name 'format_channels'`

- [ ] **Step 3: Implement**

Add to `stim.py`:

```python
def format_channels(channels: Sequence[int], max_listed: int) -> str:
    """Render a channel set compactly, collapsing runs and capping the width.

    Runs of three or more consecutive channels become ``a–b`` tokens; shorter runs
    stay as individual numbers. Past ``max_listed`` tokens the list truncates with an
    ellipsis. A ``(N ch)`` suffix carries the distinct channel count whenever the text
    alone does not state it -- that is, when the list truncated or rendered as a
    single range.

    :param channels: Distinct channels, ascending.
    :param max_listed: Tokens to show before truncating.
    :returns: The rendered list, or ``""`` for no channels.
    """
    if not channels:
        return ""
    ordered = sorted(channels)
    tokens: list[str] = []
    start = prev = ordered[0]
    for value in list(ordered[1:]) + [None]:
        if value is not None and value == prev + 1:
            prev = value
            continue
        if prev - start >= 2:
            tokens.append(f"{start}–{prev}")
        else:
            tokens.extend(str(x) for x in range(start, prev + 1))
        if value is not None:
            start = prev = value

    truncated = len(tokens) > max_listed
    text = ",".join(tokens[:max_listed]) + (",…" if truncated else "")
    lone_range = len(tokens) == 1 and "–" in tokens[0]
    if truncated or lone_range:
        text = f"{text} ({len(ordered)} ch)"
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata_stim.py -k format_channels -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/stim.py tests/test_metadata_stim.py
git commit -m "feat(stim): compact channel-set formatting"
```

---

### Task 3: `format_range`

The second pure formatter. Independent of Task 2.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/stim.py`
- Test: `tests/test_metadata_stim.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `format_range(lo: float, hi: float, unit: str, sign: str = "") -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metadata_stim.py`, adding `format_range` to the import block:

```python
def test_format_range_spans_two_values() -> None:
    assert format_range(100.0, 800.0, "µA") == "100–800 µA"


def test_format_range_collapses_when_the_bounds_match() -> None:
    assert format_range(200.0, 200.0, "µA") == "200 µA"


def test_format_range_prefixes_the_sign_once() -> None:
    assert format_range(100.0, 800.0, "µA", "-") == "-100–800 µA"
    assert format_range(100.0, 800.0, "µA", "±") == "±100–800 µA"


def test_format_range_strips_a_trailing_zero_decimal() -> None:
    assert format_range(20.0, 20.0, "Hz") == "20 Hz"


def test_format_range_keeps_a_meaningful_decimal() -> None:
    assert format_range(0.5, 12.5, "Hz") == "0.5–12.5 Hz"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_stim.py -k format_range -v`
Expected: FAIL with `ImportError: cannot import name 'format_range'`

- [ ] **Step 3: Implement**

Add to `stim.py`:

```python
def _number(value: float) -> str:
    """Render one figure to a single decimal, dropping a trailing ``.0``.

    :param value: The figure.
    :returns: Its rendering, e.g. ``"20"`` or ``"12.5"``.
    """
    return f"{value:.1f}".rstrip("0").rstrip(".")


def format_range(lo: float, hi: float, unit: str, sign: str = "") -> str:
    """Render a range, collapsing it when both bounds agree.

    ``sign`` prefixes the whole range rather than each bound: ``-100–800 µA`` reads
    where ``-800–-100 µA`` does not.

    :param lo: Lower bound.
    :param hi: Upper bound.
    :param unit: Unit label appended after a space.
    :param sign: Polarity marker prefixed to the range, if any.
    :returns: The rendered range.
    """
    low, high = _number(lo), _number(hi)
    body = low if low == high else f"{low}–{high}"
    return f"{sign}{body} {unit}".strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_metadata_stim.py -k format_range -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/stim.py tests/test_metadata_stim.py
git commit -m "feat(stim): range formatting with a single sign prefix"
```

---

### Task 4: Tighten the activity mask

`summarize_stim` starts taking a `StimConfig` instead of four loose arguments, and a voice counts only where it delivers charge. This changes the two numbers the browser already shows, so the existing tests move with it.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/stim.py:72-123,126-158`
- Test: `tests/test_metadata_stim.py:33-144`

**Interfaces:**
- Consumes: `StimConfig` from Task 1.
- Produces: `summarize_stim(store: str, data: np.ndarray, column_names: Sequence[str], settings: StimConfig) -> StimSummary`. The old positional prefixes are gone; `read_stim_summaries` and the tests are the only callers.

- [ ] **Step 1: Rewrite the test helper and the fixtures it feeds**

In `tests/test_metadata_stim.py`, replace `_summarize` and add a config builder. Every fixture that means "this voice stimulates" must now set an amplitude:

```python
from tdt_ephyviewer_explorer.metadata.stim import StimConfig

SETTINGS = StimConfig(
    store_pattern="eS?p", schema="iz_param_names", voices=VOICES,
    chan_prefix="chan", count_prefix="count", amp_prefix="amp", per_prefix="per",
    per_to_hz=1000.0, amp_units="µA", max_channels_listed=5,
)


def _summarize(data: np.ndarray, settings: StimConfig = SETTINGS) -> StimSummary:
    return summarize_stim("eS1p", data, COLS, settings)
```

Then update each existing fixture to give its stimulating voices an amplitude. The full set of edits:

```python
def test_single_active_voice_one_pulse_each() -> None:
    data = _blank(10)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 10, 1)


def test_sweeping_a_channel_counts_distinct_combinations() -> None:
    data = _blank(6)
    data[_row("chanA")] = [1, 1, 2, 2, 3, 3]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 6, 3)


def test_two_active_voices_combine_into_pairs() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 1, 2, 2]
    data[_row("chanB")] = [5, 6, 5, 6]
    data[_row("countA")] = 1.0
    data[_row("countB")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("ampB")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 4, 4)


def test_count_greater_than_one_yields_more_pulses_than_events() -> None:
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    data[_row("ampA")] = -100.0
    assert _summarize(data).n_pulses == 15


def test_concurrent_voices_do_not_double_count_pulses() -> None:
    # A and B fire together; a 3-pulse train is 3 pulses in time, not 6.
    data = _blank(5)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 3.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = 2.0
    data[_row("countB")] = 3.0
    data[_row("ampB")] = -100.0
    assert _summarize(data).n_pulses == 15


def test_pulses_take_the_max_across_voices() -> None:
    data = _blank(1)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 2.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = 1.0
    data[_row("countB")] = 5.0
    data[_row("ampB")] = -100.0
    assert _summarize(data).n_pulses == 5


def test_idle_voice_with_nonzero_params_does_not_inflate_combinations() -> None:
    # C never has a channel, so its wobbling amp/per stay out of the combination count.
    data = _blank(3)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("ampC")] = [-1.0, -2.0, -3.0]
    data[_row("perC")] = 0.983
    assert _summarize(data) == StimSummary("eS1p", 3, 1)


def test_inactive_voice_events_contribute_no_pulses() -> None:
    data = _blank(4)
    data[_row("chanA")] = [1, 0, 1, 0]  # voice A idle on two events
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    assert _summarize(data).n_pulses == 2


def test_no_active_voice_anywhere_is_all_zeros() -> None:
    data = _blank(7)
    data[_row("ampA")] = -100.0  # amp set but chan == 0: not stimulation
    assert _summarize(data) == StimSummary("eS1p", 0, 0)


def test_negative_chan_is_not_active() -> None:
    data = _blank(3)
    data[_row("chanA")] = -1.0
    data[_row("ampA")] = -100.0
    assert _summarize(data) == StimSummary("eS1p", 0, 0)
```

- [ ] **Step 2: Rewrite the two tests that asserted the old rule**

Replace `test_active_voice_with_zero_count_never_contributes_pulses` outright, and add the case that names the new rule:

```python
def test_a_zero_amplitude_return_electrode_is_not_a_voice() -> None:
    # The reference block's voice B is the anode: chanB sweeps, but countB and ampB are
    # 0 throughout, so B delivers no charge. It is not stimulation, so it contributes
    # neither pulses nor combinations -- only chanA's single setting remains.
    data = _blank(5)
    data[_row("chanA")] = [1, 1, 0, 1, 0]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = [0, 5, 6, 0, 7]
    data[_row("countB")] = 0.0
    summary = _summarize(data)
    assert summary.n_pulses == 3  # only events 0, 1, 3 have chanA > 0
    assert summary.n_combinations == 1


def test_an_active_voice_with_zero_count_contributes_combinations_not_pulses() -> None:
    # B delivers charge (ampB != 0) but its trains are empty, so it joins the
    # combination count while adding no pulses of its own.
    data = _blank(5)
    data[_row("chanA")] = [1, 1, 0, 1, 0]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = [0, 5, 6, 0, 7]
    data[_row("countB")] = 0.0
    data[_row("ampB")] = -50.0
    summary = _summarize(data)
    assert summary.n_pulses == 3
    # Events where nothing is on are excluded; the four remaining (chanA, chanB) pairs
    # are (1,0), (1,5), (0,6), (1,0) again, (0,7) -- four distinct.
    assert summary.n_combinations == 4
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_stim.py -v`
Expected: FAIL — `TypeError: summarize_stim() takes 6 positional arguments`, and the two new tests failing on counts.

- [ ] **Step 4: Rewrite `summarize_stim`**

Replace the function in `stim.py`:

```python
def _voice_mask(
    data: np.ndarray, index: dict[str, int], voice: str, settings: StimConfig
) -> np.ndarray:
    """The per-event boolean mask of when one voice is delivering charge.

    ``chan == 0`` is Synapse's dummy value for "no stimulation" and ``amp == 0`` is a
    voice configured but delivering nothing. Amplitudes are negative for cathodic
    pulses, so the amplitude test is ``!= 0``. A schema without the voice's amplitude
    column degrades to the channel test alone.

    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param index: Column name to row number.
    :param voice: Voice suffix.
    :param settings: Resolved stim settings.
    :returns: Boolean array of length ``n_events``.
    """
    on = data[index[f"{settings.chan_prefix}{voice}"]] > 0
    amp_key = f"{settings.amp_prefix}{voice}"
    if amp_key in index:
        on = on & (data[index[amp_key]] != 0)
    return on


def summarize_stim(
    store: str,
    data: np.ndarray,
    column_names: Sequence[str],
    settings: StimConfig,
) -> StimSummary:
    """Reduce a stim parameter block to headline figures and per-voice ranges.

    A voice is *active* when it delivers charge -- ``chan > 0`` and ``amp != 0`` -- for
    at least one event. Only active voices' columns take part, so an idle voice whose
    other parameters happen to vary cannot inflate the combination count, and a return
    electrode held at zero amplitude is not counted as stimulation.

    Pulses per event are the **maximum** ``count`` across that event's on voices, not
    the sum: voices fire concurrently, so a 3-pulse train on two voices is three pulses
    in time.

    :param store: Store code, carried into the result.
    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param column_names: Row labels, one per row of ``data``.
    :param settings: Resolved stim settings.
    :returns: The summary.
    :raises StimSchemaMismatch: If ``data`` has a different row count than
        ``column_names`` -- labelling the rows anyway would silently mis-report.
    """
    if data.shape[0] != len(column_names):
        raise StimSchemaMismatch(
            f"{store}: {data.shape[0]} rows but schema names {len(column_names)} columns"
        )
    index = {name: i for i, name in enumerate(column_names)}
    n_events = int(data.shape[1])

    masks: dict[str, np.ndarray] = {}
    for voice in settings.voices:
        if f"{settings.chan_prefix}{voice}" not in index:
            continue
        on = _voice_mask(data, index, voice, settings)
        if bool(on.any()):
            masks[voice] = on
    if not masks or n_events == 0:
        return StimSummary(store, 0, 0)

    any_on = np.zeros(n_events, dtype=bool)
    for on in masks.values():
        any_on |= on
    combo_rows = [i for name, i in index.items() if any(name.endswith(v) for v in masks)]
    block = data[np.ix_(combo_rows, np.flatnonzero(any_on))]
    n_combinations = int(np.unique(block.T, axis=0).shape[0])

    per_event = np.zeros(n_events, dtype=float)
    for voice, on in masks.items():
        count_key = f"{settings.count_prefix}{voice}"
        if count_key not in index:
            continue
        per_event = np.maximum(per_event, np.where(on, data[index[count_key]], 0.0))
    return StimSummary(store, int(per_event.sum()), n_combinations)
```

- [ ] **Step 5: Update the one production caller**

In `read_stim_summaries`, replace the `summarize_stim(...)` call with the new signature:

```python
                summaries.append(summarize_stim(name, data, columns, settings))
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_metadata_stim.py -v`
Expected: PASS

- [ ] **Step 7: Run the full suite — this task changes reported numbers**

Run: `uv run pytest`
Expected: PASS. `tests/test_metadata_window.py` passes its own `StimSummary` values in directly, so it is unaffected.

- [ ] **Step 8: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/stim.py tests/test_metadata_stim.py
git commit -m "fix(stim): a voice counts only where it delivers charge"
```

---

### Task 5: `VoiceSummary` and the per-voice reduction

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/stim.py`
- Test: `tests/test_metadata_stim.py`

**Interfaces:**
- Consumes: `_voice_mask`, `summarize_stim`, `StimConfig`.
- Produces: `VoiceSummary(voice: str, channels: tuple[int, ...], amp_min: float, amp_max: float, amp_sign: str, freq_min_hz: float | None, freq_max_hz: float | None)`, and `StimSummary.voices: tuple[VoiceSummary, ...]` defaulting to `()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metadata_stim.py`, adding `VoiceSummary` to the import block:

```python
def test_voice_rows_carry_channels_amplitude_and_frequency() -> None:
    data = _blank(3)
    data[_row("chanA")] = [1, 2, 3]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = [-100.0, -400.0, -800.0]
    data[_row("perA")] = [100.0, 50.0, 20.0]  # ms -> 10, 20, 50 Hz
    (voice,) = _summarize(data).voices
    assert voice == VoiceSummary("A", (1, 2, 3), 100.0, 800.0, "-", 10.0, 50.0)


def test_only_active_voices_get_a_row() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("chanB")] = 7.0  # wired, but ampB == 0: no charge, no row
    assert [v.voice for v in _summarize(data).voices] == ["A"]


def test_voice_rows_follow_configured_voice_order() -> None:
    data = _blank(1)
    for voice, channel in (("C", 3), ("A", 1)):
        data[_row(f"chan{voice}")] = float(channel)
        data[_row(f"count{voice}")] = 1.0
        data[_row(f"amp{voice}")] = -100.0
    assert [v.voice for v in _summarize(data).voices] == ["A", "C"]


def test_ranges_ignore_events_where_the_voice_is_off() -> None:
    # The stray -5 µA sits on an event where chanA is 0, so it must not lower amp_min.
    data = _blank(3)
    data[_row("chanA")] = [1, 0, 1]
    data[_row("countA")] = 1.0
    data[_row("ampA")] = [-100.0, -5.0, -800.0]
    (voice,) = _summarize(data).voices
    assert (voice.amp_min, voice.amp_max) == (100.0, 800.0)
    assert voice.channels == (1,)


def test_mixed_polarity_is_marked() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = [-100.0, 800.0]
    (voice,) = _summarize(data).voices
    assert voice.amp_sign == "±"
    assert (voice.amp_min, voice.amp_max) == (100.0, 800.0)


def test_anodic_only_amplitudes_are_marked_positive() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = 300.0
    (voice,) = _summarize(data).voices
    assert voice.amp_sign == "+"


def test_a_nonpositive_period_yields_no_frequency() -> None:
    data = _blank(2)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("perA")] = 0.0  # never divide by it
    (voice,) = _summarize(data).voices
    assert voice.freq_min_hz is None
    assert voice.freq_max_hz is None


def test_a_zero_period_event_drops_out_of_the_frequency_range() -> None:
    data = _blank(3)
    data[_row("chanA")] = 1.0
    data[_row("countA")] = 1.0
    data[_row("ampA")] = -100.0
    data[_row("perA")] = [100.0, 0.0, 25.0]
    (voice,) = _summarize(data).voices
    assert (voice.freq_min_hz, voice.freq_max_hz) == (10.0, 40.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_stim.py -k voice -v`
Expected: FAIL with `ImportError: cannot import name 'VoiceSummary'`

- [ ] **Step 3: Add the dataclass**

In `stim.py`, above `StimSummary`:

```python
@dataclass(frozen=True)
class VoiceSummary:
    """Parameters delivered by one active voice of a stim parameter store.

    :param voice: Voice suffix, e.g. ``"A"``.
    :param channels: Distinct channels stimulated, ascending.
    :param amp_min: Smallest amplitude *magnitude* delivered, in the configured units.
    :param amp_max: Largest amplitude magnitude delivered.
    :param amp_sign: ``"-"`` if every delivered amplitude was negative, ``"+"`` if
        every one was positive, ``"±"`` if both polarities appear, ``""`` if the
        schema names no amplitude column for this voice.
    :param freq_min_hz: Lowest within-train pulse frequency in Hz, or ``None`` when no
        event carried a positive period.
    :param freq_max_hz: Highest within-train pulse frequency in Hz, or ``None``.
    """

    voice: str
    channels: tuple[int, ...]
    amp_min: float
    amp_max: float
    amp_sign: str
    freq_min_hz: float | None
    freq_max_hz: float | None
```

and extend `StimSummary` with a defaulted field, documenting it:

```python
    store: str
    n_pulses: int
    n_combinations: int
    voices: tuple[VoiceSummary, ...] = ()
```

Add to the `StimSummary` docstring: `:param voices: One entry per active voice, in configured voice order.`

- [ ] **Step 4: Implement the per-voice reduction**

Add to `stim.py`:

```python
def _summarize_voice(
    voice: str,
    data: np.ndarray,
    index: dict[str, int],
    on: np.ndarray,
    settings: StimConfig,
) -> VoiceSummary:
    """Reduce one active voice's on-events to channels and parameter ranges.

    Every figure covers the on-events only; including the events where the voice is
    idle would pin each minimum to zero.

    :param voice: Voice suffix.
    :param data: Parameter block, shape ``(n_columns, n_events)``.
    :param index: Column name to row number.
    :param on: The voice's per-event mask, from :func:`_voice_mask`.
    :param settings: Resolved stim settings.
    :returns: The per-voice summary.
    """
    channels = tuple(
        int(c) for c in np.unique(data[index[f"{settings.chan_prefix}{voice}"]][on])
    )

    amp_min = amp_max = 0.0
    amp_sign = ""
    amp_key = f"{settings.amp_prefix}{voice}"
    if amp_key in index:
        amps = data[index[amp_key]][on]
        amps = amps[amps != 0]
        if amps.size:
            magnitudes = np.abs(amps)
            amp_min, amp_max = float(magnitudes.min()), float(magnitudes.max())
            negative, positive = bool((amps < 0).any()), bool((amps > 0).any())
            amp_sign = "±" if negative and positive else ("-" if negative else "+")

    freq_min: float | None = None
    freq_max: float | None = None
    per_key = f"{settings.per_prefix}{voice}"
    if per_key in index:
        periods = data[index[per_key]][on]
        periods = periods[periods > 0]
        if periods.size:
            frequencies = settings.per_to_hz / periods
            freq_min, freq_max = float(frequencies.min()), float(frequencies.max())

    return VoiceSummary(voice, channels, amp_min, amp_max, amp_sign, freq_min, freq_max)
```

- [ ] **Step 5: Return the voices from `summarize_stim`**

Replace the final `return` of `summarize_stim` with:

```python
    voices = tuple(
        _summarize_voice(voice, data, index, masks[voice], settings)
        for voice in settings.voices
        if voice in masks
    )
    return StimSummary(store, int(per_event.sum()), n_combinations, voices)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_metadata_stim.py -v`
Expected: PASS. The Task 4 tests compare against `StimSummary("eS1p", n, m)` whose `voices` defaults to `()`, so they now compare a populated tuple against the default and will fail — change each of those assertions to compare the fields instead:

```python
    summary = _summarize(data)
    assert (summary.n_pulses, summary.n_combinations) == (10, 1)
```

Apply that shape to every `== StimSummary(...)` assertion that describes an active voice. The three all-zero cases (`test_no_active_voice_anywhere_is_all_zeros`, `test_negative_chan_is_not_active`, `test_zero_events`) keep comparing whole objects, since `voices` really is `()` there.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/stim.py tests/test_metadata_stim.py
git commit -m "feat(stim): per-voice channel, amplitude and frequency ranges"
```

---

### Task 6: The voice line, and schema warnings

Assembles a voice's clauses into one string, and reports a schema that cannot supply them. Both are pure and Qt-free, so the window task stays trivial.

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/stim.py`
- Test: `tests/test_metadata_stim.py`

**Interfaces:**
- Consumes: `VoiceSummary`, `StimConfig`, `format_channels`, `format_range`.
- Produces: `format_voice_line(voice: VoiceSummary, settings: StimConfig) -> str` and `schema_warnings(column_names: Sequence[str], settings: StimConfig) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metadata_stim.py`, adding both names to the import block:

```python
def _voice(**kwargs: Any) -> VoiceSummary:
    fields: dict[str, Any] = dict(
        voice="A", channels=(1, 2, 3), amp_min=100.0, amp_max=800.0,
        amp_sign="-", freq_min_hz=10.0, freq_max_hz=50.0,
    )
    fields.update(kwargs)
    return VoiceSummary(**fields)


def test_voice_line_joins_channels_amplitude_and_frequency() -> None:
    assert format_voice_line(_voice(), SETTINGS) == "ch 1,2,3 · -100–800 µA · 10–50 Hz"


def test_voice_line_drops_the_frequency_clause_when_there_is_none() -> None:
    line = format_voice_line(_voice(freq_min_hz=None, freq_max_hz=None), SETTINGS)
    assert line == "ch 1,2,3 · -100–800 µA"


def test_voice_line_drops_the_amplitude_clause_when_the_schema_has_none() -> None:
    line = format_voice_line(_voice(amp_sign="", amp_min=0.0, amp_max=0.0), SETTINGS)
    assert line == "ch 1,2,3 · 10–50 Hz"


def test_voice_line_honours_the_channel_cap() -> None:
    voice = _voice(channels=(1, 3, 5, 7, 9, 11, 13, 15, 17))
    assert format_voice_line(voice, SETTINGS).startswith("ch 1,3,5,7,9,… (17 ch) · ")


def test_schema_warnings_name_the_missing_column() -> None:
    columns = [c for c in COLS if c != "ampA"]
    (warning,) = schema_warnings(columns, SETTINGS)
    assert "ampA" in warning


def test_a_complete_schema_warns_about_nothing() -> None:
    assert schema_warnings(COLS, SETTINGS) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_stim.py -k "voice_line or schema_warnings or complete_schema" -v`
Expected: FAIL with `ImportError: cannot import name 'format_voice_line'`

- [ ] **Step 3: Implement**

Add to `stim.py`:

```python
def format_voice_line(voice: VoiceSummary, settings: StimConfig) -> str:
    """Render one voice's parameters as a single display line.

    Clauses the data could not supply are omitted rather than shown empty.

    :param voice: The per-voice summary.
    :param settings: Resolved stim settings, for the unit label and channel cap.
    :returns: e.g. ``"ch 1–8 · -100–800 µA · 10–50 Hz"``.
    """
    parts: list[str] = []
    if voice.channels:
        parts.append(f"ch {format_channels(voice.channels, settings.max_channels_listed)}")
    if voice.amp_sign:
        parts.append(
            format_range(voice.amp_min, voice.amp_max, settings.amp_units, voice.amp_sign)
        )
    if voice.freq_min_hz is not None and voice.freq_max_hz is not None:
        parts.append(format_range(voice.freq_min_hz, voice.freq_max_hz, "Hz"))
    return " · ".join(parts)


def schema_warnings(column_names: Sequence[str], settings: StimConfig) -> list[str]:
    """Report voices whose schema cannot supply a parameter this summary reports.

    The schema is the same for every store in a block, so this is checked once rather
    than per store. A missing amplitude column also weakens the activity test for that
    voice, which is why it is worth saying out loud.

    :param column_names: The named schema's column order.
    :param settings: Resolved stim settings.
    :returns: One warning per missing column, empty when the schema is complete.
    """
    present = set(column_names)
    out: list[str] = []
    for voice in settings.voices:
        if f"{settings.chan_prefix}{voice}" not in present:
            continue
        for prefix, reported in (
            (settings.amp_prefix, "amplitude"),
            (settings.per_prefix, "frequency"),
        ):
            column = f"{prefix}{voice}"
            if column not in present:
                out.append(
                    f"schema {settings.schema!r} has no {column}: "
                    f"voice {voice} reports no {reported}"
                )
    return out
```

- [ ] **Step 4: Emit the warnings from `read_stim_summaries`**

In `read_stim_summaries`, after `settings, columns = stim_config_from(cfg)` and before the `headers is None` guard, seed the warning list:

```python
    settings, columns = stim_config_from(cfg)
    summaries: list[StimSummary] = []
    warnings: list[str] = schema_warnings(columns, settings)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_metadata_stim.py -v`
Expected: PASS. `test_read_stim_summaries_without_headers_returns_a_single_warning` still holds — the packaged schema is complete, so `schema_warnings` adds nothing.

- [ ] **Step 6: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/stim.py tests/test_metadata_stim.py
git commit -m "feat(stim): voice display line and schema warnings"
```

---

### Task 7: Voice rows in the browser

**Files:**
- Modify: `src/tdt_ephyviewer_explorer/metadata/window.py:342-352`
- Test: `tests/test_metadata_window.py`

**Interfaces:**
- Consumes: `StimSummary.voices`, `format_voice_line`, `stim_config_from`.
- Produces: nothing further.

- [ ] **Step 1: Write the failing test**

In `tests/test_metadata_window.py`, extend the stim import and append the test:

```python
from tdt_ephyviewer_explorer.metadata.stim import StimSummary, VoiceSummary


def test_voice_rows_appear_under_their_store(qapp, monkeypatch, tmp_path) -> None:
    stim = (
        StimSummary(
            "eS1p", 15561, 1881,
            (
                VoiceSummary("A", (1, 2, 3, 4, 5, 6, 7, 8), 100.0, 800.0, "-", 10.0, 50.0),
                VoiceSummary("B", (12,), 200.0, 200.0, "-", 20.0, 20.0),
            ),
        ),
    )
    win = _window(monkeypatch, stim=stim)
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert "voice A ch 1–8 · -100–800 µA · 10–50 Hz" in lines
    assert "voice B ch 12 · -200 µA · 20 Hz" in lines


def test_a_store_with_no_active_voice_shows_only_its_headline(
    qapp, monkeypatch, tmp_path
) -> None:
    win = _window(monkeypatch, stim=(StimSummary("eS1p", 0, 0),))
    win.set_tank(_tank(tmp_path))
    win.expand_block("Epi_02_Green-260727-154827")
    lines = win.detail_lines("Epi_02_Green-260727-154827")
    assert "eS1p 0 pulses · 0 combinations" in lines
    assert not any(ln.startswith("voice ") for ln in lines)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_metadata_window.py -k voice -v`
Expected: FAIL — the first test's assertions find no `voice A` line.

- [ ] **Step 3: Implement**

`window.py` imports nothing from `stim` yet. Add the import after the `notes_panel` one, keeping the block alphabetical:

```python
from tdt_ephyviewer_explorer.metadata.stim import format_voice_line, stim_config_from
```

and replace the `elif summary.stim:` branch of `_rebuild_children`:

```python
        elif summary.stim:
            settings, _ = stim_config_from(self._cfg)
            stim = QtWidgets.QTreeWidgetItem(item, ["", "Stimulation", ""])
            for entry in summary.stim:
                store_row = QtWidgets.QTreeWidgetItem(
                    stim,
                    [
                        "",
                        entry.store,
                        f"{entry.n_pulses} pulses · {entry.n_combinations} combinations",
                    ],
                )
                for voice in entry.voices:
                    QtWidgets.QTreeWidgetItem(
                        store_row,
                        ["", f"voice {voice.voice}", format_voice_line(voice, settings)],
                    )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_metadata_window.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 6: Check it against a real block**

Run: `uv run tdt-metadata --tank "<a tank with stim>"`, expand a stimulated block, and confirm the voice rows read sensibly — plausible channels, amplitudes in the hundreds of µA, frequencies in the tens of Hz. A frequency of 1000 Hz or 0.02 Hz means `per` is not in milliseconds after all; fix `per_to_hz` in the config rather than in code, and say so.

- [ ] **Step 7: Commit**

```bash
git add src/tdt_ephyviewer_explorer/metadata/window.py tests/test_metadata_window.py
git commit -m "feat(metadata): show per-voice stim parameters"
```

---

## Notes for the implementer

- **Why the amplitude test is `!= 0`:** amplitudes are stored negative for cathodic pulses. `> 0` compiles, passes a naive test written with positive fixtures, and reports every real block as unstimulated.
- **Why combinations exclude all-off events:** an event where no voice delivers charge would otherwise contribute an all-zero row to the unique-row count, adding a combination that was never a setting.
- **Why pulses take the max, not the sum:** voices fire concurrently. This is pre-existing behavior; Task 4 changes only which events count.
- **Task 5, Step 6 is the fiddly one.** Adding `voices` to `StimSummary` breaks whole-object equality in the Task 4 tests. That is expected, and the step says exactly which assertions to reshape.
