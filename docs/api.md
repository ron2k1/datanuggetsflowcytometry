# API reference

## Flow utilities

Import these functions from `datanuggets_flow`. They implement Cabrera's gate-finding workflow separately from the R package ports. See [methodology](methodology.md) for the approach and [CLI guide](cli.md) for processing FCS files.

### Flow example data

These examples use the measured `202` scatter-channel fixture. Run them from the repository root, where `tests/fixtures/flow` holds the fixture, after `import numpy as np`.

```python
import datanuggets_flow as flow

with np.load("tests/fixtures/flow/202.npz") as recorded:
    fsc = recorded["fsc"]
    ssc = recorded["ssc"]

# Match the finder's scatter-channel transformation and grid orientation.
shift = min(fsc.min(), ssc.min())
grid = flow.f_plot(
    np.sqrt(ssc - shift + 3), np.sqrt(fsc - shift + 3),
    nr=100, nc=100, scale="l",
)
density = grid.z.T
candidates = flow.local_maxima(density)
peaks = flow.refine_peaks(density, candidates)
peak_row, peak_col = peaks[0]  # This measured fixture has surviving peaks.
```

For arbitrary data, check `len(peaks)` before indexing: detecting no populations is a valid outcome.

### `lymphmacro_finder`

**Description**

Find candidate populations using forward- and side-scatter channels, a density grid, and convex hull gates.

**Usage**

```text
lymphmacro_finder(fsc_a, ssc_a, *, n_row=11, n_col=11,
                 t11=22, t21=0.25, t12=20, t22=0.5, area=find_area)
```

**Arguments**

| Argument | Meaning |
| --- | --- |
| `fsc_a`, `ssc_a` | Equal-length, finite, nonconstant one-dimensional FSC-A and SSC-A channels. |
| `n_row`, `n_col` | Row and column widths of the local-maximum neighborhood. |
| `t11`, `t21` | Radius and relative density threshold for the first retained peak. |
| `t12`, `t22` | Radius and relative density threshold for subsequent peaks. |
| `area` | Area-selection function. Defaults to `find_area`; `mirrored_area` reproduces the historical alternative. |

**Details**

The finder transforms the channels, constructs a 100 × 100 density grid, refines detected peaks, and builds hulls in the original channel coordinates. The library default uses `find_area`; the CLI default uses `mirrored_area`. Use the same choice when comparing them.

Gates may overlap, and some events may be outside every gate. Population columns are candidates for inspection, not validated biological cell-type labels.

**Value**

A Boolean array of shape `(n_events, n_populations)`. No surviving peaks produces zero columns.

**Examples**

```python
masks = flow.lymphmacro_finder(fsc, ssc)
events_in_any_gate = masks.any(axis=1)
events_per_gate = masks.sum(axis=0)  # Overlapping events can contribute to multiple gates.
```

**See also:** [`find_area`](#find_area), [`mirrored_area`](#mirrored_area), [`finder_peaks`](#finder_peaks), [`gates`](#gates), [CLI guide](cli.md).

### `finder_peaks`

**Description**

Return the density grid `lymphmacro_finder` gates on, its local maxima, and the peaks it keeps, for inspection or drawing with [`plot.peaks`](#peaks).

**Usage**

```text
finder_peaks(fsc_a, ssc_a, *, n_row=11, n_col=11)
```

**Arguments**

`fsc_a` and `ssc_a` are the channels given to `lymphmacro_finder`. `n_row` and `n_col` are its local-maximum neighborhood.

**Details**

The grid, candidates and peaks are computed by the same steps as the finder's, so peak *k* (counting from 1) is the peak that seeds the finder's population column *k* − 1, "Pop *k*" in `gates`. `refine_peaks` moves each candidate uphill with `search_ind` and merges candidates that land on the same cell, then drops peaks outside the row and column limits or not above the 0.9 density quantile. A candidate missing from `peaks` moved, merged or was dropped.

**Value**

A [`FinderPeaks`](#finderpeaks).

**Examples**

```python
fp = flow.finder_peaks(fsc, ssc)
assert len(fp.peaks) == masks.shape[1]
```

**See also:** [`local_maxima`](#local_maxima), [`refine_peaks`](#refine_peaks), [`peaks`](#peaks).

### `gate_peaks`

**Description**

Return `lymphmacro_finder`'s masks and `finder_peaks`' view together, from one density grid.

**Usage**

```text
gate_peaks(fsc_a, ssc_a, *, n_row=11, n_col=11,
           t11=22, t21=0.25, t12=20, t22=0.5, area=find_area)
```

**Arguments**

The same as [`lymphmacro_finder`](#lymphmacro_finder)'s.

**Details**

A file that is gated and drawn needs both results, and the two functions build the same grid, local maxima and peaks. `gate_peaks` builds them once. `datanuggets-flow` gates every file with it.

**Value**

A tuple `(masks, peaks)`: the array `lymphmacro_finder` returns with the same arguments, and the [`FinderPeaks`](#finderpeaks) `finder_peaks` returns with the same `n_row` and `n_col`.

**Examples**

```python
masks, fp = flow.gate_peaks(fsc, ssc, area=flow.mirrored_area)
assert masks.shape[1] == len(fp.peaks)
```

**See also:** [`lymphmacro_finder`](#lymphmacro_finder), [`finder_peaks`](#finder_peaks), [The flow pipeline library](#the-flow-pipeline-library).

### Grid and gate helpers

Flow peak and cell coordinates are **1-based**. `DensityGrid.zz` has `(x bin, y bin)` columns, while `DensityGrid.z` has shape `(nc, nr)`. Use `grid.z.T` for the peak pipeline, as in the setup, so the coordinates match `zz`.

### `f_plot`

**Description**

Bin two channel vectors into a density grid. Despite its name, this function does not draw a figure.

**Usage**

```text
f_plot(x, y, *, nr=20, nc=20, scale="raw", alpha=0.1)
```

**Arguments**

| Argument | Meaning |
| --- | --- |
| `x`, `y` | Equal-length finite, nonconstant numeric vectors. |
| `nr`, `nc` | Positive integer numbers of bins along `x` and `y`. |
| `scale` | `"raw"` for counts, `"l"` for `log1p(count)`, or `"d"` for a second `log1p` transformation. |
| `alpha` | After transformation, cells below `alpha * maximum_density` become zero. |

**Details**

Use the same channel transformation and bin counts across the steps of a gating workflow. The finder uses 100 × 100 bins; the helper's default is 20 × 20.

**Value**

A [`DensityGrid`](#densitygrid) with density `z`, grid coordinates `x` and `y`, and per-event bin positions `zz`.

**Examples**

```python
raw_grid = flow.f_plot(ssc, fsc, nr=100, nc=100)
assert raw_grid.zz.shape == (len(fsc), 2)
assert raw_grid.z.shape == (100, 100)
```

**See also:** [`local_maxima`](#local_maxima), [`lymphmacro_finder`](#lymphmacro_finder).

### `local_maxima`

**Description**

Find cells that are maxima in a surrounding window and exceed a global density threshold.

**Usage**

```text
local_maxima(z, *, n_row=11, n_col=11, quantile=0.85)
```

**Arguments**

`z` is a two-dimensional density matrix. `n_row` and `n_col` specify the neighborhood size. `quantile` selects the density quantile that maxima must strictly exceed.

**Details**

The maximum filter reflects at matrix boundaries. A flat maximum can yield more than one candidate cell; use `refine_peaks` for the workflow's additional filtering.

**Value**

An integer `(q, 2)` array of 1-based row/column coordinates.

**Examples**

```python
candidate_cells = flow.local_maxima(density, quantile=0.85)
```

**See also:** [`refine_peaks`](#refine_peaks), [`f_plot`](#f_plot).

### `search_ind`

**Description**

Move a candidate coordinate to a maximum in its local search window.

**Usage**

```text
search_ind(x, idx, idy, threshold=2)
```

**Arguments**

`x` is a density matrix. `idx` and `idy` are the 1-based row and column of the starting point. `threshold` sets the window's half-width in cells.

**Details**

Input coordinates are rounded upward; the search window is clipped to matrix bounds. Ties choose the first maximum in row order.

**Value**

A length-two integer array with the selected 1-based row and column.

**Examples**

```python
nearby_peak = flow.search_ind(density, peak_row, peak_col, threshold=2)
```

**See also:** [`local_maxima`](#local_maxima), [`refine_peaks`](#refine_peaks).

### `refine_peaks`

**Description**

Move candidate peaks to local maxima, remove duplicates, and apply the reference workflow's density and boundary filters.

**Usage**

```text
refine_peaks(x, candidates, *, threshold=2)
```

**Arguments**

`x` is the density matrix, `candidates` is a `(q, 2)` array of 1-based coordinates, and `threshold` is passed to `search_ind`.

**Details**

The fixed boundary checks require row coordinates strictly between 10 and 90 and column coordinates below 90. Retained cells must exceed the matrix's 90th density percentile. These rules assume the reference **100 × 100** grid; they are not adjusted automatically for another size.

**Value**

A `(q_kept, 2)` integer coordinate array, ordered by row position. No retained peaks gives shape `(0, 2)`.

**Examples**

```python
refined_peaks = flow.refine_peaks(density, candidate_cells)
```

**See also:** [`search_ind`](#search_ind), [`find_area`](#find_area).

### `find_area`

**Description**

Select dense grid cells within a disc centered on a peak.

**Usage**

```text
find_area(x, idx, idy, t1=35, t2=0.85)
```

**Arguments**

`x` is the density matrix; `idx` and `idy` are the peak's 1-based row and column. `t1` is the disc radius in grid cells, and `t2` is a density threshold relative to the peak.

**Details**

Cells must lie strictly within radius `t1` and have density strictly greater than `t2` times the peak density. Returned coordinates follow the helper's column-by-column traversal.

**Value**

A `(q, 2)` integer array of 1-based row/column coordinates.

**Examples**

```python
population_cells = flow.find_area(
    density, peak_row, peak_col, t1=22, t2=0.25,
)
```

**See also:** [`hull_gate`](#hull_gate), [`mirrored_area`](#mirrored_area).

### `mirrored_area`

**Description**

Select dense cells using the historical mirrored-disc calculation.

**Usage**

```text
mirrored_area(x, idx, idy, t1=35, t2=0.85)
```

**Arguments**

The density matrix, 1-based peak coordinates, radius `t1`, and relative density threshold `t2` have the same roles as in `find_area`.

**Details**

The disc calculation mirrors the peak coordinates, preserving the original workflow's behavior rather than centering the disc as `find_area` does. Use it to reproduce that workflow on its square grid. It is the CLI's default area method.

**Value**

A `(q, 2)` array of 1-based selected cell coordinates.

**Examples**

```python
historical_cells = flow.mirrored_area(
    density, peak_row, peak_col, t1=22, t2=0.25,
)
```

**See also:** [`find_area`](#find_area), [`lymphmacro_finder`](#lymphmacro_finder), [methodology](methodology.md).

### `hull_gate`

**Description**

Convert a set of population grid cells into an event gate in the original scatter channels.

**Usage**

```text
hull_gate(fsc_a, ssc_a, zz, cells)
```

**Arguments**

| Argument | Meaning |
| --- | --- |
| `fsc_a`, `ssc_a` | Original scatter-channel vectors. |
| `zz` | `(n_events, 2)` per-event 1-based bin coordinates from the matching `DensityGrid`. |
| `cells` | `(q, 2)` 1-based population cell coordinates, aligned with `zz`. |

**Details**

The helper first selects events through a hull of grid cells, then forms a hull in raw channel coordinates and tests all events against it. Too few points or a degenerate hull produces an all-false mask. Always preserve event order between the original channels and `zz`.

**Value**

A Boolean vector of shape `(n_events,)`.

**Examples**

```python
single_gate = flow.hull_gate(fsc, ssc, grid.zz, population_cells)
assert single_gate.shape == fsc.shape
```

**See also:** [`find_area`](#find_area), [`gates`](#gates).

### `DensityGrid`

The result of `f_plot`, exported from `datanuggets_flow`.

| Field | Shape | Meaning |
| --- | --- | --- |
| `z` | `(nc, nr)` | Transformed and thresholded cell densities. |
| `x` | `(nr,)` | Grid positions along the first channel. |
| `y` | `(nc,)` | Grid positions along the second channel. |
| `zz` | `(n_events, 2)` | Per-event 1-based `(x bin, y bin)` coordinates. |

The container is frozen, but its arrays do not have the read-only-copy guarantee of the core result classes.

### `FinderPeaks`

The result of `finder_peaks`, a named tuple exported from `datanuggets_flow`.

| Field | Shape | Meaning |
| --- | --- | --- |
| `density` | `(100, 100)` | The finder's `log1p` density grid, `grid.z.T`: SSC-A bins as rows, FSC-A bins as columns. |
| `candidates` | `(q, 2)` | 1-based `(row, col)` of every local maximum. |
| `peaks` | `(p, 2)` | 1-based `(row, col)` of the refined peaks, in the finder's population order. |
| `fsc` | `(100,)` | Raw FSC-A value at each column. |
| `ssc` | `(100,)` | Raw SSC-A value at each row. |

## The flow pipeline library

`datanuggets-flow` prints, asks and handles its output folders around six submodules of `datanuggets_flow`, which a script or another front end can call directly. A seventh, `datanuggets_flow.livecells`, serves the app's step that keeps live white cells before the clustering; [Live cells](#live-cells) describes it. They never print or ask: progress comes back as `StageEvent`s and refusals as `FlowError`s. Import them by their module; `datanuggets_flow` itself doesn't import them. They read and write with the package's dependencies: flowio to read FCS files, pandas for the tables, matplotlib for the figures and scikit-learn for the t-SNE. Each is imported only where it's used, except in `figures`.

| Module | Public names |
| --- | --- |
| `datanuggets_flow.settings` | `GateSettings`, `ClusterSettings`, `check_channels`, `check_cofactor`, `check_groups`, `cli_flag`, `AREAS`, `DISC_ALIASES`, `FLAGS`, `GROUP_NAME` |
| `datanuggets_flow.pipeline` | `gate_stage` and `cluster_stage`; the steps they run, `read_fcs`, `resolve_cofactor`, `negative_tally`, `auto_cofactor`, `gate_channels`, `on_channels`, `on_scale`, `gate_files`, `population_stats`, `population_table`, `parse_pops`, `selection_choices`, `parse_selection`, `pops_spec`, `pick_events`, `parse_groups`, `default_channels`, `resolve_channels`, `selection_table`, `pooled_scaling`, `make_nuggets`, `cluster_nuggets`, `tsne_embedding`, `result_tables` and `write_tables`; the header reader `read_ranges` and `decode_ranges`, for a front end that shows the channels' ranges; the types `StageEvent`, `Sample`, `PopStats`, `Kept`, `Scaling`, `Pool`, `Tables`, `RunResult`, `Cofactor`, `NegativeTally`, `Reader`, `RangesReader` and `OnEvent`; `MIN_KEPT_EVENTS` (2) and `MIN_OCCUPIED_NUGGETS` (3) |
| `datanuggets_flow.state` | `save_gates`, `load_gates`, `GateFolder`, `changed_versions`, `check_identity`, `file_sha256`, `check_new`, `begin`, `finish`, `write_run`, `clustering_record` and `run_transform`; the record's constants `GATES_SCHEMA`, `RUN_SCHEMA`, `MARKER`, `MARKER_TEXT`, `GATE_FILES`, `NPZ_KEYS`, `ENTRY_KEYS`, `FIXED`, `READER` and `PACKAGES` |
| `datanuggets_flow.figures` | `local_maxima_figure`, `gates_figure`, `result_figures`, `png_figure` and `save_figures` |
| `datanuggets_flow.compare` | `cluster_markers`, `group_summary` and `group_markers` |
| `datanuggets_flow.outputs` | `viewer_tables`, the tables a run writes after its own; the steps it runs, `pool_colors`, `pool_view`, `pca_tables`, `cells_table`, `groups_table` and `sample_cells`; the type `CellSample` |
| `datanuggets_flow.exceptions` | `FlowError` |

### Flow settings

`GateSettings` and `ClusterSettings` are frozen, keyword-only dataclasses whose fields are the command's flags, with the same defaults, taken from `datanuggets_flow._defaults`:

```text
GateSettings(*, fsc=None, ssc=None, disc="reference", t11=(22,), t21=(0.25,),
             t12=20, t22=0.5, n_row=11, n_col=11)
ClusterSettings(*, channels=None, exclude_channels=(), cofactor="auto", standardize=True,
                dn_num1=10000, dn_num2=1000, center_method="original", seed=291102,
                draws="r", n_jobs=-1, k=8, method="wkmeans", num_init=10, max_iter=100,
                tsne=True, tsne_perplexity=30.0, tsne_seed=0,
                row_filters=(), groups=None, cells_per_file=2000)
```

`fsc` and `ssc` name the two channels the gate takes, across and up. `None` leaves one to the first file: `pipeline.gate_channels(pnn, fsc=None, ssc=None)` gives the pair for channels `pnn`, each kept when given, and for one not given the first forward (or side) scatter channel that ends in `-A`, else the first scatter channel, else the first of `default_channels(pnn)`, never the other's channel, and `None` when none is left. Scatter is a name `FS` or `SS` followed by `C`, a space, a dash, an underscore or nothing, in any case and in ASCII (`_defaults.FLOW_SCATTER_PATTERNS`, forward first): `FSC-A`, `SSC-B-A`, a Beckman Navios's `FS INT` and `fsc-a`, never a marker such as `SSEA4-A`. `pipeline.on_channels(settings, pnn)` returns the settings with them settled; `gate_files` settles them on its first file, and `gate_stage` and `save_gates` record the settled pair. `check()` refuses an `fsc` or `ssc` that is neither `None` nor a channel's name, and an `fsc` equal to `ssc`. `t11` and `t21` hold one value for every file or one per file. `channels=None` takes the default channel rule, `pipeline.default_channels(pnn)` of the first file, less `exclude_channels`: every `-A` channel but scatter, or every channel but those and Time when there are fewer than two distinct ones. `check()` returns the settings when every value is usable and raises `FlowError` otherwise. `GateSettings.check(n_files)` also checks that `t11` and `t21` give one value or one per file, and `for_file(i)` gives [`gate_peaks`](#gate_peaks)' keyword arguments for file `i`, counting from 0. `to_dict()` gives the settings as JSON writes them, and `from_dict()` reads them back and refuses a key that isn't a setting. `ClusterSettings.from_dict()` reads a record saved before `method` existed as `method="tree"` with `center_method="mean"`, unless the record names a center method, since those runs cut the tree of mean centers; and a record saved before `draws` existed as `draws="numpy"`, so an old run builds the nuggets it built then. `check_channels(channels)` raises `FlowError` for a channel list that doesn't hold two or more distinct channels, or that repeats one: `ClusterSettings.check()` runs it on `channels`, and `resolve_channels` on the list it settles on. `cli_flag(name)` is the flag that sets `name`, such as `--dn-num2` for `dn_num2`, `--jobs` for `n_jobs` and `--filter` for `row_filters`. `FLAGS` holds the settings whose flag isn't their name (`n_jobs`: `--jobs`, `tsne`: `--no-tsne`, `standardize`: `--no-standardize`, `row_filters`: `--filter`), and every other name's flag is `--` and the name with `_` written as `-`. `AREAS` maps each `disc` value to its area rule from `datanuggets_flow.peaks` (`"reference"`: `mirrored_area`, `"peak"`: `find_area`), `DISC_ALIASES` maps the old `disc` names still read to their current ones (`"his"` is `"reference"`), and `GROUP_NAME` is the compiled pattern `check_groups` applies to a group name.

`row_filters` holds [filter specs](cli.md#row-filters) on `$PnN` channels' raw values, as strings, which `ClusterSettings.filters()` parses, refusing a bad one with `FlowError` param `row_filters`. `groups` names one group per gated file, in file order; `check()` runs `check_groups(groups)` on the names, and `cluster_stage` counts them against the samples. `parse_groups(spec, n_files)` reads `--groups`' `;`-separated names, refusing a count other than `n_files` with param `groups`. `cells_per_file` is how many of each file's kept cells `cells.csv` samples, 0 for none. A record saved before these fields existed still loads, with their defaults.

`method` sets how the pooled nuggets are clustered ([design choices](methodology.md#design-choices-in-the-pipeline)). `"wkmeans"`, the default, is `WCluster`'s `Wkmeans` on the nuggets of weight above 0, with `num_init` starts of up to `max_iter` rounds, drawn from `RDraws(seed)`. `"tree"` is the hierarchical tree, `Whclust` cut by `cut_tree` into `k` clusters, or into as many as there are nuggets in use when that's fewer; it doesn't use `num_init` or `max_iter`. `center_method` is `create_dn`'s, `"original"` by default. `draws` says what each file's `create_dn` draws from `seed`: `"r"`, the default, `RDraws(seed)`, so each file's nuggets are `create.DN`'s, or `"numpy"`, NumPy's draws from the integer seed, which every run saved before `draws` existed used. Weighted k-means draws R's numbers either way. `check()` refuses another `method`, `center_method` or `draws`, and a `num_init` or `max_iter` that isn't a whole number from 1, as `num_init is 0; it takes a whole number from 1`.

`cofactor` and `standardize` set the two stages before the nuggets ([Transform and Scale](methodology.md#transform-and-scale)). `cofactor` is the Transform stage, `arcsinh(x / cofactor)` or linear at 0. It takes a number from 0, used for every channel, or `"auto"`, the default, which `cluster_stage` turns into one cofactor per channel once, from the raw values of the cells it clusters, before any arcsinh; the settings keep `"auto"` as asked. `check_cofactor(cofactor)` raises `FlowError` naming `cofactor`, `cofactor is -1; it takes auto, 0 (linear) or a positive number`, for anything else, such as `"Auto"`, a negative number, NaN or `True`; `check()` runs it. `standardize`, `True` by default, is the Scale stage: every clustered channel is scaled to mean 0 and SD 1 by its mean and SD pooled over all clustered files' kept cells. `False` skips it and gives the tables of earlier versions; `check()` refuses anything but `True` or `False`, such as `1`, with param `standardize`, and `cli_flag("standardize")` is `--no-standardize`. A record saved before `standardize` existed loads with it on.

`resolve_cofactor(cofactor, tally=None)` gives the cofactor a run uses, as a `Cofactor`. A number, 0 included, comes back as `Cofactor(value, "set")`, for every channel, and `tally` isn't used. `"auto"` gives `auto_cofactor(tally)`, `tally` being the run's `NegativeTally` or a function that makes it, which is called only for `"auto"`, so a run given a number makes no extra pass over its files; `"auto"` with no `tally` raises `ValueError`. `check_cofactor` runs first, so anything else is refused with `FlowError` naming `cofactor` before a cell is counted.

`negative_tally(samples, chosen, channels, settings, *, read=read_fcs, on_event=None)` makes the tally. It reads each file in turn, the same pass `pooled_scaling` makes, and counts the raw values on `channels`, before any arcsinh, of the cells `make_nuggets` clusters: the chosen populations' cells that pass the row filters, in every file keeping `MIN_KEPT_EVENTS` or more of them. `settings.cofactor` isn't used, so it may be `"auto"`. `on_event` hears a `"cofactor"` event per file, its message empty and its data `{"cells": n}`, 0 for a file left out. When no file keeps a cell it raises the `FlowError` `make_nuggets` raises. `NegativeTally(p)` holds, for each of `p` channels, `cells`, the cells counted, `negative`, those below 0, and `counts`, a histogram of `|x|` over those below 0, all int64. Its bins are `_defaults.FLOW_COFACTOR_HIST`'s: 400 log-spaced bins per decade from 0.01 to 10⁸, with one below and one above. `add(x)` counts an array with one row per cell and one column per channel, so the files can be added one at a time and in any order and give the same tally; a NaN is a cell but not one below 0. `auto_cofactor(tally)` applies the rule ([Transform and Scale](methodology.md#transform-and-scale)) to it. For each channel it takes `f`, the share of its cells below 0, and `sd`, their spread: the median of `|x|`, found in the histogram at half their count and placed linearly in `log10 |x|` within its bin, divided by 0.6745, and `None` with no cell below 0. The cofactor is `max(150, sd)` when `f` is at least 0.01, and 150 otherwise. A tally of no cells gives 150 for every channel. The three numbers are `FLOW_COFACTOR_FLOOR`, `FLOW_COFACTOR_MIN_NEGATIVE` and `FLOW_COFACTOR_MAD_Z` in `_defaults`.

`Cofactor(value, source, range=None, values=None, negative=None, spread=None)` is the cofactor a run used. A set one has `source` `"set"` and `value`, the number for every channel. An auto one has `source` `"auto"`, `values`, each clustered channel's cofactor in channel order, `negative`, each one's `f`, `spread`, each one's `sd`, and `value`, the floor. `range` is only on a record of the earlier rule, which picked one auto number for the whole run from the files' headers: the widest marker channel range they gave, `None` when one gave none. `applied` is what the steps after the resolve take as `settings.cofactor`, the tuple `values` or the number `value`, and `per_channel(p)` gives each of `p` channels' cofactor as an array, refusing `values` of another length with `ValueError`. `transform()` gives the stage as `run.json` and the `"transform"` event record it:

```text
{"name": "arcsinh", "cofactor_from": "auto", "cofactors": [float],
 "negative_fraction": [float], "negative_sd": [float | null],
 "floor": 150.0, "min_negative_fraction": 0.01}                          auto, one per channel
{"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}         a number
{"name": "none"}                                                         0
{"name": "arcsinh", "cofactor": 150.0, "cofactor_from": "auto", "range": 262144.0}
                                                                         the earlier rule
```

The auto record has no single `cofactor`, since no one number was used, and its lists are unrounded. `cluster_stage` hands `applied` on, so the steps it runs after, `pooled_scaling` and `make_nuggets`, take settings with a number or a tuple of one per channel; called on their own with `"auto"`, they raise `FlowError` naming `cofactor`, and `resolve_cofactor` gives the cofactors to put in its place. `ClusterSettings.check()` refuses a tuple, since a caller sets one number or `"auto"`.

`read_ranges(path)` reads a file's TEXT segment alone, no events, and returns its channels' `$PnN` names, as `read_fcs` names them, and each one's range. `decode_ranges(text)` does the decoding on a header's keywords, in any case and with or without the `$`: the range is the largest value flowio's preprocess gives the channel, `$PnR` for a linear channel, `10 ** f1 * f2` for one whose `$PnE` is `f1,f2` with `f1` above 0 (`f2` taken as 1 when it is 0), divided by `$PnG` when that is neither 1 nor 0. A channel named Time has no gain and is scaled by `$TIMESTEP`, as flowio reads it. A missing `$PnE` is linear and a missing `$PnG` is 1. For `decode_ranges`, the range is `None` where `$PnR` is missing or any of the three doesn't read as numbers, or where the result isn't a positive finite number. `read_ranges` gets its keywords from flowio, which refuses a header whose `$PnR` is missing or whose `$PnR`, `$PnE` or `$PnG` isn't a number, so on such a file it raises flowio's error, as `read_fcs` does; from `read_ranges`, `None` comes from values flowio takes that give no usable range, such as a `$PnR` of 0, a negative or non-finite one, or a log decode that overflows. A `RangesReader` is a stand-in for it, which takes a path and returns the same pair. The gate step reads the ranges for its off-scale rule. `gate_files(paths, settings, *, read=read_fcs, ranges=None, on_event=None)` takes `ranges`, a `RangesReader`, which is `read_ranges` when left out and `read` is `read_fcs`, and none for a stand-in `read`, which has no file behind it. `on_scale(scatter, channels, ranges)` gives the events inside each gate channel's range, or `None` to gate every event: when none is past it, or when more than `FLOW_OFFSCALE_MAX` (1%) of them are, since then the range doesn't describe the values. Events past the range are left out of the finder's grid and of every population, and the file's `"gate"` event says how many. A front end reads the ranges to show each channel's range, as the app's upload view does. The Transform stage's `auto` once picked one cofactor from them, and now reads the cells instead.

`pooled_scaling(samples, chosen, channels, settings, *, read=read_fcs, on_event=None)` reads each kept file in turn and returns a `Scaling(mean, sd, cells, files, skew)`: each channel's pooled mean and SD with `ddof=0`, 1 for a constant channel, and its skewness, 0 for a constant channel, over the `cells` kept cells, after the row filters, of the `files` clustered. `on_event` hears a `"scale"` event per file, its message empty and its data `{"cells": n}`. `scaling.apply(x)` scales rows of transformed values and `scaling.undo(x)` takes scaled ones back; `record()` is what `run.json` keeps. `make_nuggets(..., scaling=None)` makes each file's nuggets of the scaled cells, with `settings.center_method` and `settings.draws`, and keeps each nugget's cell mean on its `Kept` when the centers aren't means. `cluster_nuggets(kept, k, scaling=None, *, method="wkmeans", num_init=10, max_iter=100, seed=291102, n_jobs=1)` clusters every file's nuggets together, leaving out those of weight 0, and keeps the scaling on the `Pool`, whose `values(x)` gives scaled values back in the transformed units, unchanged without one. Under `"wkmeans"` it clusters into exactly `k`: with fewer than `2 * k` nuggets in use, or when `wkmeans` gives up drawing a start, it raises `FlowError` rather than clustering into fewer. Too few nuggets names `dn_num2` as the setting to change, and a failed start names `k` and suggests the tree. A cluster that empties during the moves lowers `pool.k`, and the rest keep R's order, numbered from 0 without gaps. Under `"tree"` it cuts into `k`, or as many as there are nuggets in use. `pool.cell_means()` gives each nugget's cell mean, which the marker tables read, and `pool.wwcss` the total weighted within-cluster sum of squares of the nuggets in use, under either method.

### `FlowError` and `StageEvent`

`FlowError(message, param=None)` is a `ValueError` for a bad setting or input. A message names its setting as `{param}`: `str(e)` writes the setting's name and `e.cli(cli_flag)` its flag, so one error reads `n_jobs is 0; ...` from Python and `--jobs is 0; ...` from the command. `e.param` is the setting's name, and `"from_gates"` for a gate folder `load_gates` refuses.

`StageEvent(stage, file, n_files, message, data)` is what a stage passes to `on_event` as it goes. `stage` is `"gate"` for each file, `"channels"` for each file `cluster_stage` reads while it checks the default channels for values that aren't numbers, with an empty `message` and `{"cells": n}`, `"select"`, `"cofactor"` for each file `negative_tally` reads while `auto` picks the cofactors, with an empty `message` and `{"cells": n}`, `"transform"`, whose `message` names the cofactor used and why, with a line per channel for `auto`, and whose `data` holds `{"transform": cofactor.transform()}`, `"scale"`, whose `data` holds `{"standardize": scaling.record()}` or `{"standardize": False}`, `"nuggets"` for each kept file, `"cluster"`, whose `data` holds each cluster's `percent` and `k`, the clusters made: under the tree fewer than `settings.k` when there are fewer nuggets in use, and under weighted k-means fewer only when a cluster empties during the moves, `"tsne"` before the 2-D fit and again before the 3-D call, which fits nothing for fewer than three channels or nuggets, with an empty `message` and `{"nuggets": n, "dims": 2}`, then `3`, or `"figures"` once the viewer tables are written and before the figures are drawn, with an empty `message` and `{}`. `file` is the file's number, from 1, or `None` for the whole run. `message` holds the lines the command prints, and `data` the same facts as values. With `on_event=None` nothing is reported. A handler that raises stops the stage at that event, which is how the app cancels a run.

### Stages

```text
gate_stage(paths, out, settings, *, read=read_fcs, ranges=None, on_event=None, figure=None)
load_gates(folder)
cluster_stage(samples, chosen, out, settings, *, read=read_fcs, on_event=None, figure=None)
```

`gate_stage` gates the files at `paths` in order with `gate_files`, which takes its `read` and `ranges`, with a `GateSettings`, into the existing folder `out`: it draws `local_maxima.png` and `gates.png`, saves `gates.npz` and then `gates.json`, and returns one `Sample` per file. `load_gates` checks a gate folder as `--from-gates` does, raising `FlowError` on the first problem, and returns a `GateFolder(path, settings, samples, versions)`. It doesn't refuse a folder gated under other package versions, since the masks are the gates: `changed_versions(folder.versions)` gives each package whose version differs now, as `(recorded, now)`, and the command prints them in one line. `cluster_stage` clusters the populations `chosen` gives for each sample, numbered from 1 with `[]` leaving a file out, with a `ClusterSettings`, into the existing folder `out`. It settles the channels: when `settings.channels` is `None`, it reads each kept file once, sending a `"channels"` event per file, and leaves out a default channel holding NaN or an infinite value among the kept cells, with a `DataNuggetWarning` naming it, and raises `FlowError` naming `channels` when fewer than two are left; a channel named in `settings.channels` is refused instead. Then it settles the cofactor, with `resolve_cofactor`: `"auto"` first reads each kept file with `negative_tally` and picks a cofactor per channel from the cells it will cluster, and a number makes no such pass. It reads each kept file again, keeping only the cells that pass `settings.row_filters`, writes the tables, the viewer tables (`outputs.viewer_tables`: `cluster_colors.csv`, `cluster_markers.csv`, the `pca_*.csv` tables, `tsne.csv`, `tsne3d.csv` with a 3-D t-SNE, `cells.csv` (unless `cells_per_file` is 0) and, with groups, the group tables, as [Outputs](cli.md#outputs) describes) and the clustering's figures, in each cluster's `cluster_colors` colour, and returns a `RunResult` with the channels, the tables, the pooled nuggets and their clusters, the t-SNE coordinates, the files written and the `Cofactor` used. Both stages check their settings before they read a file, `gate_stage` with `check(len(paths))`. They also refuse input the command never passes them but another front end can: `gate_stage` with no paths raises `FlowError("no files to gate")`, and `cluster_stage` with no samples raises `FlowError("no gated files to cluster")`, or with a `chosen` that doesn't give one choice per sample, `pops gives 2 choices for 3 files; give one per file` with `param` `"pops"`. A short `chosen` would otherwise drop the missing files from the tables without a word.

`compare.cluster_markers(kept, pool, labels)`, `compare.group_summary(summary, groups)` and `compare.group_markers(markers, groups, channels, labels)` make `cluster_markers.csv`, `group_summary.csv` and `group_markers.csv` as DataFrames, `groups` mapping each file number to its group; the reference group is the group of the lowest-numbered kept file. `group_summary`'s log2 fold change adds a pseudocount of half a cell per file, 50 / N percentage points for a file of N kept cells averaged over the kept files, which it writes in its `log2fc_pseudocount` column. The tables are descriptive and test no difference. `result_figures(..., colors=None)` takes each cluster's colour, such as `outputs.pool_colors(pool)`; `None` keeps matplotlib's colour cycle, the same colours up to 8 clusters.

`read` takes a path and returns the events and each channel's `$PnN` and `$PnS` names, as `read_fcs` does, so stored arrays can stand in for files; with `cofactor="auto"` each kept file is read once more, for the tally. `figure` makes each figure. Its default, `matplotlib.figure.Figure`, leaves nothing in pyplot's registry, so a server can draw run after run; the command passes `plt.figure` to show them.

The command adds the rest of a run folder: `begin(out)` makes the folder with its `INCOMPLETE.txt` and `finish(out)` removes the marker, `write_run(..., scaling=None, cofactor=None, pool=None)` writes `run.json`, given the run's `result.pool.scaling` so it records the Scale stage's statistics, its `result.cofactor` so `transform` records the cofactors used, and its `result.pool` so `clustering` records how the nuggets were clustered and the R calls that rebuild them, as `clustering_record(settings, pool)` gives it ([flow run records](reproducibility.md#flow-run-records)); without `pool` the key is left out. It raises `ValueError` before writing when `scaling` is missing for settings with `standardize` on or given for settings with it off, and when `cofactor` doesn't agree with `settings.cofactor`: settings with `"auto"` need a cofactor picked as auto, with one value per channel when it has values, and settings with a number need none or that number as set. `run_transform(record)` reads a `run.json` record's Transform stage as `Cofactor.transform()` gives it: a per-channel record, or one of the earlier header rule with its `range`, as written; an arcsinh recorded before `cofactor_from` existed reads as `"set"`; and a record with no `transform` reads its settings' cofactor, 6000 when it has none. It raises `ValueError` for a record whose settings ask for `"auto"` but that has no `transform`, since that doesn't say which cofactors the run used. A `--from-gates` run copies the gate figures into its folder. `--gates-only` runs `gate_stage` itself. The one-shot run calls `gate_files` instead, because it asks for the populations after drawing `local_maxima.png` and before drawing `gates.png`.

**Examples**

```python
from pathlib import Path

from datanuggets_flow.pipeline import cluster_stage, gate_stage, parse_selection
from datanuggets_flow.settings import ClusterSettings, GateSettings
from datanuggets_flow.state import load_gates

gates, run = Path("outputs/gates-001"), Path("outputs/run-001")
gates.mkdir(parents=True)
gate_stage(sorted(Path("path/to/fcs_folder").glob("*.fcs")), gates, GateSettings())

folder = load_gates(gates)
chosen = parse_selection("1,2", [len(s["stats"]) for s in folder.samples])
run.mkdir()
result = cluster_stage(folder.samples, chosen, run, ClusterSettings(k=12))
print(result.tables.summary)
```

`parse_selection` reads a `--pops` string against each file's population count, so `"1,2"` keeps Pop 1 and Pop 2 of every file, and refuses a file that has fewer. The example calls no `check()`, because each stage checks its settings first: `GateSettings(t11=(22, 20))` on three files raises `FlowError` with `t11 gives 2 values for 3 files; give one, or one per file` before any file is read. [Staged runs](cli.md#staged-runs) describes the gate folder, and [reproducibility](reproducibility.md#flow-run-records) its records.

### Live cells

```text
suggest_channels(pnn, pns=None)
kept_values(samples, chosen, channels, *, read=read_fcs)
channel_histograms(kept, *, bins=128, cofactor="auto")
count_kept(kept, row_filters)
save_kept_values(kept, path)
load_kept_values(path)
FileValues.kept -> int                  # the file's kept cells, len(values)
ROLES = ("viability", "cd45")
VIABILITY_NAME, CD45_NAME               # the compiled name patterns suggest_channels applies
```

`datanuggets_flow.livecells` serves a front end's step between the population choice and the clustering, where the user keeps the live white cells: the cells below a threshold on a viability dye, which dead cells take up, and above one on CD45, which white cells carry. The user places both thresholds. The module never suggests a value, only which channels look like the dye and CD45, by their names. Like the other flow modules it doesn't print or ask, and it imports neither matplotlib nor pandas, so a server's main process can call it.

`suggest_channels(pnn, pns)` takes a file's `$PnN` and `$PnS` names and returns `{"viability": name | None, "cd45": name | None, "candidates": {"viability": [names], "cd45": [names]}}`, every name a `$PnN`. A channel is a viability candidate when its `$PnN` or `$PnS` holds, in any case, Zombie, LIVE/DEAD (with `/`, a space, `_`, `-` or nothing between the words), Viability, FVS, 7-AAD, DAPI, propidium iodide, or PI as a word of its own, so `PI-A` is one and `PIK3` isn't. It is a CD45 candidate when CD45 stands as a word of its own and isn't followed by an isoform written apart, so `CD45RA`, `CD45RO`, `CD45R` and `CD450` aren't, nor are `CD45-RA`, `CD45 RA`, `CD45_RO`, `CD45.RA`, `CD45/RA`, `CD45 R` or `CD45 RABC`, while `CD45.1`, `CD45.2` and `CD45 PerCP` are. A role's suggestion is its one candidate; among several, the one whose `$PnN` ends in `-A`, when exactly one does; otherwise `None`, and the front end shows the candidates and lets the user choose. On the app's PBMC demo files (Zenodo 22079206: `190.fcs`, `193.fcs`, `199.fcs`, `223.fcs`) it names `FJComp-LIVE DEAD Blue-A` and `FJComp-PerCP-A`, passing over `FJComp-BUV395-A`, whose `$PnS` is `CD45RA`. On the files of Zenodo 18367404 it names `Zombie NIR-A` and `BV570-A`.

`kept_values(samples, chosen, channels)` reads, raw, the values on `channels` of the cells the populations in `chosen` keep. These are the cells `cluster_stage` hands its row filters, read by the same step, which refuses a file that isn't the one gated. `samples` and `chosen` are what `cluster_stage` takes: `load_gates(folder).samples` and one list of population numbers per file, `[]` leaving a file out. A file that keeps no cells isn't read. It returns a `KeptValues(channels, labels, files, cofactor)`, with one `FileValues(number, name, events, pops, values)` per gated file in gate order; `values` holds one row per kept cell, in event order, and one column per channel. `cofactor` is `auto_cofactor` of a `NegativeTally` of these values, over the files keeping `MIN_KEPT_EVENTS` or more: one cofactor per channel, the ones a run clustering the same cells on these channels, with no row filters, would pick by default. `FlowError` names `channels` for a list that is empty or repeats a channel, or a channel missing from a file that keeps cells. It names `pops` for a `chosen` without one choice per file, a population a file doesn't have, or a choice that keeps no cells anywhere.

`channel_histograms(kept, *, bins=128, cofactor="auto")` bins each channel on `t = arcsinh(x / c)`, `c` that channel's cofactor, or on `x` itself with `cofactor=0`. `"auto"` takes `kept.cofactor`, each channel's own cofactor; values saved under the earlier header rule draw every channel on their one number, and values saved before a cofactor was recorded on 6000. A number is used as given for every channel. The bin edges are shared by every file. The range runs from the pooled 0.1% to the 99.9% quantile, widened by 5% of its width on each side but not past the smallest and largest value. Every cell outside it is counted in its file's `below` or `above`, and a NaN in `nan`, so each file's counts, `below`, `above` and `nan` add up to its kept cells. The result is plain JSON values:

```text
{"cofactor": float, "bins": int, "kept": int,
 "files": [{"number", "name", "events", "pops", "kept"}],
 "channels": [{"channel", "label", "lo", "hi", "edges", "counts", "below", "above", "nan",
               "files": [{"number", "counts", "below", "above", "nan"}]}],
 "cofactor_from": "auto" | "set",
 "cofactors": [float], "negative_fraction": [float], "negative_sd": [float | None]}
```

When one number serves every channel, a number given or values saved under an earlier rule, `cofactor` comes first and the three lists are left out. When each channel has its own, under `"auto"`, there is no `cofactor`, and `cofactors`, `negative_fraction` and `negative_sd` follow `cofactor_from`, in the order of `channels`, as `Cofactor.transform()` gives them; the keys then run `bins`, `kept`, `files`, `channels`, `cofactor_from`, `cofactors`, `negative_fraction`, `negative_sd`. `edges` holds `bins + 1` values from `lo` to `hi`, and `counts` the pooled counts, the sum of the files'. With a positive cofactor, a position `t` on channel `j`'s axis is the raw value `cofactors[j] * sinh(t)`, or `cofactor * sinh(t)` when there is one number, the inverse of the transform. With `cofactor=0` the axis is linear and `t` is the raw value itself; `cofactor * sinh(t)` would give 0 there. `FlowError` names `bins` for a value that isn't a whole number from 1, `cofactor` for one that isn't `"auto"` or a number from 0, such as a negative, NaN or infinite one, and `channels` for a channel with no finite value in the kept cells.

`count_kept(kept, row_filters)` counts how many of each file's kept cells pass every filter on their raw values, by `filters.filter_mask`. `row_filters` holds [filter specs](cli.md#row-filters) or `RowFilter`s. These are the counts `cluster_stage` writes in `selection.csv`'s `filtered` when `ClusterSettings.row_filters` holds the same filters:

```text
{"row_filters": [canonical spec], "kept": int, "passed": int,
 "files": [{"number", "name", "events", "kept", "passed", "left_out"}]}
```

`left_out` is true for a file the run would leave out, one where fewer than `MIN_KEPT_EVENTS` cells pass. No filters count every kept cell. A spec that doesn't parse, a filter on a channel the values don't hold, or a value that isn't a finite number raises `FlowError` naming `row_filters`.

`save_kept_values(kept, path)` writes `kept` as one `.npz` file at `path`, with no extension added. It holds a JSON record of the channels, the files and the cofactor, and each file's values: float32 where that keeps every value exactly, which values read from a float32 FCS file always do, and float64 otherwise. `load_kept_values(path)` reads it back as float64, the same numbers, with the cofactor's lists as tuples, and raises `ValueError` for a file it didn't write. A file saved under the earlier header rule loads its one cofactor as saved, and one saved before the cofactor was recorded loads with `cofactor` `None`. A server keeps the values this way between a histogram request and the count requests that follow it, so a count reads no FCS file.

The user's choices go to the run as settings: the two thresholds as `row_filters`, and the viability channel as `exclude_channels`, so the dye's values only decide which cells are clustered. [Keeping live white cells](cli.md#keeping-live-white-cells) gives the same run on the command line.

```python
from pathlib import Path

from datanuggets.filters import RowFilter, format_filter
from datanuggets_flow.livecells import channel_histograms, count_kept, kept_values, suggest_channels
from datanuggets_flow.pipeline import cluster_stage, parse_selection
from datanuggets_flow.settings import ClusterSettings
from datanuggets_flow.state import load_gates

folder = load_gates(Path("outputs/gates-001"))
chosen = parse_selection("1,2", [len(s["stats"]) for s in folder.samples])
first = folder.samples[0]
names = suggest_channels(first["pnn"], first["pns"])
dye, cd45 = names["viability"], names["cd45"]  # None when no single channel fits; then choose
kept = kept_values(folder.samples, chosen, [dye, cd45])
hist = channel_histograms(kept)  # draw these and read the thresholds off them

below = float(input(f"Keep the cells below which {dye} value? "))
above = float(input(f"Keep the cells above which {cd45} value? "))
filters = [format_filter(RowFilter(dye, "<", below)), format_filter(RowFilter(cd45, ">", above))]
for f in count_kept(kept, filters)["files"]:
    print(f["name"], f["passed"], "of", f["kept"], "kept cells pass")

run = Path("outputs/run-live-001")
run.mkdir()
settings = ClusterSettings(row_filters=tuple(filters), exclude_channels=(dye,))
cluster_stage(folder.samples, chosen, run, settings)
```

`format_filter` brackets a channel name that holds a space, as in `[FJComp-LIVE DEAD Blue-A] < ...`, so the spec parses back to the same filter.

## Plotting

### `gates`

**Description**

Draw raw scatter-channel events with candidate populations overlaid.

**Usage**

```text
gates(fsc_a, ssc_a, masks, *, title=None, ax=None, channels=None)
```

**Arguments**

`fsc_a` and `ssc_a` are the original event channels. `masks` is a Boolean `(n_events, n_populations)` array. `title` optionally labels the plot, and `ax` supplies axes. `channels`, when given, names the two channels on the axes, such as `("FSC-A", "SSC-A")`, or `("FSC-H", "SSC-H")` for a file gated on heights. Without it the axes have no labels.

**Details**

All events appear in gray; nonempty population masks are colored on top. Display names such as “Pop 1” number the drawn population columns for readability, without assigning biological cell types.

**Value**

The Matplotlib axes.

**Examples**

Use the measured channels and `masks` from the [flow example](#lymphmacro_finder):

```python
fig, ax = plt.subplots()
plot.gates(fsc, ssc, masks, title="Candidate populations", ax=ax)
```

**See also:** [`lymphmacro_finder`](#lymphmacro_finder), [`hull_gate`](#hull_gate), [`peaks`](#peaks).

### `peaks`

**Description**

Draw the gate finder's density grid with its local maxima and the peaks that seed each population.

**Usage**

```text
peaks(fp, *, title=None, ax=None, channels=None)
```

**Arguments**

`fp` is a [`FinderPeaks`](#finderpeaks) from `finder_peaks`. `title` optionally labels the plot, `ax` supplies axes, and `channels`, when given, names the two channels on the axes. Without it the axes say only that the grid is square-root scaled.

**Details**

The grid is drawn with the first channel gated on across and the second up, as in `gates`, on the finder's square-root scale with tick labels in raw units; empty bins are blank. Every local maximum is an open circle and each kept peak a red cross labelled with the Pop number it seeds in `gates`. A colorbar is added to the axes' figure.

**Value**

The Matplotlib axes.

**Examples**

```python
fig, ax = plt.subplots()
plot.peaks(flow.finder_peaks(fsc, ssc), title="Density peaks", ax=ax)
```

**See also:** [`finder_peaks`](#finder_peaks), [`gates`](#gates).
