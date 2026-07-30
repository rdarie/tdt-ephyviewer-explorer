# Expanded stimulation summary in `tdt-metadata`

**Date:** 2026-07-30
**Status:** Approved, ready for implementation planning

## Problem

The metadata browser reports one line per stim parameter store:

```
Stimulation
  eS1p    1240 pulses · 6 combinations
```

That is enough to know stimulation happened, but not enough to answer the question
actually asked while scanning a tank: *is this the block I am looking for?* Answering it
means opening the block. The parameters that identify a block — which channels were
stimulated, at what amplitudes, at what rates — are already in the array that produced
those two numbers, and are discarded.

A second, smaller problem: a voice is currently called *active* when `chan > 0` alone.
A voice wired to a channel but held at 0 µA therefore contributes its columns to the
combination count and its `count` to the pulse total, inflating both.

## Goals

- Report, per active voice, the channels stimulated and the amplitude and frequency
  ranges delivered.
- Keep the summary brief: the display grows with the block's complexity, not with the
  number of parameters that exist.
- Use one definition of "active" throughout, correcting the inflated counts.
- Add no I/O. Everything below comes from the array the tier-2 read already loads.

## Non-goals

- Per-voice pulse counts.
- A per-combination table (one row per distinct setting). Deferred; the design leaves
  room for it as a further child level under the store row.
- Any change to when stim data is read. The tiering in `summary.py` stands: text
  sidecars eagerly, `.tsq` headers and `eS1p` on expand only.

## Display

One grandchild row per active voice, under the existing store row:

```
Stimulation
  eS1p        980 pulses · 3 combinations
    voice A   ch 1–8 · 100–800 µA · 10–50 Hz
    voice B   ch 12 · 200 µA · 20 Hz
```

Voices appear in the order given by `metadata.stim.voices` (A, B, C, D), not in the order
they happen to fire. Inactive voices produce no row. A store with no active voice keeps
its existing `0 pulses · 0 combinations` line and gains nothing. Rows use the tree's existing three
columns as `["", "voice A", "ch 1–8 · 100–800 µA · 10–50 Hz"]`, matching the gizmo rows
above them.

## Activity mask

One definition, used for every figure this feature reports and for the two it already
reported:

> Voice `v` is **on** at event `e` when `chan{v}[e] > 0` **and** `amp{v}[e] > 0`.
> Voice `v` is **active** when it is on for at least one event.

`chan == 0` is Synapse's dummy value for "no stimulation"; `amp == 0` is a voice that is
configured but delivering nothing. Neither is stimulation.

Consequences, all intended:

- **Per-voice ranges** are computed over that voice's on-events only. Including off
  events would pin every `amp_min` and `freq_min` to 0.
- **Combinations** consider the columns of active voices, over events where at least one
  voice is on. A voice held at 0 µA no longer contributes its varying columns.
- **Pulses** stay the per-event **maximum** of `count` across on voices, summed over
  events — voices fire concurrently, so a 3-pulse train on two voices is three pulses in
  time. Only the mask changes: events where a voice is off, by the stricter test, no
  longer contribute that voice's `count`.

Existing blocks will report smaller pulse and combination counts after this change. That
is the correction, not a regression.

## Data model

`stim.py` gains a per-voice record, and `StimSummary` carries a tuple of them:

```python
@dataclass(frozen=True)
class VoiceSummary:
    """Parameters delivered by one active voice of a stim parameter store.

    :param voice: Voice suffix, e.g. ``"A"``.
    :param channels: Distinct channels stimulated, ascending.
    :param amp_min: Smallest amplitude delivered, in ``amp_units``.
    :param amp_max: Largest amplitude delivered, in ``amp_units``.
    :param freq_min_hz: Lowest within-train pulse frequency, in Hz.
    :param freq_max_hz: Highest within-train pulse frequency, in Hz.
    """

    voice: str
    channels: tuple[int, ...]
    amp_min: float
    amp_max: float
    freq_min_hz: float
    freq_max_hz: float


@dataclass(frozen=True)
class StimSummary:
    store: str
    n_pulses: int
    n_combinations: int
    voices: tuple[VoiceSummary, ...] = ()
```

`voices` defaults to empty so existing construction sites and tests keep working.

## Frequency

`per{v}` is the within-train inter-pulse interval in milliseconds, so

```
freq_Hz = per_to_hz / per
```

with `per_to_hz` in config rather than as a literal in the reduction. Events whose `per`
is `<= 0` are excluded from the frequency range rather than yielding `inf`; a voice whose
every on-event has a non-positive `per` reports no frequency clause. This is the one
place a silent `inf` could leak into the display, and it is closed at the source.

## Formatting

Two pure functions in `stim.py`, testable without Qt or a block:

**`format_channels(channels, max_listed)`** — collapse contiguous runs of three or more
into `a–b` tokens, then join with commas. `max_listed` counts **tokens**, not channels:
past that many, the list truncates with `…`. The `(N ch)` suffix carries the distinct
channel count, and appears when the list was truncated or when it rendered as a single
range token — in both cases the text alone does not say how many channels were actually
stimulated.

| Input | Output |
| --- | --- |
| `(1,2,3,4,5,6,7,8,12,14)` | `1–8,12,14` |
| `(1..32)` | `1–32 (32 ch)` |
| `(1,3,5,7,9,11,13,15,17)` | `1,3,5,7,9,… (17 ch)` |
| `(12,)` | `12` |

**`format_range(lo, hi, unit)`** — `"200 µA"` when `lo == hi`, `"100–800 µA"` otherwise.
Frequencies render to one decimal with a trailing `.0` stripped, so 20 Hz is `20 Hz`, not
`20.0 Hz`.

The assembled value cell joins the present clauses with `" · "`, skipping any clause the
data could not supply.

## Configuration

`config/metadata/default.yaml`, under `metadata.stim`:

```yaml
    # Column prefixes: chan{V} > 0 and amp{V} > 0 mark a voice active at an event;
    # count{V} is pulses per train, per{V} the within-train interval.
    chan_prefix: chan
    count_prefix: count
    amp_prefix: amp
    per_prefix: per
    # freq_Hz = per_to_hz / per{V}. per is in milliseconds.
    per_to_hz: 1000.0
    # Amplitude unit label, display only.
    amp_units: "uA"
    # Channels listed per voice before the list truncates to a count.
    max_channels_listed: 5
```

`StimConfig` gains the matching fields and `stim_config_from` reads them.

## Failure handling

- A voice whose `amp` or `per` column is absent from the named schema still lists, minus
  the clause it cannot compute, and a warning is appended naming the missing column. A
  partial answer plus a stated gap beats a dropped voice.
- `StimSchemaMismatch` behavior is unchanged: a row-count mismatch between the data and
  the schema is still an error, not a guess.
- Per-block warnings continue to surface through `BlockSummary.warnings` exactly as now.

## Testing

`tests/test_stim.py` extends its existing fixtures:

- A voice with `chan > 0` but `amp == 0` throughout is dropped, and both the pulse and
  combination counts fall accordingly.
- Per-voice ranges cover on-events only — an off event carrying a stray low amplitude
  does not lower `amp_min`.
- Frequency conversion: `per = 100` ms yields 10 Hz; a `per` of 0 is excluded; an
  all-non-positive `per` yields no frequency clause.
- Single-valued ranges render without a dash.
- `format_channels` over the four table cases above.
- A schema missing `ampA` warns and still lists voice A with its channels and frequency.

The suite stays Qt-free and headless.

## Files touched

| File | Change |
| --- | --- |
| `src/tdt_ephyviewer_explorer/metadata/stim.py` | `VoiceSummary`, tightened mask, per-voice reduction, the two formatters, `StimConfig` fields |
| `src/tdt_ephyviewer_explorer/config/metadata/default.yaml` | The five new keys |
| `src/tdt_ephyviewer_explorer/metadata/window.py` | Voice rows under each store row |
| `tests/test_stim.py` | The cases above |

`summary.py` needs no change: `StimSummary` grows a field, and it only ever passes the
summaries through.
