# datanuggets app, phase 2: live-cells amendment

An amendment to [contract.md](contract.md), which still wins wherever this file is silent. It
adds one step to the flow path: after the populations are chosen and before the cluster form,
the user keeps the live white cells by placing a threshold on a viability dye and one on CD45,
and can place more on any other channel.

The rule behind every section: **nothing suggests a threshold.** The package may name which
channel looks like the viability dye and which looks like CD45, from the channel names alone. It
never proposes a value. No server default, web default or fixture places a line for the user.

The builders are those of contract.md section 1. The package part is `datanuggets_flow.livecells`.
The server and web parts below are for the server and web builders.

## 1. Package API (`datanuggets_flow.livecells`, built)

```python
def suggest_channels(pnn: Sequence[str], pns: Sequence[str] | None = None) -> dict
    # {"viability": pnn | None, "cd45": pnn | None,
    #  "candidates": {"viability": [pnn], "cd45": [pnn]}}
def kept_values(samples, chosen, channels, *, read=read_fcs) -> KeptValues
def channel_histograms(kept: KeptValues, *, bins: int = 128, cofactor: float | str = "auto") -> dict
def count_kept(kept: KeptValues, row_filters: Sequence[str | RowFilter]) -> dict
def save_kept_values(kept: KeptValues, path) -> Path
def load_kept_values(path) -> KeptValues
```

- `suggest_channels` matches `$PnN` or `$PnS`, ignoring case. Viability names: Zombie, LIVE/DEAD,
  LIVE DEAD, LiveDead, Viability (Fixable Viability Dye), FVS, 7-AAD, DAPI, propidium iodide,
  and PI only as a whole word. CD45 only as a whole word, so CD45RA, CD45RO and CD45R don't match.
  A role's suggestion is its single candidate. Among several, it is the one whose `$PnN` ends in
  `-A`, when exactly one does. Otherwise it is `None`, and the candidates are listed for the user
  to choose from.
- `kept_values(samples, chosen, channels)` takes what `cluster_stage` takes:
  `state.load_gates(folder).samples` and one list of populations per file. It reads, raw, the
  cells those populations keep, with the same step `make_nuggets` uses. That step refuses a
  changed file. A file that keeps no cells isn't read. `FlowError` names `channels` or `pops`.
  It keeps, as `kept.cofactor`, the auto cofactors of those values, one per channel
  (`auto_cofactor` of a `NegativeTally` over the files keeping `MIN_KEPT_EVENTS` or more,
  contract.md section 2): the ones a run clustering the same cells on these channels would pick
  before any row filter. A run with the step's filters tallies the cells that pass them, so its
  cofactors can differ a little from the histograms'.
- `channel_histograms` bins channel j on `t = arcsinh(x / c_j)` (`x` with cofactor 0) on edges
  every file shares. Each file's `counts`, `below`, `above` and `nan` add up to its kept cells,
  so no cell outside the range is dropped. With `"auto"`, the default, `c_j` is channel j's own
  cofactor from `kept.cofactor`, and the result gives them as `cofactors`, with
  `negative_fraction` and `negative_sd`, after `cofactor_from`; values saved under the earlier
  header rule draw every channel on their one number, and values saved before a cofactor was
  recorded on 6000, each given as `cofactor`. A number is used as given for every channel.
- `count_kept` gives the exact per-file counts of kept cells passing the filters on raw values
  (`filters.filter_mask`). These are the numbers `selection.csv`'s `filtered` gets from a run
  with the same `row_filters`. `left_out` = passed < `MIN_KEPT_EVENTS`.
- `save_kept_values` / `load_kept_values` write and read one `.npz` (JSON record plus per-file
  values, float32 where lossless). Counts from a loaded file equal counts from the read.
- Payload shapes, refusals and an example: [docs/api.md, Live cells](../api.md#live-cells). The
  CLI equivalent: [docs/cli.md, Keeping live white cells](../cli.md#keeping-live-white-cells).
- The step's display constants (`LIVECELLS_BINS = 128`, `LIVECELLS_RANGE_QUANTILES = (0.001,
  0.999)`, `LIVECELLS_RANGE_PAD = 0.05`, `LIVECELLS_FLAT_WIDTH = 1.0`, `LIVECELLS_SCHEMA`) sit in
  `livecells.py`. None of them is a threshold. Moving them to `_defaults.py`, as contract.md
  section 2 asks, is a follow-up for the package owner. `_defaults.py` was outside this branch's
  allow-list.

## 2. HTTP API (server builder)

All routes are under `/api/v1`. Section 3 of contract.md applies: error shape, codes, scrubbing,
`FlowError` sent as `invalid_setting` with `param` = the JSON field.

### 2.1 Records and disk

- A live-cells record belongs to a gate. Its id comes from the workspace counter with prefix `l`
  (`PREFIX["livecells"] = "l"`), giving `l1`, `l2`, ... per workspace. Records are kept in
  `meta.json` under `livecells`, each holding `id`, `gate_id`, `created`, `job`, and `request`
  (the normalized request below). A local workspace's `meta.json` from before this amendment has
  no `livecells` key; the server reads it as empty.
- Disk, inside the gate folder: `gates/<gid>/livecells/<lid>/request.json`, `values.npz`
  (`save_kept_values`) and `histograms.json` (`channel_histograms`, written with
  `allow_nan=False`). The job's `spec["out"]` is the `<lid>` folder, so `run_job`'s own cleanup
  deletes it when the job fails or is cancelled. Deleting the gate deletes its folders and its
  records. `DELETE /workspace` empties the `livecells` records along with the others.
- A set is read (histograms, counts) only when its job is done. A crash or kill of the server
  skips the job's cleanup and can leave a set's folder half written; the restart marks the job
  failed (contract.md's restart message), and at boot, after the jobs are loaded, the server
  removes every `gates/<gid>/livecells/<lid>` folder that is not a done set's, including a
  folder with no record (a job started just before the stop, its set not yet saved). The
  failed record stays and lists as failed; the same request starts a new set.
- Cache: a POST whose normalized request (`pops` sorted per file, `channels` in order, `bins`,
  `cofactor`) equals a queued, running or done record of the same gate returns that record and
  its job. No new job starts. Failed and cancelled records never match, and neither does a done
  record asked for `"auto"` whose `histograms.json` has no `cofactors`: it was drawn while auto
  picked one number from the headers, so the request starts a new set drawn per channel.
- `LIVECELLS_PER_GATE` records per gate. A new one beyond it evicts the oldest done record, with
  its folder. When every record is still active, the POST is refused with 409 `wrong_state`.

### 2.2 Job

- New job kind `"livecells"`. The Job JSON keeps its key set: `kind: "livecells"`, `gate_id` set,
  `run_id` null. Cancel and timeout work as for other kinds.
- Worker `livecells_work(spec, rep, out)`, registered in `JOB_KINDS` beside `gate_work` and
  `flow_work`:
  1. `state.load_gates(gates)`.
  2. Trial cap: the cells the pops keep, summed over the files with `pick_events`, must be at
     most `LIVECELLS_CELLS_MAX`, or the job fails with `invalid_setting` param `pops`.
  3. `kept_values(folder.samples, pops, channels)`, then `save_kept_values(kept, out / "values.npz")`.
  4. `channel_histograms(kept, bins=bins, cofactor=cofactor)`, then `histograms.json`, with
     `cofactor_from` first. Under auto per channel it holds `cofactors`, `negative_fraction` and
     `negative_sd` and no single cofactor, and the job logs the span of the channels' cofactors,
     rounded as the run's Transform lines round them, `Histogram cofactor per channel (auto):
     LO-HI`, or one number when every channel has the same, as on section 4's two channels
     (`Histogram cofactor per channel (auto): 150`). Drawn on one number it holds
     `cofactor` and `range` (the earlier header rule's `kept.cofactor.range`, null for a set
     number) beside `cofactor_from`, and the job logs `Histogram cofactor 6000 (set)`.

  It calls `rep.check()` between steps. Progress goes 0 -> 0.8 after the values -> 1.0 when done.
  A new set's job counts toward `JOBS_PENDING_PER_IP`, `JOBS_PER_IP_HOUR`, `QUEUE_MAX` and
  `HEAVY_BUDGET_S_PER_DAY` like any job (amended 2026-10-28: it used to skip the hour's count,
  so live-cells POSTs could start jobs past the hourly cap). In the server's terms: the POST
  calls `check_job_room`, then `jobs.submit(ws, "livecells", spec, ip, gate_id=gid)`, then
  `limits.note_job(ip)`, as `post_gate` does. A POST the cache answers (section 2.1) starts no
  job, needs no job room and counts nothing, also when the match is found under the
  workspace lock after the room check.

### 2.3 Endpoints

`GET /flow/gates/{gid}/livecells` -> 200 (409 `wrong_state` until the gate is done)
```json
{"gate_id": "g1",
 "channels": [{"pnn": str, "pns": str}],
 "suggested": {"viability": "FJComp-LIVE DEAD Blue-A", "cd45": "FJComp-PerCP-A",
               "candidates": {"viability": [pnn], "cd45": [pnn]}},
 "livecells": [{"id": "l1", "status": "queued|running|done|failed|cancelled", "created": "...",
                "request": LivecellsRequest}]}
```
`channels` and `suggested` come from gate file 1's `$PnN`/`$PnS`, the file the default channel
rule reads too. `channels` is the Gate payload's `files[0].channels`. `suggested` is `suggest_channels(pnn, pns)` as is: channel names, never a value.

`POST /flow/gates/{gid}/livecells` -> 202 `{"job": Job, "livecells_id": "l1"}`
```json
{"pops": [[1, 2], [1], [], [1]], "channels": ["FJComp-LIVE DEAD Blue-A", "FJComp-PerCP-A"],
 "bins": 128, "cofactor": "auto"}
```
- `pops` takes one list per gate file, as in `POST /flow/runs`. `channels` takes 1 to
  `LIVECELLS_CHANNELS_MAX` `$PnN` names, distinct, in any number past the two roles. Any channel
  of the files is taken, forward and side scatter too, since no channel name is assumed (a file
  from a mass cytometer has none). A name
  that holds a lone surrogate (U+D800 to U+DFFF), which a JSON escape can carry and UTF-8
  cannot, is refused with 422 param `channels` too.
- `bins` (default 128) must be `LIVECELLS_BINS_MIN` to `LIVECELLS_BINS_MAX`. `cofactor` takes
  `"auto"` or a number from 0 (0 for linear), by the package's own check, and defaults to
  `ClusterSettings().cofactor`, `"auto"`. Auto picks each channel's cofactor from the kept
  cells' raw values, so it is the one a flow run clustering the same cells picks for that
  channel before any row filter. Any other string (`"Auto"`, `"150"`), a negative
  or non-finite number, or a list is 422 param `cofactor`. The normalized request keeps
  `"auto"` as the string and a number as a float, so `"auto"` sent or left out is the same
  request for the cache.
- Refusals: 409 when the gate is not done; 422 param `pops` / `channels` / `bins` / `cofactor`.
  The server checks counts and ranges. The package's `FlowError` covers the rest, such as a
  channel missing from a file that keeps cells.

`GET /flow/gates/{gid}/livecells/{lid}` -> 200 (404 `not_found` for an unknown lid, or a lid of
another gate)
```json
{"id": "l1", "gate_id": "g1", "status": "done", "created": "...", "job": "j9",
 "request": {"pops": [[1, 2], [1], [], [1]], "channels": [pnn], "bins": 128, "cofactor": "auto"},
 "histograms": {"cofactor_from": "auto", "bins": 128, "kept": int, "files": [...],
                "channels": [...], "cofactors": [float], "negative_fraction": [float],
                "negative_sd": [float|null]}
             | {"cofactor": 6000.0, "cofactor_from": "auto|set", "range": float|null,
                "bins": 128, "kept": int, "files": [...], "channels": [...]}
             | null}
```
`histograms` is null until the job is done, like a Gate's `files`. Under auto it has the first
shape: each channel drawn on its own cofactor, `cofactors[j]` for `channels[j]`, with the share
of its kept cells below 0 and their SD (null with none below 0), and no single `cofactor` and no
`range`. Drawn on one number it has the second: `histograms.cofactor` is that number, never
`"auto"`, `cofactor_from` says how it was chosen, and `range` is the widest marker channel range
the earlier header rule picked an auto number by (null for a set number, or when a header gave a
marker channel no usable range or the headers gave no marker channel). A set saved under that
rule keeps the second shape. A set made before these keys were recorded was asked for a number
and reads as `"set"` with `range` null. Counts are ints. `lo`, `hi`, `edges`, `cofactors`,
`negative_fraction`, `negative_sd` and `range` are sent unrounded, as JSON doubles. This is an
exception to section 3's 4-significant-digit rule, so the bars stand on the edges the package
counted with and a client turns `t` back into the raw values the package drew. Other floats,
`cofactor` among them, follow the rule.

`POST /flow/gates/{gid}/livecells/{lid}/counts` -> 200 (409 until the record is done; 404 unknown)
```json
{"row_filters": [{"column": "FJComp-LIVE DEAD Blue-A", "op": "<", "value": number},
                 {"column": "FJComp-PerCP-A", "op": ">", "value": number}]}
```
response = `count_kept(load_kept_values(values.npz), specs)`:
```json
{"row_filters": ["[FJComp-LIVE DEAD Blue-A] < <value>", "FJComp-PerCP-A > <value>"],
 "kept": int, "passed": int,
 "files": [{"number": 1, "name": "190.fcs", "events": int, "kept": int, "passed": int,
            "left_out": bool}]}
```
- `number` is the raw value of the user's line. The server and the web have no default for it.
- The server turns Filter JSON into `format_filter` specs, as for flow runs. A filter on a
  channel outside the record's `channels`, or more than `LIVECELLS_FILTERS_MAX` filters, gets 422
  param `row_filters`. `[]` counts every kept cell.
- The request is synchronous and runs in the threadpool, never on the event loop and never in
  the job pool, so it can't queue behind a flow run. A plain `def` route, as every route in
  `runs_api.py` is, gets this from FastAPI. It reads
  `values.npz` and no FCS file. The server keeps the last `LIVECELLS_MEMORY_SETS` loaded sets
  in memory, keyed by (workspace, lid), and bounds the loading too: one load per set at a time
  (a second request for a set being loaded waits for it and shares its values), and at most
  max(`LIVECELLS_MEMORY_SETS`, 1) loads of different sets at once; other requests wait for a
  slot.
- Trial: `LIVECELLS_COUNTS_PER_IP_MINUTE` gives 429 `rate_limited` with `Retry-After`.

`DELETE /flow/gates/{gid}` also refuses 409 while a livecells job of the gate is queued or
running. `DELETE /workspace` refuses and deletes as before, and also empties the `livecells`
records (section 2.1).

### 2.4 Caps (config.py `Caps`, sent in `/config` `caps` by their lower-case names)

`/config` sends `caps` in trial mode only; in local mode it is null (contract.md section 3.2), so
the web reads none of these there. In trial mode it stops adding rows at `livecells_channels_max`.
It sends `bins` 128 and one filter per row, which stays under `LIVECELLS_FILTERS_MAX`. A set's
values are its kept cells times its channels, so the trial channel cap keeps a set at most
`LIVECELLS_CELLS_MAX` times 8 float64 values, about 384 MB. The counts route keeps up to
`LIVECELLS_MEMORY_SETS` (2) loaded sets in the API process, so about 768 MB at worst.
`LOCAL_CAPS` sets every `Caps` field typed `int | None` to None, so a cap with a Local value
below is typed `int` (its trial default is its local value) and a cap with none is `int | None`.

| Name | Trial | Local |
|---|---|---|
| `LIVECELLS_CHANNELS_MAX` | 8 | none |
| `LIVECELLS_BINS_MIN` / `LIVECELLS_BINS_MAX` | 8 / 512 | 8 / 512 |
| `LIVECELLS_PER_GATE` | 8 | 8 |
| `LIVECELLS_CELLS_MAX` | 6,000,000 kept cells summed over the files | none |
| `LIVECELLS_FILTERS_MAX` | 16 per counts request | none |
| `LIVECELLS_COUNTS_PER_IP_MINUTE` | 120 | none |
| `LIVECELLS_MEMORY_SETS` | 2 loaded sets kept, and 2 loads at once | 2 |

`GET__config.json` (trial) gains these keys in its `caps`. `GET__config.local.json` keeps
`caps: null`.

## 3. Web behaviour (web builder)

Steps on the gate screen: **Populations -> Live cells -> Cluster**. Live cells is its own step,
with **Skip** and **Continue**. Skip goes to the cluster form and adds nothing.

- **Entering the step** sends `GET .../livecells` and fills one dropdown per row:
  - The first two rows are "Viability dye" and "CD45". Each dropdown lists file 1's channels as
    `pns (pnn)`, plus "None": every channel but the time channel (`Time`, `Time (s)`, `HDR-T`),
    forward and side scatter included.
  - The two rows start on `suggested.viability` / `suggested.cd45`.
  - When a suggestion is null but there are candidates, a note names them ("Several channels
    look like a viability dye: A, B. Choose one.") and the dropdown stays on "None".
  - With no candidates the note says no channel's name looks like one.
  - "Add a channel" adds a row (its dropdown on "None", its side "keep above"), up to one row
    per channel offered, or `livecells_channels_max` rows in trial mode. An added row can be
    removed; the two role rows can be set to "None". A channel chosen in one row is shown but
    disabled in the others. Added rows are named "Channel 1", "Channel 2" and so on, counting
    added rows only.
  - With every row on "None", Continue acts as Skip.
- **Loading** sends `POST .../livecells` with the chosen pops and the rows' channels, in row
  order, and `cofactor`: the cluster form's typed number when the step has one, else `"auto"`.
  The step polls the
  job and then `GET .../livecells/{lid}`. A changed choice of pops or channels sends a new POST
  after 400 ms without another change (the step's first POST goes at once), and first cancels
  the job of an earlier, different request while it is still queued or running; the cache
  answers repeats.
  - Picking a channel, "Add a channel" and "Remove" redraw the step. The focus stays on the
    dropdown that changed, moves to the new row's dropdown after Add, and to the row above after
    Remove.
- **Histograms** are one Plotly bar chart per channel, pooled counts on `edges`.
  - The x axis is in `t` units (arcsinh) on the channel's cofactor, the number the server drew
    it on, never `"auto"`: `histograms.cofactors[j]` for `histograms.channels[j]` under auto,
    else `histograms.cofactor` (`cofactorFor` in `shared/cofactor.js`). Tick labels are raw
    values: `tickvals = asinh(raw / cofactor)` for round raw values, `ticktext` the raw numbers.
    The axis title names the channel's cofactor and `cofactor_from` ("cofactor 150, auto"). With
    cofactor 0 the axis is linear.
  - `below` / `above` show as text at the left and right ends ("312 cells below the range").
    They are never hidden.
  - Per-file histograms are optional, behind a toggle. They use the same edges.
- **The line**:
  - No line is drawn until the user clicks a histogram. The click places a vertical line at that
    x, clamped to `[lo, hi]`.
  - The line then drags (an editable Plotly shape).
  - Its raw value is `cofactor * sinh(t)`, with the channel's cofactor, rounded to 4 significant
    digits. It shows beside the
    line and in a number input. Typing a value moves the line, which is the keyboard path.
  - Nothing ever places a line for the user: no default position and no "auto" button.
- **Keep below / keep above** is a switch per row. The viability dye defaults to "keep
  below" (`<`), CD45 and every added row to "keep above" (`>`). The switch is a direction, not
  a value.
- **Counts**:
  - After a drag ends, a typed value or a switch change, the step waits 300 ms of quiet, then
    sends `POST .../counts` with one filter per row that has a line, in row order.
  - Each request carries a sequence number. A response older than the latest is dropped.
  - A table shows each file's kept cells, passing cells and percent, from the payload's exact
    ints, with a "left out" badge when `left_out`. It also shows the echoed `row_filters`.
  - Before any line is placed, the table shows the kept cells with no filter.
- **Continue** hands the filters on: one Filter per placed line, in row order, plus
  `exclude_channels: [viability]` when "Leave the viability dye out of the clustering" is ticked.
  The checkbox is ticked by default when a viability channel is chosen.
- **Cluster form**:
  - The filters appear in the filter builder, visible and editable. The dye is unticked in the
    channel checkboxes, with a note that it was excluded.
  - The run request sends `channels: null, exclude_channels: [dye]` when the ticked set equals
    `default_channels` minus the dye. Otherwise it sends the explicit ticked `channels` and
    `exclude_channels: []`, because the package refuses the two together.
  - Back returns to Live cells with the lines kept.
- The gate job lookup in `views/gate.js` must match `kind === "gate"` as well as `gate_id`, since
  livecells jobs carry the gate's id. Two more places in the merged web read a job's `gate_id`
  and need the same check: the job-done toast in `js/actions.js` ("Gate g1 is ready.") and the
  "Pick populations" button in `views/job.js` (a done job with `gate_id` and no `run_id`). A done
  livecells job gets neither.

## 4. Fixtures (web builder, contract.md section 6 naming)

| File | Body |
|---|---|
| `GET__flow__gates__g1__livecells.json` | the step's channels, suggestion and records |
| `POST__flow__gates__g1__livecells.json` | `{"job": Job, "livecells_id": "l1"}` |
| `GET__jobs__j9.json` | that job, `kind: "livecells"`, done (the next free job id after j8) |
| `GET__flow__gates__g1__livecells__l1.json` | the record with `histograms` |
| `POST__flow__gates__g1__livecells__l1__counts.json` | a counts response |

- They are built by `app/web/tools/build_fixtures.py` from a real run of the package on the four
  PBMC demo files (190, 193, 199, 223), with the gate fixture's pops. The request leaves the
  cofactor on `"auto"`, so the histograms have the per-channel shape, `cofactor_from` `"auto"`.
  On the 107,581 kept cells neither `FJComp-LIVE DEAD Blue-A` nor `FJComp-PerCP-A` has a cell
  below 0, so both are drawn on 150, with `negative_fraction` 0 and `negative_sd` null.
- The counts fixture's filters sit at each channel's middle histogram edge (`edges[bins // 2]`),
  turned to raw with that channel's cofactor and rounded to 4 significant digits. They are derived, never
  typed, and are not offered to the user as defaults.
- In fixture mode, the counts table shows that response wherever the line sits.

## 5. Acceptance criteria

### Package (P)
- P17 `suggest_channels` on the real `$PnN`/`$PnS` of the 4 demo FCS gives
  `FJComp-LIVE DEAD Blue-A` / `FJComp-PerCP-A`, and not `FJComp-BUV395-A` (CD45RA). On the files
  of Zenodo 18367404 it gives `Zombie NIR-A` / `BV570-A`. Ambiguity gives None plus candidates.
  The function returns names only.
- P18 `kept_values` on real events (202 fixtures written with `flowio.create_fcs`, gated by
  `gate_stage`, loaded by `load_gates`) equals a direct read of the `pick_events` rows. It
  refuses a changed file and doesn't read a left-out one.
- P19 `channel_histograms`: `bins + 1` shared edges from `lo` to `hi`. Per file, counts + below +
  above + nan = kept. Pooled = sum of files. Counts equal an independent digitize recount, at
  the default cofactor and at cofactor 0.
- P20 `count_kept` equals a direct `filter_mask` count and the `filtered` column of
  `cluster_stage`'s `selection.csv` with the same `row_filters`. It is the same after
  `save_kept_values` / `load_kept_values`.
- P21 `ruff check` and `ruff format --check` are clean. docs/api.md (Live cells) and docs/cli.md
  (Keeping live white cells) describe the module and its CLI equivalent.

### Server (S)
- S13 The four endpoints exist with the pinned key sets and errors: 409 for a gate or record not
  done, 404 for an unknown lid, 422 with `param` for each of `pops`, `channels`, `bins`,
  `cofactor`, `row_filters`. Every channel of a file is taken at the trial caps, scatter
  included.
- S14 End to end on the S6 real-event fixture: POST -> a `livecells` job done -> `histograms`
  equals `channel_histograms(kept_values(...))`. The counts response equals `count_kept` and the
  `filtered` column of a flow run sent the same `row_filters`.
- S15 An identical POST reuses the record (same id, no new job), but an `"auto"` record drawn
  under the header rule starts a new set, which the next identical POST reuses. Counts answer
  with the FCS uploads made unreadable after the job, which proves no FCS read. `/health`
  answers within 200 ms while counts run.
- S16 Caps: channel count, bins range, cells cap (`pops`), filter count, counts rate (429 +
  `Retry-After`), eviction past `LIVECELLS_PER_GATE`. `DELETE` of the gate gives 409 while a
  livecells job runs, and removes `livecells/` after.
- S17 The Job key set is unchanged. `kind` is `"livecells"` with `gate_id` set. Cancel removes
  the record's folder.

### Web (W)
- W14 Live cells sits between Populations and Cluster, with Skip. The dropdowns start on the
  suggestions. An ambiguous or empty suggestion shows its note. "None" is offered, and every
  channel but Time. "Add a channel" adds removable rows, up to one per channel offered, and
  a channel one row holds is disabled in the others.
- W15 Bars are on the arcsinh axis of the channel's own cofactor with raw tick labels, and
  below/above are shown. No line appears before a click. The line drags, is clamped to
  `[lo, hi]`, and shows `cofactor * sinh(t)`, with that cofactor, to 4 significant digits. A
  typed value moves it.
- W16 Keep below / keep above per row: viability starts below, CD45 and added rows above.
  Switching re-counts.
- W17 Counts go out 300 ms after the last drag, typed value or switch, and stale responses are
  dropped. The per-file table uses the payload's exact ints and the left-out badge.
- W18 Continue puts the filters in the cluster form's filter builder, editable, and unticks the
  dye. The flow run request carries them, as `channels: null` + `exclude_channels`, or explicit
  channels + `[]` after the ticks were edited.
- W19 The gate job lookup, the job-done toast and the job view's Pick populations button all
  filter `kind === "gate"`. `?fixtures=1` renders the step from the
  section 4 fixtures with zero console errors at 1440 and 390 px.

### Integration (I)
- I3 Browser pass on the live server: load the PBMC demo -> gate -> pops -> Live cells shows the
  suggestions `FJComp-LIVE DEAD Blue-A` / `FJComp-PerCP-A` -> place both lines -> counts ->
  Continue -> flow run. The run's `selection.csv` `filtered` equals the counts last shown.
