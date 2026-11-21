# Command-line analysis

## FCS pipeline

`datanuggets-flow` gates FCS files, lets you choose candidate populations, and clusters their events. It creates nuggets for each file, then clusters the pooled nuggets once, with weighted k-means by default or the hierarchical tree with `--method tree`. Cluster numbers therefore refer to the same fitted clustering across files; they are not independently validated cell-type labels. [methodology.md](methodology.md#the-datanuggets-flow-pipeline) explains the method and its design choices.

A run does everything at once, or in two stages: `--gates-only` gates the files and saves the gates, and `--from-gates` chooses populations from them and clusters, as [Staged runs](#staged-runs) describes.

`python -m pip install "datanuggets-flow==0.1.0a6"` installs the command with flowio, matplotlib, pandas and scikit-learn. In a clone, `uv sync` installs them and `uv run datanuggets-flow` runs it. The [quickstart](quickstart.md#a-first-datanuggets-flow-run) walks through a first run.

> **Experimental workflow.** Each run creates a fresh folder under `outputs/` by default. Existing output paths are refused, and unfinished runs retain an `INCOMPLETE.txt` marker. Choose at least two distinct fluorescence channels and enough retained cells to make at least three occupied nuggets.

Inspect the gates and confirm your compensation and preprocessing before interpreting results. The command does not apply compensation. With many input files and `--method tree`, also check the total nugget count: 10,000 pooled nuggets require about 800 MB for the hierarchy's matrix alone. Weighted k-means, the default, builds no such matrix.

### Synopsis

```text
datanuggets-flow PATH [PATH ...] [options]                one run: gate, choose, cluster
datanuggets-flow PATH [PATH ...] --gates-only [options]   gate and save the gates, then stop
datanuggets-flow --from-gates GATES [options]             choose from GATES' figures, then cluster
```

```text
usage: datanuggets-flow [-h] [--gates-only | --from-gates GATES] [--pops POPS]
                        [--out OUT] [--k K] [--method {wkmeans,tree}]
                        [--center-method {mean,random,original}]
                        [--num-init N] [--max-iter N] [--draws {r,numpy}]
                        [--cofactor COFACTOR] [--no-standardize]
                        [--dn-num1 DN_NUM1] [--dn-num2 DN_NUM2] [--seed SEED]
                        [--jobs JOBS] [--channels CHANNELS |
                        --exclude-channels EXCLUDE_CHANNELS] [--fsc FSC]
                        [--ssc SSC] [--disc {reference,peak}] [--t11 T11]
                        [--t21 T21] [--t12 T12] [--t22 T22] [--n-row N_ROW]
                        [--n-col N_COL] [--no-tsne]
                        [--tsne-perplexity TSNE_PERPLEXITY]
                        [--tsne-seed TSNE_SEED] [--filter SPEC]
                        [--groups GROUPS] [--cells-per-file CELLS_PER_FILE]
                        [--no-show]
                        [paths ...]
```

### Inputs

Each path is an FCS file or a folder of them. A folder gives its files whose suffix is `.fcs` in any case, so `.FCS` counts too, sorted by name. Names that start with a dot are skipped, such as the `._` copies macOS writes on some drives. Subfolders aren't searched. A file named directly is read whatever its suffix.

Files and folders can be mixed. The files are numbered from 1 in the order of the arguments, with each folder's files in name order. Name order is string order, so `10.fcs` comes before `9.fcs`. That number is what per-file thresholds, `--pops` entries and the `N` in `nuggets_N.csv` and `events_N.csv` follow. The run prints `File N, name` for every file, and `selection.csv` records the numbering.

flowio reads each file's events with `as_array(preprocess=True)`, as the file stores them. Channels are found by their `$PnN` names. The gate takes two channels, `--fsc` across and `--ssc` up. One left out is the first file's forward scatter for `--fsc`, side scatter for `--ssc`: its first forward (or side) scatter channel that ends in `-A`, else its first scatter channel, such as a Navios's `FS INT`, else the first of its default clustering channels, as on a mass cytometer, which records no scatter. The two are never one channel, and every file must have both. The channels to cluster are taken from the first file, and every file must have them too.

A `--from-gates` run takes no paths. It reads the files its gate folder records, at the paths they were gated from.

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--gates-only` | off | Gate the files, draw `local_maxima.png` and `gates.png`, save the gates in `--out` and stop, without asking |
| `--from-gates GATES` | none | Choose populations over the figures of `GATES`, a `--gates-only` folder, and cluster its files, which must not have changed |
| `--out OUT` | `outputs/flow-<timestamp>`, or `outputs/flow-gates-<timestamp>` with `--gates-only` | New output folder, relative to the current directory. Existing paths are refused, including empty folders |
| `--fsc FSC` | the first file's forward scatter | The channel the gate takes across, described above |
| `--ssc SSC` | the first file's side scatter | The channel the gate takes up |
| `--disc {reference,peak}` | `reference` | The area rule the gates use, described below |
| `--t11 T11` | `22` | The first peak's distance threshold, one value or one per file |
| `--t21 T21` | `0.25` | The first peak's density threshold, one value or one per file |
| `--t12 T12` | `20` | Every other peak's distance threshold, in every file |
| `--t22 T22` | `0.5` | Every other peak's density threshold, in every file |
| `--n-row N_ROW`, `--n-col N_COL` | `11`, `11` | Rows and columns of the window the finder's local maxima are found in, 1 to 100 each |
| `--pops POPS` | ask at the prompt | Populations to keep, in the prompt's grammar: one entry for every file, or one per file separated by `;` |
| `--channels CHANNELS` | every `-A` channel but scatter | Comma-separated `$PnN` names. Give at least two distinct channels; clustering and PCA need two. The default takes names in the first file ending in `-A` that aren't scatter, or, when it has fewer than two, every name but scatter and Time. A default channel holding NaN or an infinite value among the kept cells is left out with a warning, and one named here is refused. See [Files from other instruments](#files-from-other-instruments) |
| `--exclude-channels EXCLUDE_CHANNELS` | none | Comma-separated `$PnN` names to leave out of the default channels, such as a viability dye. Each must be a channel of the first file. Can't be combined with `--channels` |
| `--cofactor COFACTOR` | `auto` | The Transform stage: fluorescence is clustered as `arcsinh(x / cofactor)`, or as stored with `0`. `auto` picks one per channel from the spread of its cells below 0, at least 150; see [Transform and Scale](#transform-and-scale). A number applies to every channel, and `0` keeps the channels linear. A negative, NaN or infinite value is refused |
| `--no-standardize` | off | Skip the Scale stage, which by default scales every clustered channel to mean 0 and SD 1 over all clustered files' kept events. See [Transform and Scale](#transform-and-scale) |
| `--dn-num1 DN_NUM1` | `10000` | `create_dn`'s `dn_num1`, the nuggets its first pass makes from a file's kept events, 3 or more |
| `--dn-num2 DN_NUM2` | `1000` | Nuggets per file, 2 to `--dn-num1` − 1, so 9999 by default. Lowered to a file's kept events when there are fewer. Clustering requires at least 3 occupied nuggets across all retained files |
| `--center-method {mean,random,original}` | `original` | Each nugget's center, `create.DN`'s `center.method`: `original`, the event the nugget was built around; `mean`, the mean of its events, which is `create.DN`'s own default; `random`, one of its events. These centers are what the clustering, `nuggets_N.csv` and the t-SNE use |
| `--seed SEED` | `291102` | The seed of `create_dn` and of weighted k-means, a whole number from 0 to 2147483647, the largest R's `set.seed` takes. Weighted k-means always draws R's `set.seed(SEED)` numbers, and `create_dn` does with `--draws r` |
| `--draws {r,numpy}` | `r` | How `create_dn` draws from `--seed`: `r`, R's `set.seed` draws, so each file's nuggets are the ones `create.DN` makes; `numpy`, NumPy's draws, which every run made before this flag used. It doesn't change weighted k-means, which draws R's either way |
| `--jobs JOBS` | `-1` | Cores `create_dn` uses, `-1` for every one. The nuggets are the same for any value |
| `--k K` | `8` | Clusters, 1 or more. Weighted k-means is asked for exactly `K` and needs two nuggets in use per cluster, `2K` in all, or the run stops; a cluster that empties during its rounds leaves fewer. The tree is cut into `K`, lowered to the number of nuggets in use when there are fewer |
| `--method {wkmeans,tree}` | `wkmeans` | `wkmeans`: `WCluster`'s weighted k-means of the pooled nuggets, as `Wkmeans` clusters them. `tree`: the hierarchical tree, `Whclust` of the pooled nuggets cut into `--k` clusters. See [methodology.md](methodology.md#design-choices-in-the-pipeline) |
| `--num-init N` | `10` | Weighted k-means' random starts, a whole number from 1; the start with the least total WWCSS is kept |
| `--max-iter N` | `100` | Weighted k-means' rounds per start at most, a whole number from 1 |
| `--no-tsne` | off | Leave out the t-SNE and `clusters_tsne.png`, so scikit-learn isn't needed |
| `--tsne-perplexity TSNE_PERPLEXITY` | `30` | The t-SNE's perplexity, a positive number, lowered to (nuggets − 1) / 3 when that's smaller |
| `--tsne-seed TSNE_SEED` | `0` | The t-SNE's seed, a whole number from 0 |
| `--filter SPEC` | none | Keep only the kept events that pass a test on a channel's raw value, such as `"FJComp-BV510-A > 10000"`; repeat it to require several. See [Filters and groups](#filters-and-groups) |
| `--groups GROUPS` | none | One group name per file, in file order, separated by `;`, such as `"ctrl;ctrl;treated"`. Adds the group tables |
| `--cells-per-file CELLS_PER_FILE` | `2000` | Kept events per file sampled into `cells.csv`, a whole number from 0; `0` writes no `cells.csv` |
| `--no-show` | off | Save the figures without opening them, on matplotlib's Agg backend |

A flag left out takes the default above, which `--help` prints too. `--fsc` to `--n-col` set the gate stage, so `--from-gates` refuses them. `--pops` to `--cells-per-file` set the clustering stage, so `--gates-only` refuses them. `--tsne-perplexity` and `--tsne-seed` are refused with `--no-tsne`, which would ignore them, and `--num-init` and `--max-iter` are refused with `--method tree`, for the same reason.

On the files of the Zenodo record the default channels are the 32 unmixed `FJComp-...-A` channels. `SSC-B-A` is side scatter, so it's left out. A channel name with a space needs quotes, as in `--channels "FJComp-BV510-A,FJComp-Spark Blue-A"`.

#### Per-file thresholds

`--t11` and `--t21` take one number for every file, or a comma-separated list with one number per file in file order. Any other count stops the run. The peaks after the first use `--t12` and `--t22`, the reference finder's 20 and 0.5 by default, in every file, and `--n-row` and `--n-col` set the window of its local maxima. The finder's 100 by 100 grid and its other cutoffs are fixed and have no flag; [methodology.md](methodology.md#the-finders-parameters) lists them.

Cabrera's `cfc.py` sets the first peak's thresholds file by file. For a folder of four files:

```sh
datanuggets-flow path/to/fcs_folder --t11 22,20,18,18 --t21 0.25,0.5,0.5,0.5 --out outputs/threshold-run
```

`cfc.py` pairs these values with the samples in the order FlowKit returns them, by their `$FIL` keyword, which may not be the order of the workbook it reads ([methodology.md](methodology.md#against-cabreras-script)). Here they follow file order, so check the `File N` lines against the values you meant.

#### --disc

- `reference`, the default, gates with `datanuggets_flow.mirrored_area`, a copy of `cfc.py`'s own `find_area`, whose distance disc sits on the mirrored cell. The populations and their numbers are the ones `cfc.py`'s figures show.
- `peak` gates with `datanuggets_flow.find_area`, which centres the disc on the peak, as `lymphmacro_finder` does.

`reference` was called `his` before. `--disc his` still works and gives `reference`, and gate folders and the app's gate records that say `his` still load.

On `202.fcs`, `reference` gives populations of 225,770, 58,245 and 27,590 events and `peak` gives 214,085, 66,149 and 37,742. Which rule is right is still one of the [open problems](limitations.md#open-problems). [methodology.md](methodology.md#the-disc---disc-reference-and---disc-peak) explains the difference.

### Choosing populations

#### At the prompt

Without `--pops`, the run gates every file, prints each file's populations and asks. Each population line gives its event count, its share of the file's events, and its median on the two channels it was gated on, FSC-A and SSC-A on the demo files. `local_maxima.png` draws each file in its own panel: the density grid, every local maximum, and each kept peak labelled with its Pop number, so you choose from the peaks. `gates.png`, the populations' full gates, is drawn only after the choice. A `--from-gates` run asks with both figures already drawn by `--gates-only`, and shows both while it waits. From a run on three files of the Zenodo record, after the first answer:

```text
Which populations hold the cells you want? Each file's Pop numbers label the peaks in its own panel of the local maxima figure, and the same number can be a different peak in another file. Type numbers like 1 or 1,2 or 1-3, "all", or "none" to leave the file out; Enter repeats the previous file's choice, Ctrl+C stops. Click this terminal before typing.

File 2, 202.fcs:
  Pop 1:   225,770 events (80.0%), median FSC-A 1,015,754, SSC-A   569,799
  Pop 2:    58,245 events (20.6%), median FSC-A 1,171,461, SSC-A   626,855
  Pop 3:    27,590 events ( 9.8%), median FSC-A 1,404,158, SSC-A 1,355,836
Keep which, Pop 1 to 3 [1,2]:
```

The brackets hold the previous file's answer. Each answer is one of:

| Answer | Keeps |
| --- | --- |
| `1` | Pop 1 |
| `1,2` or `1 2` | Pop 1 and Pop 2 |
| `1-3` | Pop 1 to Pop 3. `3-1` means the same |
| `1-2,5` | Pop 1, Pop 2 and Pop 5 |
| `all` | every population of the file |
| `none` | nothing, so the file is left out |
| Enter | the previous file's answer |

Case doesn't matter, and a number given twice counts once. An answer that names a population the file doesn't have, or that isn't numbers, ranges, `all` or `none`, prints the reason and asks again. So does Enter at the first file, which has no previous answer. A file in which the finder found no population is left out without a question. Ctrl+C or the end of input stops the run with `cancelled; nothing was clustered`.

After the last answer the run prints the `--pops` that gives the same choice without the prompt, such as `To repeat this choice: --pops "1,2;none;1"`, for a later run or a script.

The prompt needs a terminal. When standard input is not one, such as a pipe, the run stops after gating with `no terminal to ask in; pass --pops, e.g. --pops "1,2"`. On Windows, input redirected from `NUL` counts as a terminal, so the run reaches the first question and stops with `cancelled; nothing was clustered` instead. Git Bash in its default mintty window gives a Windows Python no terminal either, so the run stops there too; use Windows Terminal, PowerShell or `winpty`, or pass `--pops`.

Without `--no-show`, the gate figure opens before the first question and stays responsive while the prompt waits, so it can be zoomed and panned. Click the terminal before typing. On Windows the wait ends at the first key press.

#### With --pops

`--pops` takes the same answers, for scripted runs. One entry applies to every file, and one entry per file, separated by `;`, applies file by file. Quote it, since `;` ends a command in the shell, PowerShell included:

```sh
datanuggets-flow a.fcs b.fcs --pops "1,2;1" --out outputs/selection-run
```

Enter has no meaning here. A file in which the finder found no population takes `all` or `none`. An entry that doesn't parse or names a missing population stops the run, as the failure table below shows. `--pops ""` counts as no `--pops` in every mode: a one-shot or `--from-gates` run asks, and `--gates-only` doesn't refuse it.

An event in two kept populations counts once: the kept events are the union of the chosen populations.

### Row filters

`--filter` keeps only the rows that pass a test on one column of the CSV. The column can be any header column, including one you don't analyze, such as a label. Filters read the raw text of the file, before any transformation. Repeat `--filter` to require every filter at once.

Write a filter as `COLUMN OP VALUE`, with a space on each side of the operator, and quote the whole filter:

| Operator | Value | Keeps rows whose cell is |
| --- | --- | --- |
| `<` `<=` `>` `>=` | a number | less than, at most, greater than, or at least the number |
| `==` `!=` | a number or text | equal to, or different from, the value |
| `between` | `lo,hi` with lo <= hi | from lo to hi, both ends included |
| `in` | one or more values separated by commas | equal to any of them |

A value that reads as a finite number is compared as a number; any other value is compared as exact text, and only `==`, `!=` and `in` take text. Text can't contain `,`, `[` or `]`. Put a column name in square brackets when it contains spaces or an operator word: `--filter "[Cell size] between 10,50"`. Under a number filter, every cell of that column must be a finite number; a blank or text cell stops the run, naming the column and the 0-based data row.

### Filters and groups

`--filter` narrows the kept events further, on the raw value of any `$PnN` channel of the files, clustered or not, before the arcsinh. It takes the grammar of the CSV command's [row filters](#row-filters): `CHANNEL OP VALUE` with a space on each side of the operator. A channel name with a space goes in square brackets, as in `--filter "[FJComp-Spark Blue-A] <= 40000"`. Repeat `--filter` to require every filter at once. An event is clustered when it is in a chosen population and passes every filter. A file whose events pass in fewer than 2 is left out, as a file keeping fewer than 2 is without filters. With filters, `selection.csv` gains `filtered`, the kept events that pass, and `filtered_percent`, their share of the file's events.

`--groups` names a group for every file, in file order, separated by `;` like per-file `--pops`, and quoted the same way. A name takes 1 to 40 letters, digits, spaces and `_ . + -`, starting with a letter or digit; the spaces around each name are dropped. The run then writes `groups.csv`, `group_summary.csv` and `group_markers.csv`, which compare each group with the reference group, the group of the lowest-numbered clustered file. The comparison is descriptive and tests no difference; [Comparing groups of files](methodology.md#comparing-groups-of-files) gives its rules. `--from-gates` counts the names against its gate folder's files.

```sh
datanuggets-flow a.fcs b.fcs c.fcs d.fcs --pops 1 --groups "ctrl;ctrl;treated;treated" --out outputs/groups-001
datanuggets-flow a.fcs --pops 1 --filter "FJComp-BV510-A > 10000" --filter "[FJComp-Spark Blue-A] <= 40000" --out outputs/filtered-001
```

#### Keeping live white cells

The app's live-cells step keeps the cells below a threshold on a viability dye, which dead cells take up, and above one on CD45, which white cells carry, and leaves the dye out of the clustering. The user places both thresholds on histograms of the kept cells; nothing suggests a value. The step hands the clustering two filters and an exclusion, so the same run on the command line is:

```sh
datanuggets-flow --from-gates outputs/gates-001 --pops "1,2" --filter "[FJComp-LIVE DEAD Blue-A] < VIABILITY_MAX" --filter "FJComp-PerCP-A > CD45_MIN" --exclude-channels "FJComp-LIVE DEAD Blue-A" --out outputs/live-001
```

with `VIABILITY_MAX` and `CD45_MIN` replaced by the raw values read off the histograms, such as the app shows next to its lines. The channels here are the PBMC demo files' (Zenodo 22079206): their dye is `FJComp-LIVE DEAD Blue-A`, and CD45 is `FJComp-PerCP-A`, whose `$PnS` is `CD45`, not `FJComp-BUV395-A`, whose `$PnS` is `CD45RA`. Other panels name them otherwise, such as `Zombie NIR-A` and `BV570-A` on the files of Zenodo 18367404. `<` keeps the cells below a value and `>` the cells above it. The filters test raw values, while the app draws each channel's histogram on an `arcsinh(x / c)` scale with raw values on the tick labels, `c` the cofactor `auto` picks for that channel from the kept cells before any filter, so with a positive `c` a line at position `t` is the raw value `c * sinh(t)`. With `--cofactor 0` the scale is linear and a line at `t` is the raw value `t` itself. `--exclude-channels` leaves the dye out of the default channels; with `--channels`, leave it out of the list instead, since the two flags can't be combined. `selection.csv`'s `filtered` then holds each file's live white cells, the counts the app shows before the run. In Python, `datanuggets_flow.livecells` gives the step's histograms and counts ([api.md](api.md#live-cells)).

The step can filter on more marker channels than those two: each channel added in the app gives one more `--filter` with its own side. Keeping the live white cells that are also CD3-positive on the PBMC demo files adds `FJComp-BV510-A`, whose `$PnS` is `CD3`:

```sh
datanuggets-flow --from-gates outputs/gates-001 --pops "1,2" --filter "[FJComp-LIVE DEAD Blue-A] < VIABILITY_MAX" --filter "FJComp-PerCP-A > CD45_MIN" --filter "FJComp-BV510-A > CD3_MIN" --exclude-channels "FJComp-LIVE DEAD Blue-A" --out outputs/live-cd3-001
```

The step offers every channel but the time channel, forward and side scatter included. `--filter` itself takes any channel. A trial server takes up to 8 channels in one live-cells set; the command line has no such cap.

### Transform and Scale

After the populations and filters choose the events, two stages prepare the clustered channels before any nugget is made, and the run prints a line for each. On two public FlowCAP files with `--pops 1`:

```text
Transform: arcsinh(x / c) of every clustered channel, c per channel (auto: the SD of the cells below 0 where at least 1% of the kept cells are below 0, at least 150; else 150)
  IFNa (FITC-A): 150  (5.9% below 0, SD 16)
  CD123 (PE-A): 150  (3.5% below 0, SD 24)
  MHC II (PerCP-Cy5-5-A): 150  (20.6% below 0, SD 18)
  ...
  TNF-a (Alex 700-A): 150  (10.3% below 0, SD 12)
Scale: every channel to mean 0 and SD 1, pooled over 2 files' 78,796 cells
  IFNa (FITC-A): mean 0.3184, SD 0.2083, skew 0.349
  CD123 (PE-A): mean 0.8015, SD 0.425, skew -0.0791
  MHC II (PerCP-Cy5-5-A): mean 0.6936, SD 1.082, skew 1.31
  ...
  CD11c (APC-A): mean 0.1419, SD 0.3546, skew 5.61
  ...
  Warning: 1 of 8 channels has skewness beyond 5 either way after the transform.
  Their mean and SD follow the long tail, so most cells take a narrow band of each scaled axis; a smaller cofactor compresses the tail.
```

- **Transform** takes each channel to `arcsinh(x / c)`, `c` its cofactor. With `--cofactor auto`, the default, the run picks a `c` for each clustered channel, once and before any arcsinh, from the raw values of the cells it clusters: each kept file's cells in the chosen populations that pass every `--filter`. A channel with 1% or more of those cells below 0 takes their spread, the median of `|x|` over them divided by 0.6745, but no less than 150; any other channel takes 150. The first line gives the rule, then a line per channel gives its cofactor, the share of its cells below 0 and, where the rule used it, their spread, `SD`. The share is rounded, so a channel printed with `1.0% below 0` and no `SD` is just under 1%. On FACSAria-type files such as FlowCAP's the negatives spread to a few tens, and every channel takes 150, as above. On two of the Aurora demo files, 190.fcs and 193.fcs with Pops 1 and 2, seven of the 32 channels rise, from CCR4's 183 to CD8's 420, and the rest stay at 150; [methodology.md](methodology.md#transform-and-scale) gives the reasons and the whole files' numbers. A number applies to every channel, and the line then reads `Transform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set`. `--cofactor 0` leaves the channels linear, and the line reads `Transform: none; the channels are clustered as stored`. `run.json` records the cofactors used either way ([Flow run records](reproducibility.md#flow-run-records)).
- **Scale** then subtracts each channel's mean and divides by its standard deviation, so every channel has mean 0 and SD 1. The mean and SD are pooled: computed once over the kept events of every clustered file together, after the populations and `--filter`, with `ddof=0`. A file left out of the clustering, with fewer than 2 kept events, doesn't count. A channel whose SD is 0 is divided by 1. The run reads each file once for the statistics and once more for its nuggets, so still only one file's events are in memory at a time. `--no-standardize` skips the stage; the line then reads `Scale: none; the channels keep the transform's units`, and the run writes the tables an earlier version wrote.
- **Skew** on each channel's line is its pooled skewness after the Transform stage, the third central moment over the SD cubed. Far from 0 it means a long tail: a few cells far out set the SD, so the other cells share a narrow band of the scaled axis and their clusters sit close together. Past 5 either way the run prints the warning above; it goes on either way. The cofactor sets the tail. On the two files above, `--cofactor 6000` puts all 8 channels past 5, from 5.7 (MHC II) to 84.9 (CD123), `--cofactor 1000` 6 of them, `--cofactor 500` one (CD11c, 8.61), and the default, 150 on every channel, one (CD11c, 5.61), with every other channel between -0.64 and 1.62. These files' values are small next to 6000, so 6000 leaves them nearly linear. On two of the Aurora demo files, 190.fcs and 193.fcs with Pops 1 and 2, `--cofactor 6000` puts 2 of 32 channels past 5 (IgM 5.84, CD25 5.62), and the default's cofactors per channel none, the largest IgD's 2.68.

Without the Scale stage, a channel with a wide spread dominates the distances `create_dn` and the clustering use. In the run above MHC II's SD is 5.2 times IFNa's, so unscaled it would count about 27 times as much in a squared distance; at `--cofactor 6000` it is 13 times, about 170 times as much. [methodology.md](methodology.md#transform-and-scale) gives the reasons for each choice.

The scaled values are what `create_dn`, the clustering (`wkmeans` or `whclust`), the PCA, both t-SNEs and the placement of `cells.csv` work on. The PCA and t-SNE coordinates are as computed on them. Every table of channel values is in the Transform stage's units, the scaling undone: `nuggets_N.csv`'s centers, `cluster_centers.csv`, `cluster_markers.csv`, `group_markers.csv`, `cells.csv`'s channel columns and `pca_center.csv`'s `center`. `nuggets_N.csv`'s `scale`, `create_dn`'s own measure of each nugget's spread, stays in the scaled units. `pca_center.csv` gains a `scale` column, each channel's pooled SD. A `--from-gates` run's `run.json` records both stages ([Flow run records](reproducibility.md#flow-run-records)).

### What a run does

1. Checks the flags against the run's mode, then every setting's value, an explicit `--channels` list and the `--groups` names included, then that matplotlib, pandas and, unless `--no-tsne`, scikit-learn import. Finds the files, reads the thresholds, and checks the number of `--pops` entries and of `--groups` names. Creates a new output folder and an `INCOMPLETE.txt` marker; an existing output path stops the run without changing its contents.
2. Gates each file: reads its events, runs the finder on `--fsc` and `--ssc` with the file's `--t11` and `--t21` and the `--disc` rule, prints the population lines and the number of local maxima and kept peaks, and draws the file's panel of `local_maxima.png`.
3. Checks the clustering channels, requiring at least two distinct channels present in every file, then chooses each file's populations at the prompt or from `--pops`, and draws `gates.png`.
4. For each file, keeps the events in any chosen population. A file with fewer than 2 kept events is left out of the clustering but stays in `selection.csv`. The file is read again, so only one file's events are in memory at a time, and the kept events' clustered channels are transformed as `arcsinh(x / c)` with each channel's cofactor, or left as they are with `--cofactor 0`. With `--cofactor auto` the cofactors are picked before the nuggets: the run reads every kept file once more, counts each channel's raw values below 0 in the cells it will cluster, after `--filter`, and picks each channel's cofactor from those counts. A file left out of the clustering counts for nothing. A number given with `--cofactor` skips that pass. Writes `selection.csv`. With `--filter`, only the kept events that pass every filter are clustered, and `selection.csv` is written after step 5 so it can count them. Unless `--no-standardize`, the Scale stage then reads every clustered file's kept events once and pools each channel's mean and SD.
5. Makes data nuggets of each file's kept events separately, scaled to mean 0 and SD 1 by those pooled values unless `--no-standardize`, with `create_dn`, `dn_num2` set to `--dn-num2` or to the number of kept events if that is smaller, `center_method`, `dn_num1` and `n_jobs` from `--center-method`, `--dn-num1` and `--jobs`, `seed` set to `RDraws(--seed)`, R's `set.seed` draws, or with `--draws numpy` to the number `--seed` itself, and every other argument at its default. When a file has no more kept events than `--dn-num2`, `create_dn` warns `DN.num is greater than or equal to the number of rows. Returning original data`, and each event becomes its own nugget.
6. Pools every file's nugget centers and weights in file order, drops nuggets with weight 0, checks that at least three occupied nuggets remain, and clusters them, each weighted by its event count. With `--method wkmeans`, the default, that is `wkmeans` at exactly `--k` clusters, with `--num-init` starts of up to `--max-iter` rounds each on R's draws from `--seed`. It stops with an error when fewer than two nuggets per cluster are in use, or when a start draws 1,000 random partitions without filling `--k` clusters, rather than clustering with fewer. The first error asks for a lower `--k` or a larger `--dn-num2`, and the second for a lower `--k` or `--method tree`. With `--method tree`, it builds the hierarchical tree with `whclust` and cuts it at `--k` clusters with `cut_tree`.
7. Writes the outputs below, the tables before the figures, and prints each file's share of kept cells in each cluster. Removes `INCOMPLETE.txt` when all tables and figures are saved. Without `--no-show`, it then opens the figures and returns when they are closed.

`create_dn` and weighted k-means run with `--seed`, 291102 by default, and the t-SNE with `--tsne-seed`, 0 by default. `--jobs` doesn't change the nuggets. Two runs on the same three files with the same flags, on one machine, wrote identical CSV files.

### Staged runs

Gating and the population choice can be separate runs. `--gates-only` does steps 1 and 2, draws `gates.png`, saves the gates in a gate folder and stops, without asking. `--from-gates` asks over that folder's figures and does steps 3 to 7 without gating again, as often as needed:

```sh
datanuggets-flow path/to/fcs_folder --gates-only --out outputs/gates-001
datanuggets-flow --from-gates outputs/gates-001 --out outputs/run-001
datanuggets-flow --from-gates outputs/gates-001 --pops "1,2" --k 12 --out outputs/run-002
```

For the same files, settings and populations, the two stages write the one-shot run's tables. `--gates-only` ends by naming its folder and the command that continues from it:

```text
Gates are in /path/to/outputs/gates-001
Choose populations and cluster with: datanuggets-flow --from-gates "/path/to/outputs/gates-001"
```

A gate folder holds:

| File | Contents |
| --- | --- |
| `local_maxima.png`, `gates.png` | The one-shot run's two gate figures |
| `gates.npz` | Each file's masks, one bit per event and population, and the finder's density grid, local maxima, peaks and grid positions |
| `gates.json` | The record of the gating, written last. [Flow run records](reproducibility.md#flow-run-records) lists its keys |

`--from-gates` checks everything before it asks: the gate folder and its record, each FCS file at its recorded path with the size and SHA-256 it was gated with, that `--out` doesn't exist, and the channels to cluster. It then shows both figures, or prints their paths with `--no-show`, and asks. A folder gated under other package versions isn't refused, since the masks are the gates, but the run first prints a line naming each package whose version differs, such as `note: GATES was gated with numpy 2.3.4 (now 2.4.0); its masks are used as saved`, because the packages that cluster can move the tables. The run folder is made only after the answer, so stopping at the prompt writes nothing. Both figures are copied into the run folder byte for byte, the gate folder's masks choose the events, and `run.json` records the run. The gate folder is only read.

The masks choose events by their row in the file, so they fit only the bytes they were found in. A file that moved or changed after gating is refused; gate it again with `--gates-only`. A gate folder records file paths, hashes and event counts, so keep it with the FCS data and out of Git.

Each mode refuses the flags it can't use before any file is read or folder made: FCS paths or a gate flag with `--from-gates`, whose gates are the folder's, and `--pops` or a clustering flag with `--gates-only`, which stops before them. Giving both modes gets argparse's usage message and exit status 2. After the setting checks, `--from-gates` also stops on these, before `--out` is checked:

| Message | Cause |
| --- | --- |
| `GATES isn't a folder` | `--from-gates` names no folder |
| `GATES's gate stage did not finish; run --gates-only again into a new folder` | The folder still has its `INCOMPLETE.txt` |
| `GATES isn't a gate folder: it has no gates.json` | One of the four files is missing; the message names it |
| `GATES/gates.json isn't UTF-8 JSON: <decoder error>` | A `gates.json` that isn't UTF-8 text or doesn't parse as JSON; the decoder's own error follows the colon |
| `GATES/gates.json isn't a datanuggets-flow-gates/1 record` | A record from another version or program, or JSON that isn't an object |
| `GATES/gates.json isn't a complete datanuggets-flow-gates/1 record: file 1's entry has no sha256` | A record edited outside the program that lacks something `--from-gates` reads: its settings, its files, or a key of a file's entry |
| `GATES/gates.json: foo isn't a gate setting` | A recorded setting this version doesn't have |
| `GATES/gates.npz has no masks_1` | An array the record calls for is missing: any of `masks`, `density`, `candidates`, `peaks`, `grid_fsc` and `grid_ssc` for any recorded file |
| `GATES/gates.npz's masks_1 doesn't fit file 1: its shape is (125, 3), where 2,000 events and 3 populations take (250, 3)` | A mask array whose shape, or a type other than `uint8`, doesn't fit the file's recorded events and populations: one bit per event, packed 8 to a byte, by one column per population |
| `PATH, gated as file 1, is missing` | An FCS file moved or deleted after gating |
| `PATH isn't the file that was gated: it has 1,024 bytes, where the gated file had 2,048` | An FCS file changed after gating. A file of the same size with other bytes gets `its SHA-256 differs from the gated file's` |

### Outputs

Figures and tables share one run folder: `outputs/flow-<timestamp>/` by default, or a new folder chosen with `--out`. Paths are relative to the current directory, so run from the folder that should hold `outputs/`.

| File | Contents |
| --- | --- |
| `local_maxima.png` | One panel per file, two to a row, titled `File N: name`: the finder's 100 × 100 density grid, every local maximum as an open circle and each kept peak as a cross labelled with the Pop number it seeds. Written before the prompt; populations are chosen from it. 110 dpi |
| `gates.png` | One panel per file, laid out as `local_maxima.png`: every event in gray and each population in color. Written after the populations are chosen. 110 dpi |
| `selection.csv` | One row per file: what was kept |
| `nuggets_N.csv` | One row per nugget of file N |
| `events_N.csv` | One row per kept event of file N |
| `cluster_summary.csv` | One row per clustered file and cluster |
| `cluster_centers.csv` | One row per cluster: its center |
| `cluster_colors.csv` | One row per cluster: the colour the figures draw it in |
| `cluster_markers.csv` | One row per clustered file and cluster: its cells' mean on each channel |
| `pca_scores.csv`, `pca_loadings.csv`, `pca_variance.csv`, `pca_center.csv` | The weighted PCA `clusters_pca.png` draws |
| `tsne.csv` | The t-SNE `clusters_tsne.png` draws. Left out with `--no-tsne` |
| `tsne3d.csv` | A separate 3-D t-SNE of the same nuggets, for viewers that turn them in 3D; no figure draws it. Left out with `--no-tsne` or fewer than three channels or nuggets |
| `cells.csv` | Up to `--cells-per-file` kept events of each clustered file, placed in that PCA. Left out with `--cells-per-file 0` |
| `groups.csv`, `group_summary.csv`, `group_markers.csv` | Only with `--groups`: each file's group, and each group's cluster shares and channel means against the reference group |
| `dendrogram.png` | Only with `--method tree`: the hierarchical tree of the pooled nuggets, leaves at 0, titled `Hierarchical tree of N nuggets`. Weighted k-means has no tree, so a default run draws none. 150 dpi |
| `clusters_pca.png` | The nuggets' weighted PCA scores, colored by cluster and sized by weight. 150 dpi |
| `clusters_tsne.png` | A t-SNE of the nugget centers in the transformed units, colored by cluster as in `clusters_pca.png`, with marker area proportional to the square root of each nugget's weight. [The t-SNE figure](methodology.md#the-t-sne-figure) gives the arguments scikit-learn's `TSNE` is called with. Left out with `--no-tsne`. 150 dpi |
| `cluster_centers.png` | `cluster_centers.csv` as a heat map, one column per cluster and one row per channel, in the transformed units. 150 dpi |
| `run.json` | Only in a `--from-gates` run: the record of the run. [Flow run records](reproducibility.md#flow-run-records) lists its keys |

A `--from-gates` run's `local_maxima.png` and `gates.png` are byte-for-byte copies of its gate folder's, so its folder holds the one-shot run's files plus `run.json`.

The headers from the three-file run, with the 32 channel columns between the first and the last cut:

```text
selection.csv        file_number,file,populations,events,kept,percent
nuggets_1.csv        nugget0,CD38 (FJComp-APC-Cy5.5-A),...,CD161 (FJComp-eFluor 450-A),weight,scale,cluster
events_1.csv         event0,nugget0,cluster
cluster_summary.csv  file_number,file,cluster,cells,percent
cluster_centers.csv  cluster,CD38 (FJComp-APC-Cy5.5-A),...,CD161 (FJComp-eFluor 450-A)
cluster_colors.csv   cluster,parent,color
cluster_markers.csv  file_number,file,cluster,cells,CD38 (FJComp-APC-Cy5.5-A),...,CD161 (FJComp-eFluor 450-A)
pca_scores.csv       file_number,nugget0,PC1,...,PC32
pca_loadings.csv     channel,label,PC1,...,PC32
pca_variance.csv     component,sdev,variance_ratio
pca_center.csv       channel,label,center,scale
tsne.csv             file_number,nugget0,tsne1,tsne2
tsne3d.csv           file_number,nugget0,tsne1,tsne2,tsne3
cells.csv            file_number,event0,nugget0,cluster,PC1,...,PC5,CD38 (FJComp-APC-Cy5.5-A),...,CD161 (FJComp-eFluor 450-A)
groups.csv           file_number,file,group,kept
group_summary.csv    group,cluster,samples,mean_percent,sd_percent,min_percent,max_percent,reference,diff_vs_ref,log2fc_vs_ref,log2fc_pseudocount
group_markers.csv    group,cluster,channel,label,samples,mean,reference,diff_vs_ref
```

The columns:

- `file_number` is the file's number and `file` its name. In `selection.csv`, `populations` is the kept populations, such as `1,2`, or `none`, `events` the file's event count, `kept` the kept events, and `percent` the kept share of the events.
- Channel columns are named `$PnS ($PnN)`, such as `CD3 (FJComp-BV510-A)`, or by `$PnN` alone when the channel has no `$PnS`. Their values are in the transformed units.
- In `nuggets_N.csv`, `nugget0` is the nugget's row, numbered from 0, `weight` its event count and `scale` its `create_dn` scale, in the Scale stage's units when it ran. The channel columns are the centers that were clustered, so with `--center-method original` they are the events the nuggets were built around. `cluster` is numbered from 1. With the tree the clusters are numbered in the order they first appear among the pooled nuggets. Weighted k-means keeps `Wkmeans`' own numbers, R's labels, and when a cluster empties during its rounds the numbers after it close up, so they run from 1 with no gap. A nugget with weight 0 has cluster 0.
- In `events_N.csv`, `event0` is the event's row in its FCS file, numbered from 0, so the rows of events that weren't kept are missing. `nugget0` is its nugget's row in `nuggets_N.csv` and `cluster` its nugget's cluster.
- In `cluster_summary.csv`, `cells` is the file's kept events in the cluster and `percent` their share of the file's kept events. Every cluster has a row for every clustered file, with 0 cells where it has none. The table the run prints is this file's `percent` rounded to one decimal, one column per file number.
- `cluster_centers.csv` holds each cluster's weighted mean of its nuggets' event means, with the nugget weights as weights, which is the mean of the cluster's events. With `--center-method mean` those means are the centers themselves; with `original` or `random` they aren't, so this table is not the mean of `nuggets_N.csv`'s centers.
- In `cluster_colors.csv`, `color` is a `#rrggbb` colour. Up to 8 clusters take matplotlib's default colours, as before; with more, `parent`, numbered from 1, is the cluster's colour family. With the tree it is the cluster of the same tree cut into 8 that each cluster falls in. Weighted k-means has no tree, so neighbouring cluster numbers share a family: cluster `c` of `k`, numbered from 0, falls in family `c * 8 // k`. The clusters of one parent take colours near its colour, each picked as far as it can be from the colours already given, so no two clusters share one and every colour reads on a light and a dark background. The library's [`datanuggets.colors`](https://github.com/ron2k1/datanuggets/blob/main/docs/api.md#datanuggetscolors) gives the rule.
- In `cluster_markers.csv`, `cells` is the file's events in the cluster, as in `cluster_summary.csv`, and each channel column the mean of those events in the transformed units, empty where `cells` is 0. It is computed from the file's nuggets, each nugget's mean of its events weighted by its event count, which gives the events' own mean, rounding aside, whatever `--center-method` is.
- The `pca_*.csv` tables hold the weighted PCA of the nuggets in use, scaled by the Scale stage, with each component's largest loading made positive, as `clusters_pca.png` draws it. `pca_scores.csv` has a row per nugget in use, in file order, `nugget0` its row in `nuggets_N.csv`. `pca_loadings.csv` and `pca_center.csv` have a row per channel, `channel` its `$PnN` and `label` its column name. `pca_center.csv`'s `center` is in the transformed units, and `scale`, each channel's pooled SD, is there only when the Scale stage ran. In `pca_variance.csv`, `variance_ratio` is each component's share of the variance.
- `tsne.csv` has the same rows as `pca_scores.csv`, at the points `clusters_tsne.png` draws. `tsne3d.csv` has the same rows again, from a 3-D t-SNE fitted on its own with the same arguments, perplexity and seed, so its first two columns are not `tsne.csv`'s.
- `cells.csv` samples up to `--cells-per-file` of each file's clustered events, without replacement, with a generator seeded by `--seed` and the file number, sorted by `event0`. `PC1` to `PC5`, fewer with fewer channels, are `((values - center) / scale) @ loadings` from `pca_center.csv` and `pca_loadings.csv`, or `(values - center) @ loadings` with `--no-standardize`; the channel columns are in the transformed units.
- `groups.csv` has a row per file, clustered or not: its group, and `kept`, `true` when the file was clustered.
- `group_summary.csv` has a row per group, in the order the groups first appear, and cluster. `samples` is the group's clustered files; `mean_percent`, `sd_percent` (empty under 2 samples), `min_percent` and `max_percent` summarize their `percent` in `cluster_summary.csv`, a file with no cells in the cluster counting as 0. `reference` is the reference group's `mean_percent`, `diff_vs_ref` the difference from it, and `log2fc_vs_ref` is log2((mean + pc) / (reference + pc)), with the pseudocount pc in `log2fc_pseudocount`, the same on every row: half a cell of each clustered file in percentage points, 50 / N for a file of N clustered cells, averaged over the clustered files. It keeps a cluster with no cells in one group from giving an infinite fold change. For a cluster of a few cells per file it pulls the fold change towards 0, so read it with the raw `mean_percent` and `sd_percent` of both groups. The reference group's own `diff_vs_ref` and `log2fc_vs_ref` are 0. The table describes the groups; it tests no difference between them.
- `group_markers.csv` has a row per group, cluster and channel. `samples` is the group's files with cells in the cluster, `mean` the plain mean of their `cluster_markers.csv` means, `reference` the reference group's, and `diff_vs_ref` the difference. Each is empty where there is nothing to average or compare.

A file left out of the clustering has no `nuggets_N.csv` or `events_N.csv`, so the numbers can skip.

#### Output safety

**Existing output paths are never reused.** The command refuses a file, directory, or symbolic link at the requested path, including an empty directory. This keeps a new run from deleting or overwriting earlier results. Let the default choose a fresh run folder, or give `--out` an unused name.

If a run fails or is cancelled after creating its folder, partial figures and tables stay there with `INCOMPLETE.txt`. The error also prints their location. Rerun in a new folder; the command does not resume unfinished runs. The marker is removed only after every result file has been saved.

### Spillover

Events are clustered as stored, uncompensated. When a file's `$SPILLOVER` or `$SPILL` keyword holds a matrix with any entry more than 0.001 from the identity, the run prints `warning: NAME has a compensation matrix, but its events are clustered as stored, uncompensated` and goes on. It prints each time the file is read: when it's gated, and on each pass the clustering stage makes over its events, up to four (the default channels' check for values that aren't numbers, the auto cofactor's tally, the Scale stage and the nuggets). A gate folder doesn't record the matrix, so `--from-gates` warns again when it reads the file. Spectral files are unmixed already. The four files of the Zenodo record tried here, `154`, `199`, `202` and `223`, carry no spillover keyword, so this warning hasn't been seen on real data.

### Files from other instruments

The defaults fit a cytometer that records areas (`-A`) and forward and side scatter, as the PBMC demo's Cytek Aurora does. Files from other instruments run too, with these differences.

- Scatter by name. A channel named `FS` or `SS` followed by `C`, a space, a dash, an underscore or nothing, in any case is scatter: `FSC-A`, `ssc-a`, a spectral cytometer's `SSC-B-A`, and a Beckman Navios's `FS INT` and `SS INT`. A marker named from those letters, such as `SSEA4-A`, isn't. Scatter is gated on and never clustered by default.
- A processed file's label column. A default channel holding NaN or an infinite value among the kept cells, as a label column can, is left out with a `warning:` line. A channel named with `--channels` is refused. Other bookkeeping columns, such as event numbers, hold numbers and stay in the defaults: list the markers with `--channels`.
- Heights only, or no areas. When the first file has fewer than two channels ending in `-A` other than scatter, as a FACSCalibur's FCS 2.0 file or a mass cytometer's does, the default channels are every channel but Time and scatter. Instrument parameters such as a mass cytometer's `Event_length` are among them. Leave those out with `--exclude-channels`, or list the markers with `--channels`.
- No `FSC-A` or `SSC-A`. The gate takes the first file's other scatter channels: `FSC-H` and `SSC-H` on a heights-only file, `FS INT` and `SS INT` on a Navios file. A file with no scatter, such as a mass cytometer's, is gated on its first two default channels, which are rarely the ones to gate cells on: name two with `--fsc` and `--ssc`, such as the DNA channels. The finder's cutoffs were set on scatter ([limitations](limitations.md#flow-cytometry)), so check the gates it draws.
- Empty populations under the reference rule. On public files from an Aurora and an Attune, `--disc reference` drew areas holding no events, since it mirrors each peak's area across the diagonal. The gate lines say so, and `--disc peak` centres each area on its peak.
- A few events past the detector's range. Left in, they squeeze the others into the edge of the finder's grid, where no peak is kept, as on a public CytoFLEX file. So when up to 1% of a file's events are past a gate channel's range (its `$PnR`), they are left out of the grid and of every population, and the gate lines say how many. When more are past it, the range doesn't describe the values and every event is gated. A file that still has no populations gets a line saying so, and its `--pops` entry can only be `none`, or `all`, which chooses nothing there too.
- Files not named `.fcs`. Some instruments name their FCS files otherwise, as a FACSCalibur's `.B08`. Name such a file on the command line, since a folder is searched for `*.fcs` only. The app takes any file whose header says FCS 2.0, 3.0 or 3.1, whatever its name.
- Mass cytometry counts. `--cofactor auto` never goes below 150, a floor for fluorescence. Mass cytometry is usually transformed with a cofactor of 5: pass `--cofactor 5`.
- A channel without a name. FCS 2.0 makes `$PnN` optional. A channel without one is named `P` and its number, such as `P6` for the sixth, in flags, tables and labels.

Two warnings help with mixed or unusual files. Each prints once as a `warning:` line, and the app lists them with the run's other warnings:

- `Stains differ between files: FL2-A is CD4 (a.fcs) or CD8 (b.fcs). ...` when files give a clustered channel different stains (`$PnS`). Channels are matched by `$PnN` and labelled with the first file's stain, so check that the files hold the same panel. The same stain spelled two ways also shows here.
- `FL4-A takes one value in every clustered cell, ...` for a channel with no spread among the kept cells, such as an empty detector. It adds nothing to the clusters, so leave it out with `--exclude-channels`.

Other warnings the `datanuggets` library raises during a run print the same way.

In the app, the gate form's X and Y channel lists offer every channel of the file. Each starts on the channel chosen when the file has it, or else on the one the rule above takes. The Live cells step offers every channel but Time. The app groups files into datasets by the same default channels ([datasets](app/flow-only-and-datasets.md#2-datasets)).

### Failure conditions

The checks run in the order of the steps above, so the first condition a run meets is the one it reports. These messages go to standard error and the exit status is 1:

| Message | Cause |
| --- | --- |
| `give FCS files or folders, or --from-gates GATES` | No paths and no `--from-gates` |
| `--from-gates reads the FCS files its gate folder records; give no FCS paths` | Paths given with `--from-gates` |
| `--t12 sets the gate stage, and --from-gates reuses the gates in GATES; run --gates-only again to change it` | A gate flag given with `--from-gates` |
| `--k sets the clustering stage, which --gates-only stops before` | `--pops` or a clustering flag given with `--gates-only` |
| `--tsne-seed has no effect with --no-tsne` | `--tsne-perplexity` or `--tsne-seed` given with `--no-tsne` |
| `--num-init and --max-iter set weighted k-means, not the hierarchical tree` | `--num-init` or `--max-iter` given with `--method tree` |
| `--t12 is 0.0; it takes a positive distance in grid cells` | `--t12` or a `--t11` value that is 0 or below, or NaN. `--t11` is checked once the files are counted |
| `--t22 is nan; it takes a fraction of the peak's density, 0 or more` | `--t22` or a `--t21` value below 0, or NaN |
| `--n-row is 0; it takes 1 to 100 grid cells` | `--n-row` or `--n-col` outside the 100 by 100 grid |
| `--groups has 'b/c'; a name takes 1 to 40 letters, digits, spaces and _ . + -, starting with a letter or digit` | A `--groups` name that isn't allowed. An empty one gets `--groups has an empty name` |
| `--k is K; it takes 1 or more clusters` | `--k` below 1 |
| `--num-init is 0; it takes a whole number from 1` | `--num-init` or `--max-iter` below 1 |
| `--dn-num1 is N; it takes 3 or more nuggets` | `--dn-num1` below 3 |
| `--dn-num2 is N; it takes 2 to 9999 nuggets per file` | `--dn-num2` below 2, or not below `--dn-num1`, whose value less one ends the range. `create_dn` needs it below `dn_num1` |
| `--cofactor is -1.0; it takes auto, 0 (linear) or a positive number` | A negative, NaN or infinite `--cofactor`, or a word other than `auto` |
| `--seed is -1; it takes a whole number from 0 to 2147483647, R's largest seed` | A negative `--seed`, or one above 2147483647, which R's `set.seed` refuses |
| `--tsne-seed is -1; it takes a whole number from 0` | A negative `--tsne-seed` |
| `--jobs is 0; it takes -1 (every core) or 1 or more` | `--jobs` of 0 or below -1 |
| `choose at least two distinct fluorescence channels for clustering and PCA` | `--channels` with fewer than two distinct names |
| `--channels repeats a channel; list each channel only once` | Duplicate entries in a list with at least two distinct channels |
| `--tsne-perplexity is 0.0; it takes a positive number` | A `--tsne-perplexity` of 0 or below, or NaN |
| `--filter: 'CD3-A>=1' has no operator; write COLUMN OP VALUE with one of < <= > >= == != between in between spaces` | A `--filter` that doesn't parse; the message says what is wrong |
| `--cells-per-file is -1; it takes a whole number from 0` | A negative `--cells-per-file` |
| `datanuggets-flow needs matplotlib, pandas and scikit-learn: pip install datanuggets-flow` | matplotlib isn't installed, pandas unless `--gates-only`, or scikit-learn unless `--gates-only` or `--no-tsne` |
| `PATH: no such file or folder` | A path that doesn't exist |
| `no .fcs files in PATHS` | The paths hold no FCS file, such as `tests/fixtures/flow`, whose fixtures are `.npz` arrays |
| `--t11 takes numbers like 22 or 22,20,18,18, got 'a'` | A threshold that isn't a number. `--t21` gives the same message |
| `--t11 gives 2 values for 3 files; give one, or one per file` | A threshold list of the wrong length |
| `--pops gives 2 choices for 3 files; give one for all of them or one per file, separated by ;` | A `--pops` list of the wrong length |
| `--groups gives 2 names for 3 files; give one per file, separated by ;` | A `--groups` list of the wrong length |
| `output path already exists: PATH; choose a new --out folder` | The selected output path already exists |
| `223.fcs has no channel FOO; its channels: FSC-A, FSC-H, ...; set --fsc to one` | A file without the `--fsc` or `--ssc` channel. The message names the flag |
| `t.fcs has no channel left to gate on; its channels: Time; set --fsc to one` | A first file with no channel the gate could take for a flag left out |
| `--exclude-channels names FOO, which 202.fcs doesn't have; its channels: FSC-A, FSC-H, ...` | An `--exclude-channels` name the first file doesn't have |
| `choose at least two distinct fluorescence channels for clustering and PCA` | Fewer than two default channels left in the first file |
| `223.fcs has no channel FOO; its channels: FSC-A, FSC-H, ...` | A file without one of the channels to cluster |
| `--pops: there is no Pop 9; this file has Pop 1 to Pop 7` | A `--pops` entry naming a population the file doesn't have. A file without populations says `this file has no populations; choose none for it` |
| `--pops: 'x' isn't a population number or a range like 1-3` | A `--pops` entry that doesn't parse |
| `no terminal to ask in; pass --pops, e.g. --pops "1,2"` | No `--pops`, and standard input isn't a terminal |
| `cancelled; nothing was clustered` | Ctrl+C or the end of input at the prompt |
| `--filter names CD3-A, which a.fcs doesn't have; its channels: FSC-A, FSC-H, ...` | A filter on a channel a file with kept events doesn't have |
| `no file has cells kept, so there is nothing to cluster` | Every file was left out or kept fewer than 2 events |
| `--filter keeps fewer than 2 cells in every file, so there is nothing to cluster` | The filters leave fewer than 2 events in every file |
| `223.fcs isn't the file that was gated: it has 1,000 events, where the gated file had 2,000` | A file changed between gating and the read that takes its kept events. A change of channels gets the same start |
| `the kept cells make fewer than 3 occupied nuggets, too few to cluster; keep more cells or increase --dn-num2` | Fewer than 3 nuggets with weight above 0 |
| `weighted k-means needs two nuggets in use per cluster: k = 5 needs 10, and the kept cells fill 9; lower k or increase --dn-num2` | With `--method wkmeans`, fewer than twice `--k` nuggets with weight above 0. R's `Wkmeans` would draw random starts forever there, and the run doesn't lower `--k` for you |
| `weighted k-means can't make k = 100 clusters of these 400 nuggets (none of 1,000 random partitions filled all k = 100 clusters, where R would keep drawing); lower --k or use method tree` | With `--method wkmeans`, a start drew 1,000 random partitions and none put two nuggets in every cluster and left every cluster with a nugget nearest its center. R would keep drawing. A lower `--k` or `--method tree` always helps; more nuggets help only near twice `--k`, and on a large pool of few channels they make it fail more often. See [limitations.md](limitations.md#weighted-k-means-starts) |

A bad flag value, such as `--disc mirror` or a non-integer `--k`, gets argparse's usage message and exit status 2, and so do `--channels` with `--exclude-channels` and `--gates-only` with `--from-gates`. Other errors can end in a Python traceback with exit status 1: missing flowio, an unreadable FCS file, or invalid scatter values. A failed run retains its incomplete marker and any partial outputs.

### Examples

Each output directory below must be unused. Replace `path/to/fcs_folder` and the channel names with your inputs.

```sh
datanuggets-flow path/to/fcs_folder --out outputs/run-001
datanuggets-flow path/to/fcs_folder --pops "1,2" --no-show --out outputs/run-002
datanuggets-flow a.fcs b.fcs --pops "1,2;1" --out outputs/run-003
datanuggets-flow path/to/fcs_folder --t11 22,20,18,18 --t21 0.25,0.5,0.5,0.5 --out outputs/run-004
datanuggets-flow path/to/fcs_folder --pops "1,2" --disc peak --k 12 --out outputs/run-005
datanuggets-flow a.fcs --pops 1 --channels "FJComp-BV510-A,FJComp-Spark Blue-A,FJComp-Alexa Fluor 700-A" --cofactor 0 --dn-num2 200 --k 3 --out outputs/run-006
```

The last command uses three untransformed channels from Pop 1, reduces the retained events to up to 200 nuggets in total, and groups those nuggets into three clusters.

```sh
datanuggets-flow path/to/fcs_folder --pops "1,2" --exclude-channels Viability-A --out outputs/run-007
datanuggets-flow path/to/fcs_folder --pops "1,2" --no-tsne --dn-num2 500 --jobs 2 --out outputs/run-008
datanuggets-flow path/to/fcs_folder --gates-only --t12 18 --n-row 9 --n-col 9 --out outputs/gates-002
datanuggets-flow --from-gates outputs/gates-002 --pops all --seed 7 --tsne-seed 7 --out outputs/run-009
```

The first clusters the default channels without a viability dye named `Viability-A`. The second skips the t-SNE and makes up to 500 nuggets per file on two cores. The last two gate with a smaller window and a smaller distance threshold for the later peaks, then cluster every population with other seeds.

```sh
datanuggets-flow --from-gates outputs/gates-002 --pops all --method tree --center-method mean --draws numpy --out outputs/run-010
```

This one clusters with the hierarchical tree on mean centers and NumPy's draws, the settings every run made before `--method` existed used, so on the same files, populations and other flags it writes the tables such a run wrote.
