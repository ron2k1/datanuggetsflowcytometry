# Flow-only app and datasets

Two changes to the app, in this order:

1. The app becomes a flow cytometry app. General mode (CSV upload, `POST /runs/general`, the
   General/Flow switch) leaves it. The general analysis isn't part of this repository.
2. Uploaded FCS files are grouped into datasets by their colour channels. A gate, and so a run,
   takes files from one dataset only.

## 1. Flow only

### What leaves

- Web: the SWAP control and mode state (`S.mode`, `setMode`, `EV.modeChange`, the two tab sets),
  the CSV upload path (preview, column picker, row filters, the general run form), the
  `GENERAL_ANALYSES`, `TRANSFORMS`, `PREVIEW_PAGE`, `LOCAL_CSV_PREVIEW` and `STORAGE.mode` values,
  `startGeneralRun` and `uploadRows`, and every branch on a general run in plot, inspector, panel,
  record and jobs. The page accepts `.fcs` only.
- Server: `features/general`, `core/package/general.py`, CSV upload (`describe_csv`,
  `read_rows`, `GET /uploads/{uid}/rows`, the `.csv` upload kind), the general branches in runs,
  plot, cells and run outputs, `runs.upload_in_use`, the `defaults.general` block of `/config` and
  the caps `upload_csv_bytes`, `csv_rows`, `csv_columns`, `general_nuggets_max` and
  `general_intermediate_max`.
- Demos: iris and California housing (and their CSVs), and the AIS large set. The image keeps the
  PBMC demo; `large.json` keeps nkg2a.
- Fixtures: the general runs r1, r2 and r4, the CSV uploads u1 and u2, the general jobs, the iris
  and housing demo loads and `POST__runs__general.json`.

### What changes on purpose

- `POST /runs/general` and `GET /uploads/{uid}/rows` answer 404 `not_found` (the fallback route).
- A CSV upload is refused like any other file that isn't FCS, by its header: "This is not an FCS
  2.0, 3.0 or 3.1 file."
- The Upload JSON loses `preview` (it was always null for FCS). The run manifest loses `methods`;
  `/runs/{rid}/plot` and `/cells` drop the `method` query parameter (FastAPI ignores it if sent).
- A local workspace from before this change can still hold CSV uploads and general runs. The
  server keeps listing them, so `DELETE` still works and their files still download, but
  `GET /runs/{rid}`, `/plot` and `/cells` refuse a run whose kind is not `flow` with 409
  `wrong_state`, as `/compare` already does. The page lists only `fcs` uploads, `flow` runs and
  jobs that are not `general`.
- Fixture ids keep their gaps (uploads u3 to u6, runs r3 and r7, jobs j1, j4, j7 to j10), so no
  flow fixture or document that names an id changes.

### What keeps its coverage

Downloads (files, zip, CSV-injection quoting, path traversal), the no-absolute-path sweep and the
JOB/MANIFEST/PLOT key sets move from `test_general.py` onto a flow run in `test_flow.py`. Job
mechanics (queue, cancel, timeout, restart, claims) run on gate jobs. Upload refusals, size caps,
workspace expiry and the host check run on the 202 FCS file. CI's smoke script runs the flow path
on the PBMC demo: load it, gate it, run it, then read the plot, the files and the zip.

## 2. Datasets

### Definition

A dataset is the FCS uploads in one workspace whose colour channels are the same set. The colour
channels are the package's default clustering channels (`pipeline.default_channels`): the `$PnN`
names that end in `-A` and are not scatter (`FLOW_CHANNEL_SUFFIX`, `FLOW_SCATTER_PATTERNS`: FS
or SS followed by C, a space, a dash, an underscore or nothing, in any case), or, in a file with
fewer than two such names, every name but those and Time (`FLOW_TIME_PATTERN`), as on a mass cytometer. Order does not matter. Beside two `-A` colour
channels, Time and `-H`/`-W` channels never count. Stain names (`$PnS`) do not define a dataset.

This is stricter than the package, which only needs every file to contain the first file's
channels. A file with one extra colour channel is its own dataset here, because a dataset is meant
to be one staining panel.

### Grouping (the page)

`shared/datasets.js` groups uploads from their `columns` names, so it works the same for live
uploads, fixture uploads and files read in the tab. Each dataset has:

- `key`: its sorted colour channels; `channels`: the same list.
- `files`: its uploads, in upload order. Datasets are ordered by their first upload.
- `name`: the given name, or "Dataset N" by that order.
- `diff`: against the dataset with the most files (the earliest on a tie), "lacks X, Y" and/or
  "adds Z", naming at most three channels and then "and N more". Empty for that dataset itself.
- `stains`: the colour channels whose trimmed, non-empty `$PnS` differ between its files, each
  with the stain names and the files that use them. This is a warning only: the same channel can
  be spelled two ways by two operators, and the page cannot tell that from a different stain.

The `-A` suffix is mirrored as `FLOW_CHANNEL_SUFFIX` in `shared/config.js` and pinned to the
package by a Python test, as the scatter patterns and the time pattern already are. The server's
`colour_channels` calls the package's `default_channels` itself.

### The rule (the server)

`POST /flow/gates` refuses uploads whose colour channels differ: 422 `invalid_setting`, param
`uploads`, "b.fcs has different colour channels from a.fcs (it lacks `<channel>`). A gate takes files
from one dataset." The colour channels come from a `core/package/flow.py` helper that reads
the package's constants. `POST /flow/runs` checks its gate's uploads the same way, since a gate
made before this check can mix datasets: 422 `invalid_setting`, param `gate_id`, the same message
ending "A run takes files from one dataset." Before this check a mismatch failed later, as a gate
or run job error.

### Names

Given names live in the workspace, so they survive a reload and a restart in local mode.

- `meta.json` gains a `datasets` kind: records `{id, channels, name}`, ids `d1`, `d2`, ...
  A `meta.json` from before reads as no names.
- `GET /workspace` adds `"datasets": [{id, channels, name}]`.
- `POST /datasets` with exactly `{channels, name}` sets the name of that channel set (a new
  record, or the existing one for the same set in any order); a blank name removes it. It
  answers 200 with `{datasets: [...]}`. The name is trimmed as Python's `str.strip()` trims, then
  at most 60 characters with no control character (Unicode `Cc`), line or paragraph separator
  (U+2028, U+2029) or bidi control (U+061C, U+200E, U+200F, U+202A to U+202E, U+2066 to U+2069).
  The channel list is 1 to 512 names, each non-empty, at most 100 characters and listed once,
  and at most 16,000 bytes as Python's `json.dumps` writes it; a channel name may hold those
  characters, as an upload's `$PnN` can. Neither holds a lone surrogate (U+D800 to U+DFFF). A
  workspace keeps at most 100 names: a new set's name at the cap first removes the names of the
  sets no upload has, and is refused when every name left is an upload's set. A name may be given
  to a set no upload has (it is kept until the cap makes room, and not shown). Each refusal is
  422 `invalid_setting`, as contract section 3.3 gives them. A run takes files of one dataset
  too: `POST /flow/runs` checks its gate's uploads (the rule, above).
- In fixture mode the transport keeps names in the tab, as it keeps uploads read in the tab.

### On the page

- Explorer: the Uploads folder becomes Datasets. Each dataset is a folder row with its name and
  file count, its `diff` and channel count in the tooltip, and a warning mark when its stains
  differ. A rename button beside the row turns the name into a text field: Enter saves, Escape
  cancels without closing anything else.
- Upload tab: a Dataset line with the name, file count, `diff` and any stain warning.
- Gate form: the file list shows only the opened file's dataset, the last batch is pre-ticked only
  within it, and a note counts the files in other datasets that are not shown and says why. A
  stain warning shows when the ticked files' stains differ.
- Uploader: after a batch, a file that lands in a dataset of its own gets a toast naming its
  dataset and what it lacks or adds, shown after the batch's last refusal or failure toast.

### Edge cases

- A file with fewer than two colour channels is, like any file, in one dataset with the files that
  have the same colour channels. It can be gated; the cluster step refuses it, as the package does
  today.
- Live cells and the cluster step read gate file 1's channels. With one dataset per gate, every
  file has the same ones.

## 3. Out of scope

The repository split, PyPI and image releases, and updating the running containers. A package
change that lets a file with no populations ticked skip the channel check is a separate offer.
