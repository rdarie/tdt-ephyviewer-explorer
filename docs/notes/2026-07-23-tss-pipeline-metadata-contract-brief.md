# Implementation brief — embed the `tdt_explore` metadata contract in tss-pipeline parquets

**Audience:** a coding agent working in `C:\Users\MBO\Documents\GitHub\tss-pipeline`.
**Written from:** the tdt-ephyviewer-explorer repo (the *consumer*). Date: 2026-07-23.
**Goal:** make each preprocessed parquet self-describing so the tdt-explore GUI can ingest it
(kind + time axis + sample rate) without filename or index heuristics.

This is the **producer half** of a shared contract. The consumer half (reader, GUI,
auto-discovery) is implemented separately in tdt-explore. Keep the JSON shape below exact —
both repos depend on it. If you must deviate, record the deviation (see "Report back").

---

## 1. Why this is needed (context)

tdt-explore currently ingests only raw TDT stores. We want it to also ingest tss-pipeline's
preprocessed parquets. Investigation of the current outputs found that **neither the filename
nor the DataFrame index reliably identifies a file's kind or sample rate**:

- Filenames are config-driven (`file_name` in YAML), so a timeseries may be `raw_data.parquet`,
  `mona_data.parquet`, `raw_data_mep.parquet`, `{workflow}.parquet`, etc.
- The continuous index is a plain `RangeIndex` 0..N-1 (sample number), **not** clock ticks —
  built via `pd.DataFrame(data)` with no index set (`preprocessing.py` ~`:200, :297, :447`).
- `DataFrame.attrs['sampling_rate']` is present on some frames (e.g. `mona_data`) but
  deliberately **absent** on others: `attrs` is wiped before some writes
  (`preprocessing.py` ~`:4951, :5038`) and never set on the cleaned `raw_data_mep`
  (~`:1178`). The pipeline itself treats `df.attrs` as non-durable and gets the rate from
  the session YAML config downstream — tdt-explore has no access to that config.

So we embed a small, durable, explicit contract in each parquet we care about.

> NOTE: line numbers above are from a 2026-07-23 read of `preprocessing.py` and may drift.
> Treat them as starting points; search for the `to_parquet` calls if they've moved.

---

## 2. The contract (authoritative — keep exact)

**Storage key:** `b"tdt_explore"` in the **parquet schema metadata** (not `df.attrs`).
**Value:** a UTF-8-encoded JSON object.
**Do NOT reuse `write_scalar_annotations`** (that owns key `b"tss_scalar_annotation"` and its
own keyset). Reuse only its *technique* (below), under this new key.

### Common fields (every kind)
```jsonc
{
  "contract_version": 1,              // int; bump only on breaking change
  "kind": "timeseries" | "event",
  "data_source": "raw_data_mep"       // optional; free-text provenance
}
```

### `kind == "timeseries"`
```jsonc
{
  "sampling_rate": 24414.0625,        // REQUIRED float, Hz, EFFECTIVE (post-decimation) rate
  "t_start": 3.2148,                  // REQUIRED float, SECONDS; block-relative time of sample 0
  "channel_names": ["0","1","..."],   // optional list[str]; default = DataFrame columns
  "units": "uV"                       // optional; display only
}
```

### `kind == "event"`  (e.g. `stim_info_per_pulse.parquet`, `stim_info.parquet`)
```jsonc
{
  "time_column": "timestamp_sample",  // REQUIRED; column holding event onset (see "units" below)
  "time_units": "samples",            // "samples" (RECOMMENDED here) or "seconds" (absent-default)
  "sampling_rate": 24414.0625,        // REQUIRED when time_units == "samples"
  "label_column": "stim_site",        // optional; human-readable per-row label
  "schema": "iz_param_names"          // optional; named column-schema for formatter labels
}
```

> **Epoch/window-info tables are OUT OF SCOPE.** `window_info_per_pulse.parquet` /
> `{epoch_window_name}.parquet` are interval tables whose semantics are convoluted and not the
> time-series snips originally assumed. Do **not** tag them (see the do-not-tag list in §4).
> There is no `epoch` kind in this contract version.

**Use integer sample columns, not seconds — precision.** The seconds column (`timestamp`) is
**float32**: ~7 significant digits, so ~0.12 ms ULP at 1000 s, which is coarser than one 41 µs
sample and drifts worse later in a block. The int `timestamp_sample` column is exact, and the
consumer computes `seconds = sample / sampling_rate` in float64 (exact to ~1e-13 s). So for
every event file tss-pipeline writes, point `time_column` at the integer `*_sample` column and
set `time_units:"samples"` + `sampling_rate`.

`time_units` is *optional* and its absent-default is `"seconds"` — that default exists only so
the consumer can still read untagged/external parquets that carry only a float `timestamp`. It
is **not** the recommendation for tss-pipeline's own outputs.

> WRITER CAVEAT (must-do for the gain to be real): `timestamp_sample` is currently
> `round(timestamp * sample_rate)`. If `timestamp` is already float32 at that multiply, the
> sample column just re-encodes the float32 error and buys nothing. Derive the `*_sample`
> columns from the **raw TDT tick / float64 source**, before any float32 cast, so they are the
> true integer sample index. Confirm this when you report back.

---

## 3. `t_start` semantics (get this right — it's the alignment key)

`t_start` must express the onset of sample 0 on the **same block-relative seconds clock** as:
- TDT stream `start_time`, and
- the event table's `timestamp` column (which is `scalar ts + delay`, block-relative seconds).

The continuous data written to parquet may be trimmed/offset relative to the raw stream start;
whatever offset you applied, `t_start` must be the block-relative-seconds time that the FIRST
row of the parquet corresponds to. You are the only place that knows this offset. Concretely:

- If the parquet starts at the raw stream's first sample: `t_start = stream_start_time` (s).
- If you trimmed the first `k` samples at effective rate `fs`:
  `t_start = stream_start_time + k / fs`.

If a timeseries genuinely starts at block time 0, `t_start = 0.0` is fine — but set it
explicitly; do not omit it.

`sampling_rate` is the **effective** rate: if the frame was decimated by `decimation_factor`,
write `raw_rate / decimation_factor`, not the raw rate.

---

## 4. Which files to tag (recommended coverage)

| File (pattern)                       | kind         | key fields to set                                              |
|--------------------------------------|--------------|----------------------------------------------------------------|
| `{file_name}.parquet` (raw ingest)   | `timeseries` | `sampling_rate`, `t_start`, (`channel_names` if named/Voice)   |
| `{file_name}_{workflow}.parquet` (cleaned, e.g. `raw_data_mep`) | `timeseries` | `sampling_rate`, `t_start`, `units:"uV"` |
| combined-stream output               | `timeseries` | as above (`channel_names` recommended)                         |
| template-subtracted `{workflow}.parquet` | `timeseries` | `sampling_rate`, `t_start`                                 |
| `stim_synch.parquet`                 | `timeseries` | `sampling_rate`, `t_start` (boolean per-sample TTL; shows as 0/1 trace) |
| `*_blank_mask.parquet` (e.g. `raw_data_mep_blank_mask`) | `timeseries` | `sampling_rate`, `t_start` — use the SAME values as the companion cleaned data it aligns to (e.g. `raw_data_mep`) |
| `stim_info_per_pulse.parquet`        | `event`      | `time_column:"timestamp_sample"`, `time_units:"samples"`, `sampling_rate`, `label_column:"stim_site"` |
| `stim_info.parquet`                  | `event`      | same as per-pulse                                              |

**Do NOT tag (consumer skips them anyway):**
- **Window-info / epoch tables** — `window_info_per_pulse.parquet`,
  `{epoch_window_name}.parquet` (interval tables, convoluted semantics, out of scope; there is
  no `epoch` kind in this contract version).
- Feature/summary tables with a MultiIndex (`mep_full_rms*`, `*_templates`, `*_rms`),
  `spikes*`/`binned_spikes`, spectral/kinematics outputs.

These are all out of scope for the viewer.

---

## 5. Implementation mechanism (mirror `write_scalar_annotations`)

`data_io/scalar_annotations.py:26-54` already shows the durable-metadata pattern: build a
`pyarrow.Table`, merge a JSON blob into `table.schema.metadata`, `pq.write_table`. Factor a
small shared helper rather than duplicating, e.g.:

```python
import json
import pyarrow as pa
import pyarrow.parquet as pq

def embed_metadata(df, path, key: str, payload: dict, **to_table_kwargs) -> None:
    """Write ``df`` to ``path`` with ``payload`` JSON embedded under schema-metadata ``key``."""
    table = pa.Table.from_pandas(df, **to_table_kwargs)
    md = dict(table.schema.metadata or {})
    md[key.encode()] = json.dumps(payload).encode("utf-8")
    pq.write_table(table.replace_schema_metadata(md), path)
```

Then at each `to_parquet` site listed in §4, build the payload and call
`embed_metadata(df, path, "tdt_explore", payload)` instead of `df.to_parquet(path)`.
Preserve any existing `df.attrs` writes — this is additive; the new blob is the durable source
of truth and `attrs` can stay for backward compatibility.

Keep the payload construction near where `stream_cfg['sampling_rate']`, the trim offset, and
column names are already in scope, so `t_start`/`sampling_rate`/`channel_names` are exact.

---

## 6. Acceptance criteria

1. Re-running preprocessing on the example block
   `cnn_gp_mep_all_udp_v2-260626-115952 / rRew03-260626-130955` produces:
   - `raw_data_mep.parquet` with a `tdt_explore` blob: `kind:"timeseries"`, correct
     `sampling_rate` and `t_start`.
   - `stim_info_per_pulse.parquet` with `kind:"event"`, `time_column:"timestamp_sample"`,
     `time_units:"samples"`, `sampling_rate`, `label_column:"stim_site"`.
   - `stim_synch.parquet` and `raw_data_mep_blank_mask.parquet` with `kind:"timeseries"` and
     the same `sampling_rate`/`t_start` as `raw_data_mep`.
2. Round-trip check passes (add as a unit test):

```python
import json, pyarrow.parquet as pq
md = pq.read_metadata(path).metadata
blob = json.loads(md[b"tdt_explore"])
assert blob["contract_version"] == 1
assert blob["kind"] in {"timeseries", "event"}
if blob["kind"] == "timeseries":
    assert "sampling_rate" in blob and "t_start" in blob
if blob["kind"] == "event":
    assert blob["time_column"] in df.columns          # points at a real column
    if blob.get("time_units", "seconds") == "samples":
        assert "sampling_rate" in blob                # needed to convert samples -> seconds
        # alignment check (float64): sample / rate ~= expected block-relative seconds
        # secs0 = df[blob["time_column"]].iloc[0] / blob["sampling_rate"]
```

3. Existing downstream consumers that ignore the blob are unaffected (data/columns/index
   unchanged; only schema metadata added).

---

## 7. Report back to tdt-explore (so we can write the ingestion plan against reality)

After implementing, tell the tdt-explore side:
- Any field name / value deviations from §2 (especially if you renamed keys or changed
  `time_units` handling).
- Which files you actually tag, and any you chose to tag that aren't in §4.
- For `stim_synch` / `*_blank_mask`: their column layout (single mask column vs one per
  channel) and confirmation they share `raw_data_mep`'s `sampling_rate`/`t_start`.
- The concrete `t_start` values / formula you used, and whether any timeseries can start at a
  non-zero block time in practice.
- **Confirmation that the `*_sample` columns are derived from the high-precision TDT clock**
  (not by rounding an already-float32 `timestamp`), and which exact columns you pointed
  `time_column`/`off_time_column` at.
- Whether `channel_names` is populated for integer-site streams or only for `Voice ...` streams.
- `contract_version` shipped (should be `1`).
