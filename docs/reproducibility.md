# Reproducibility

## Datasets

### Zenodo record 22079206

The flow data is [Zenodo record 22079206](https://zenodo.org/records/22079206), "Flow cytometry data of PBMC of critically ill, mechanically ventilated patients". It's licensed under CC BY 4.0. It holds 44 FCS 3.1 files from a Cytek Aurora, 10,183,290 events in all and 20,844 to 516,810 a file. The flow comparisons below take a folder holding them.

The fixtures in `tests/fixtures/flow/` are three of its files, `154`, `202` and `223`, each thinned to every k-th event and cut at 50,000 events. `benchmarks/flow/record.py` recorded them on an Apple M4 machine with 16 GB on 2026-10-12 from Prof. Cabrera's own Python. Their [README](../tests/fixtures/flow/README.md) gives each file's k, its populations and every key the files hold.

## Experiments

### Flow: Cabrera's script against its pieces

The flow comparisons run Prof. Cabrera's gate finder, in its Python version ported from the original R code, against `datanuggets_flow`. `benchmarks/flow/` holds the reference functions word for word in `cabrera_reference.py`, the whole reference script in `run_cabrera.py` with its two paths read from the command line and matplotlib drawing on Agg so it runs unattended, nothing else changed, and the reference finder cut at its steps in `cabrera_pieces.py`. [methodology.md](methodology.md) describes the finder and where the port departs from it.

The reference script reads a workbook whose second sheet has a `Filename` column, and the folder those files are in. `prepare.py` writes one for a folder of FCS files, in name order, to `<folder>/metadata.xlsx` unless `--out` says otherwise. `--source` joins the columns of the record's metadata sheet on its `file_name` column, and `--limit N` keeps the first N files:

```sh
uv run python benchmarks/flow/prepare.py <folder> --limit 4
```

`check_reference.py` runs the whole reference script with FlowKit and checks that its masks equal the masks of `cabrera_pieces.py` on the arrays the comparison reads, flowio's. The script reads the first four samples in FlowKit's order with the thresholds `t0 = [22, 20, 18, 18]` and `t00 = [0.25, 0.5, 0.5, 0.5]`, so the workbook needs at least four files. FlowKit needs pandas below 3 and the lock has pandas 3, so it runs in a throwaway environment:

```sh
uv run --no-project --with flowkit --with openpyxl --with matplotlib --with flowio \
    python benchmarks/flow/check_reference.py <metadata.xlsx> <folder>
```

For each sample it prints whether flowio's arrays equal FlowKit's and whether the script's masks equal those of the pieces, then how many samples match. It exits with 1 unless all of them do. On an Apple M4 machine with 16 GB it matched on all four of the files it was given, masks and arrays both, on 2026-10-12.

### Flow: compare.py, piece by piece

`compare.py` runs the reference code and ours piece by piece on real FCS files, each piece on the same arrays on both sides, timed as the median of `--repeat` runs. It runs in the repo's environment, whose dev group has flowio and matplotlib:

```sh
uv run python benchmarks/flow/compare.py <file.fcs | folder> --repeat 5
uv run python benchmarks/flow/compare.py --metadata <folder>/metadata.xlsx --dir <folder> --t0 22,20,18,18 --t00 0.25,0.5,0.5,0.5
```

| Argument | Default | Meaning |
| --- | --- | --- |
| `target` | none | an FCS file, or a folder whose `*.fcs` files run in name order |
| `--metadata`, `--dir` | none | the reference script's workbook and its folder, in place of `target`: the files of the second sheet's `Filename` column, in the sheet's order |
| `--t0` | 22 for every file | `t11` per file, as `22,20` or `22 20` |
| `--t00` | 0.25 for every file | `t21` per file |
| `--repeat` | 3 | runs per piece, timed as their median |
| `--out` | `tmp/flow` | where the pictures and `summary.csv` go |
| `--no-png` | off | skips the pictures |

It stops with a usage error if it gets both `target` and `--metadata` or `--dir`, or neither a `target` nor both of them, a `--repeat` below 1, or a number of thresholds that isn't one per file. `--t0` and `--t00` pair with the files in the order they run, so with `--metadata` they follow the workbook's rows. The reference script itself pairs its thresholds with the samples in FlowKit's `$FIL` order instead, which [methodology.md](methodology.md) explains.

On Windows, `.\benchmarks\flow\compare.ps1` takes the same arguments, `--metadata` and an unquoted `22,20,18,18` included. It runs `compare.py` in the repo's `.venv`, writes to `tmp\flow`, refuses `--out`, and opens the picture the run wrote.

```powershell
.\benchmarks\flow\compare.ps1 --metadata <folder>/metadata.xlsx --dir <folder> --t0 22,20,18,18 --t00 0.25,0.5,0.5,0.5
```

For each file it prints a table like this one, from an Apple M4 machine with 16 GB on `202.fcs`:

```text
202.fcs: 282,270 events, t11=22 t21=0.25, median of 3
  piece             his s     ours s   speedup  match
  1 grid           0.0169     0.0017     10.0x  equal
  2 maxima         0.0071     0.0001     50.5x  equal
  3 peaks          0.0001     0.0001      1.2x  equal, 3 peaks
  4 area           0.0004     0.0001      3.6x  his keeps 586 cells ours doesn't, ours 1485 his doesn't (the disc)
  5 gate           3.1627     0.0436     72.6x  on his cells: equal
  finder his       3.2071     0.0577     55.5x  his find_area: equal
  finder fixed     3.2071     0.0599     53.5x  his 3 populations, ours 3, 107,909 events gated differently (the disc)
  6 graph          0.4674     0.1451      3.2x  his masks both, mean pixel difference 0.05 of 255
```

`5 gate` runs the reference gate and ours on the reference area's cells. `finder his` runs the port's whole finder with the reference `find_area` in place of its own, and `finder fixed` runs it as shipped, both against the reference finder end to end. `6 graph` draws both figures from the reference masks, so the difference is the drawing alone, and times each to the finished pixels.

The picture, `<file>_compare.png`, shows the reference figure, ours from the shipped finder, and the events whose populations differ in red. Each piece's row goes into `summary.csv`, with the columns `file`, `events`, `piece`, `his_s`, `ours_s`, `speedup` and `match`, as each file ends, so a stopped run keeps what it did. A file that fails to run is reported and skipped. Over several files it also prints each piece's median, smallest and largest speedup. It exits with 1 if a file fails to run, or if the grid, the maxima, the peaks, the gate on the reference cells or `finder his` differ, beyond events within 1e-9 of the data's range from the hull's edge.

### Flow: speed over the 44 files

This is `compare.py` on a folder holding all 44 files of the Zenodo record, with `--repeat 5`:

```sh
uv run python benchmarks/flow/compare.py <folder> --repeat 5
```

On an Apple M4 machine with 16 GB, over all 44 files: 10,183,290 events, 20,844 to 516,810 a file, each piece timed as the median of 5 runs. Committed on 2026-10-12.

| Piece | Reference, median s | Ours, median s | Speedup, median | Smallest | Largest |
| --- | --- | --- | --- | --- | --- |
| `1 grid` | 0.0163 | 0.0014 | 11.4x | 7.9x | 12.0x |
| `2 maxima` | 0.0077 | 0.0001 | 54.0x | 49.7x | 58.6x |
| `3 peaks` | 0.0001 | 0.0001 | 1.1x | 0.9x | 1.2x |
| `4 area` | 0.0003 | 0.0001 | 3.7x | 3.3x | 3.9x |
| `5 gate` | 2.1350 | 0.0348 | 64.0x | 21.0x | 126.2x |
| `finder his` | 2.1524 | 0.0458 | 49.7x | 18.1x | 93.0x |
| `finder fixed` | 2.1524 | 0.0461 | 47.8x | 20.2x | 84.1x |
| `6 graph` | 0.3797 | 0.1209 | 3.1x | 1.8x | 4.0x |

The grid, the maxima and the peaks equal the reference output on all 44 files. The gate on the reference cells and `finder his` equal the reference output on 40, and on the other 4, `186`, `190`, `278` and `345`, one event each differs, lying exactly on the hull's edge. The reference finder took 100.2 s over the 44 files and ours 1.85 s. `3 peaks` takes a tenth of a millisecond on both sides, so its ratio is noise. The shipped finder, with the disc on the peak, gates 1.4% to 38.7% of a file's events differently from the reference finder, 8.0% at the median. `202.fcs`, at 38.2%, is second only to `193.fcs`.

### Flow: one joined sample

`stress.py` joins every file's events into one sample and runs both finders once on it. Ours runs in the script's own process, as shipped and given the reference `find_area`. The reference finder runs in a child process stopped after `--cap` seconds, since its Delaunay triangulation of every kept event grows with the sample:

```sh
uv run python benchmarks/flow/stress.py <folder>
```

`--cap` defaults to 1800 seconds, 30 minutes, and `--out` to `tmp/flow`. It prints the event count, each run's seconds and populations, how ours given the reference `find_area` compares with the reference run, how many events the shipped finder moves, and the speedup. It appends a row to `stress.csv` in `--out` and deletes the events and masks it saved for the child. It exits with 1 if the reference run fails, or if ours given the reference `find_area` differs from it beyond the hull's edge. A run that hits `--cap` exits 0, since the cap is the measurement.

On an Apple M4 machine with 16 GB, `stress.py` joined the 44 files into one sample of 10,183,290 events. Ours took 1.44 s and the reference finder 1190.0 s, about 20 minutes, so 827x. Ours given the reference `find_area` gave the reference masks exactly, every event, and the shipped finder gated 499,311 of them, 4.9%, differently. The speedup grows with the sample because the reference gate triangulates every kept event, 4,977,743 and 4,880,276 for the two populations here, where ours triangulates the 56 vertices of their hull, and tests each of the 10,000 grid cells once where the reference gate tests every event's bin. Committed on 2026-10-12.

## Flow run records

A one-shot `datanuggets-flow` run's folder holds its tables and figures but no record of its flags. A staged run records them. `--gates-only` writes `gates.json` into the gate folder, beside `gates.npz` and the two gate figures, and `--from-gates` writes `run.json` into its run folder. Both are UTF-8 JSON from `datanuggets_flow.state`, and both begin with `schema`, `created`, the UTC time the record was written, and `versions`, the versions of Python, datanuggets-flow, datanuggets, numpy, scipy, numba, joblib, flowio, matplotlib, pandas and scikit-learn, `null` for one not installed.

`gates.json`, schema `datanuggets-flow-gates/1`, is written last, so a gate folder without it is refused as unfinished. The rest of it:

| Key | Contents |
| --- | --- |
| `settings` | The gate settings: `fsc`, `ssc`, `disc`, the `t11` and `t21` lists as given, one value for every file or one per file, `t12`, `t22`, `n_row` and `n_col` |
| `fixed` | The finder's fixed constants, as [methodology.md](methodology.md#the-finders-parameters) lists them, with the first-peak rule in words |
| `reader` | `{"library": "flowio", "preprocess": true, "compensation": "not applied"}` |
| `files` | One entry per file, in file order: its `number`, `name`, absolute `path`, `size` in bytes, `sha256`, `n_events`, `pnn` and `pns` channel names, its `t11` and `t21`, its count of `local_maxima`, and for each population its number, events, percent, scatter medians and peak cell |

`gates.npz` holds each file's masks, packed with `np.packbits` along the events, and the finder's density grid, local maxima, peaks and grid coordinates, as `masks_N`, `density_N`, `candidates_N`, `peaks_N`, `grid_fsc_N` and `grid_ssc_N` for file N. It is read with `allow_pickle=False`.

`run.json`, schema `datanuggets-flow-run/1`, holds `gates`, the gate folder's absolute path, `settings`, the clustering settings from `channels` to `cells_per_file`, `row_filters` and `groups` among them, `pops`, the populations kept in `--pops`'s grammar, and the `channels` clustered with their `labels`. `transform` is the Transform stage with the cofactors the run used. When `--cofactor auto` picked them it is `{"name": "arcsinh", "cofactor_from": "auto", "cofactors": [...], "negative_fraction": [...], "negative_sd": [...], "floor": 150.0, "min_negative_fraction": 0.01}`, the lists in `channels` order and unrounded: each channel's cofactor, the share of the clustered cells below 0 on it, and the spread of those cells, `null` for a channel with none, beside the rule's floor and guard. It has no single `cofactor`, since no one number was used. It is `{"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}` when a number was given, or `{"name": "none"}` for `--cofactor 0`. A run made while `auto` picked one number for the whole run from the files' headers recorded `{"name": "arcsinh", "cofactor": 150.0, "cofactor_from": "auto", "range": 262144.0}`, `range` being the widest marker channel range in the headers, or `null` when a header gave one of those channels no usable range and the run fell back to 6000. `state.run_transform` reads that record as written. `standardize` is the Scale stage: `{"mean": [...], "sd": [...], "ddof": 0, "cells": N, "skew": [...]}`, each channel's pooled mean, SD and skewness in `channels` order over the `N` cells clustered, or `false` when the run had `--no-standardize`. `settings` keeps `cofactor` as asked, `"auto"` or a number, and gains `standardize`. A `run.json` written before these keys existed still loads. That run was not scaled. In one written before `cofactor_from` existed, the cofactor was given or left at 6000, and `state.run_transform` reads it as set.

`settings` holds `center_method`, `seed`, `draws`, `k`, `method`, `num_init` and `max_iter` among the rest. `clustering` records how the run clustered:

| Key | Contents |
| --- | --- |
| `method` | `"wkmeans"` or `"tree"` |
| `k` | the clusters asked for, `--k` |
| `k_used` | the clusters made: `k` for weighted k-means less any cluster that emptied during its rounds, or the tree's `k` lowered to the nuggets in use |
| `nuggets_clustered` | the pooled nuggets of weight above 0 |
| `nuggets_dropped` | the pooled nuggets of weight 0, which no event joined and which have no cluster |
| `total_wwcss` | the total weighted within-cluster sum of squares of the clusters, on the clustering's scale |
| `r` | the R calls that rebuild the nuggets and clusters, `{"create.DN": ..., "cluster": ...}`, described in [Rerunning a flow run in R](#rerunning-a-flow-run-in-r) |

A `run.json` written before `method` existed clustered with the tree on mean centers, and one written before `draws` existed built its nuggets on NumPy's draws, so `ClusterSettings.from_dict` reads a record without `method` as `"tree"` with `center_method` `"mean"`, unless it names one, and a record without `draws` as `"numpy"`, whatever its method. Neither has a `clustering` block. An old record never takes today's defaults.

To repeat a staged run, run `--from-gates` on the same gate folder with the `pops` and settings `run.json` records, into a new folder:

```sh
datanuggets-flow --from-gates outputs/gates-001 --pops "1,2;none;1" --k 8 --out outputs/run-001b
```

A run whose `run.json` has no `standardize` key was made before the Scale stage and was not scaled, while the stage is now on by default, so add `--no-standardize` to repeat its tables. A run whose `settings` have no `method` was made before weighted k-means became the default, so add `--method tree --center-method mean --draws numpy` to repeat its tables. With those flags the test suite's runs give their old digests table for table.

`--cofactor auto` depends on the cells the run clusters: the same files, populations and filters give the same cofactors, in any file order, since the tally adds every file's counts into the same bins, but other populations, filters or files can give others. `transform`'s `cofactors` are the numbers the run used, one per channel. `--cofactor` takes one number for every channel, so a run whose channels all took the same cofactor, such as 150 on FlowCAP's files, is repeated on new files the same way with `--cofactor 150`. A run whose channels took several is repeated only by `auto` on the same cells. A run whose `transform` has a `range` used the one number in its `cofactor`, so pass that number, such as `--cofactor 6000`, to repeat its tables now. A run whose `transform` has no `cofactor_from`, made before `auto` existed, used its `settings`' `cofactor`, 6000 unless one was given. The default is now `auto`, so pass `--cofactor 6000` to repeat its tables.

The FCS files must still be the ones that were gated, where they were gated, as [Staged runs](cli.md#staged-runs) describes. With the package versions `versions` records, on the same machine, the run gives the first run's tables again, since `create_dn`'s only random step and weighted k-means' starts are seeded by `--seed`, and `--from-gates` names any package whose version differs. The t-SNE is seeded by `--tsne-seed`, and `_defaults.TSNE_ARGS` pins the arguments that shape `clusters_tsne.png` ([The t-SNE figure](methodology.md#the-t-sne-figure)), but a scikit-learn release that changes one of the arguments left at its default can still move the picture. The finder draws nothing, so a `--gates-only` run with the recorded `settings` on the same files finds the same masks.

### Rerunning a flow run in R

`clustering`'s `r` holds the calls, with `datanugget` 1.5.0's and `WCluster` 1.3.0's argument names in their order, that rebuild a run's nuggets and clusters in R. For a default run:

```text
"create.DN": "create.DN(x, center.method = \"original\", DN.num1 = 10000, DN.num2 = 1000, seed = 291102)"
"cluster":   "Wkmeans(centers, k = 8, obs.weights = weights, num.init = 10, max.iterations = 100, seed = 291102)"
```

With `--method tree`, `cluster` is `cutree(Whclust(centers, w = weights), k = K)`, `K` the `k_used`. `create.DN` is `null` with `--draws numpy`, since R can't draw NumPy's numbers, so such a run's nuggets can't be rebuilt in R. In `create.DN`, `x` is one clustered file's kept events after the Transform and Scale stages: the rows of `events_N.csv`'s `event0`, in that order, on the `channels`, as `arcsinh(x / c)` with `transform`'s cofactors and then `(x - mean) / sd` with `standardize`'s. One call is made per file. `DN.num2` is the setting even for a file with fewer events, since `create.DN` given more than a file's rows keeps every row as a nugget, as the run does. In `cluster`, `centers` and `weights` are every file's nugget centers and weights, file by file, with the nuggets of weight 0 left out:

```r
library(datanugget)  # 1.5.0
library(WCluster)    # 1.3.0
# xs: a list of the clustered files' kept events after Transform and Scale, in file order
nug <- do.call(rbind, lapply(xs, function(x)
  create.DN(x, center.method = "original", DN.num1 = 10000, DN.num2 = 1000, seed = 291102,
            no.cores = 1, make.pbs = FALSE)$"Data Nuggets"))
nug <- nug[nug$Weight > 0, ]
centers <- nug[, grep("^Center", names(nug))]
weights <- nug$Weight
km <- Wkmeans(centers, k = 8, obs.weights = weights, num.init = 10, max.iterations = 100,
              seed = 291102)
```

The calls above add `no.cores = 1` and `make.pbs = FALSE`, which the record leaves at R's defaults, since that is how they were checked. `km$"Cluster Assignments"` is then the run's `cluster` column of the nuggets in use, in `nuggets_N.csv` order, while no cluster empties. A cluster that empties leaves a gap in R's labels, which the run closes up. The tree's `cutree` numbers are the run's as they are. On the two halves of the public `202_fluor.npz` fixture, transformed as `arcsinh(x / 150)` and scaled, with `DN.num1 = 2000` and `DN.num2 = 200`, R 4.6.1 gave the port's 400 centers and its labels exactly, with the same total WWCSS. No test compares a whole flow run with R. This check was run in R outside the suite, as were four runs of the command, matched bit for bit: one file, three files, the automatic cofactor and the Scale stage.
