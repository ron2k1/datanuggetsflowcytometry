# Methodology

This page describes the flow cytometry gate finder and the `datanuggets-flow` pipeline built on it. It then says how the pipeline relates to the papers and how it's checked. The data nuggets method and the weighted analyses come from the `datanuggets` library, a port of two R packages held to R's output. The library's [methodology](https://github.com/ron2k1/datanuggets/blob/main/docs/methodology.md) describes them. The flow pipeline adds steps of its own, and this page marks them as design choices where nothing in the repository validates them.

Usage is elsewhere. [quickstart.md](quickstart.md) has a first run, and [cli.md](cli.md) documents every flag of `datanuggets-flow`.

## Flow cytometry, as implemented

### The gate finder

`datanuggets_flow.lymphmacro_finder` is Prof. Cabrera's gate finder for the lymphocyte and macrophage populations, ported from its Python version, which is Cabrera's own port of the original R code. It works on two channels, FSC-A and SSC-A in his files, or any two it is given:

1. Both channels are shifted by the smaller of their two minimums, plus 3, and square rooted.
2. `f_plot` bins them into a 100 by 100 grid, each bin `floor(100 * (v - min) / (max - min)) + 1` clipped to 1 to 100, counts the events per cell, takes `log(1 + count)`, and sets cells below 0.1 times the largest to 0. Grid rows are SSC-A bins and columns are FSC-A bins.
3. `local_maxima` keeps each cell equal to the maximum of the 11 by 11 window around it, where that maximum is above the 0.85 quantile of the grid.
4. `refine_peaks` moves each candidate to the densest cell within 2 cells of it (`search_ind`), drops duplicates, keeps a peak whose row is above 10 and below 90, whose column is below 90 and whose density is above the 0.9 quantile of the grid, and sorts the peaks by row.
5. `find_area` keeps the cells closer than `t1` cells to the peak whose density is above `t2` times the peak's. The first peak takes `t11=22` and `t21=0.25`, the others `t12=20` and `t22=0.5`.
6. `hull_gate` takes the convex hull of the area's cells and keeps the events whose bin lies inside it. The population is every event inside the convex hull of those events, in FSC-A and SSC-A. It needs more than 3 cells and more than 3 kept events.

The result has one row per event and one column per population, in peak order. An event can be in more than one population, or in none. With the shipped finder on `202.fcs`, 57,797 of its 282,270 events are in more than one and 29,065 in none. The cutoffs are Prof. Cabrera's and aren't retuned here.

### Where the finder departs from Cabrera's code

1. `find_area` centres its distance disc on the peak. Cabrera's code builds the grid row by row and flattens the density column by column, so its density test reads the right cell while its disc sits on the mirrored cell `(idy, idx)`. On `202.fcs` this puts 107,909 of the 282,270 events in a different set of populations: the reference finder's three hold 225,770, 58,245 and 27,590 events, the corrected ones 214,085, 66,149 and 37,742. On a peak on the diagonal the two agree. It's the one change in output, and it waits on a ruling.
2. `hull_gate` tests each grid cell once and looks the answer up per event, and tests the events against a triangulation of their hull's vertices, where the reference code triangulates every kept event. Both cover the same polygon, so they can differ only on an event within rounding of the hull's edge.
3. With no peak left after the reference code's filters, the finder returns zero columns. The reference code raises `IndexError`.
4. An area whose cells or kept events lie on one line, or so near one that Qhull calls them flat, gives an empty population. The reference code raises `QhullError`.
5. NaN or infinite values, or a channel with one value, raise `ValueError`. The reference code bins them or divides by zero.
6. The reference finder's unused `plot=False` argument is dropped, and `plot.gates` draws the reference code's figure with one matplotlib artist per population.

### The disc: `--disc reference` and `--disc peak`

Whether the disc should sit on the peak or where Cabrera's code puts it is an open ruling, listed among the [open problems](limitations.md#open-problems). The library and the command line take different sides of it for now:

- `lymphmacro_finder` uses the corrected `find_area`, with the disc on the peak, unless it's given `area=mirrored_area`.
- `datanuggets-flow` defaults to `--disc reference` (formerly `his`, which still works), which gates with `datanuggets_flow.mirrored_area`, a copy of `cfc.py`'s `find_area`, so the populations and their numbers are the ones `cfc.py`'s figures show. `--disc peak` uses the corrected `find_area`.

The choice changes which events the clustering sees. In the comparison run on an Apple M4 machine with 16 GB over the 44 files of the record, the corrected disc gates 1.4% to 38.7% of a file's events differently from the mirrored disc, 8.0% at the median.

### The finder's parameters

The finder's tunable values are in `datanuggets_flow._defaults`, and each has a `datanuggets-flow` flag. The rest make it Cabrera's finder: they are constants named in the module that uses them, no flag changes them, and every gate folder records them in `gates.json` under `fixed`. The reference lines below are in `benchmarks/flow/cabrera_reference.py`, which holds his functions word for word, and `tests/flow/test_flow_settings.py` pins every value in both tables.

| Constants | Default | Flag | What they set | Reference |
| --- | --- | --- | --- | --- |
| `FINDER_N_ROW`, `FINDER_N_COL` | 11, 11 | `--n-row`, `--n-col` | The window `local_maxima` takes each cell's maximum over | :139, :161 |
| `FINDER_T11`, `FINDER_T21` | 22, 0.25 | `--t11`, `--t21` | The first peak's distance and density thresholds, one value or one per file | :139, :186 |
| `FINDER_T12`, `FINDER_T22` | 20, 0.5 | `--t12`, `--t22` | Every other peak's thresholds | :140, :187 |

| Constant | Module | Value | What it fixes | Reference |
| --- | --- | --- | --- | --- |
| `MSIZE` | `gate` | 100 | The grid's rows and columns | :147 |
| `GRID_SCALE` | `gate` | `"l"` | Cells hold `log(1 + count)` | :149 |
| `GRID_ALPHA` | `gate` | 0.1 | Cells below 0.1 times the largest go to 0. It's `f_plot`'s default, which the reference finder leaves implicit | :15, :60 |
| `SQRT_SHIFT` | `grid` | 3 | Added to each channel, less the smaller minimum, before the square root | :143-145 |
| `LOCAL_MAX_QUANTILE` | `peaks` | 0.85 | A local maximum must be above this quantile of the grid | :154 |
| `LOCAL_MAX_EDGES` | `peaks` | `"reflect"` | How the window extends past the grid's edges, `generic_filter`'s default | :161 |
| `SEARCH_THRESHOLD` | `peaks` | 2 | How far, in cells, `search_ind` looks for a denser cell | :73 |
| `ROW_MIN`, `ROW_MAX`, `COL_MAX` | `peaks` | 10, 90, 90 | A peak's row must be above 10 and below 90, and its column below 90 | :175 |
| `PEAK_QUANTILE` | `peaks` | 0.9 | A peak's density must be above this quantile of the grid | :179 |
| `MIN_POINTS` | `gate` | 3 | An area needs more than 3 cells, and its gate more than 3 events | :208 |
| The first-peak rule | `gate`, `peaks` | | The first peak by SSC row takes `t11` and `t21`, the others `t12` and `t22` | :186-187 |

`find_area` and `mirrored_area` default to `t1=35` and `t2=0.85`, `AREA_T1` and `AREA_T2` in `peaks`, from :102. The finder always passes its own thresholds, so those defaults are never reached and `gates.json` doesn't record them. The other `datanuggets-flow` defaults, from the scatter prefixes and the off-scale share to the t-SNE's seed, are in `_defaults` too, and [cli.md](cli.md#options) lists them with their flags.

### The `datanuggets-flow` pipeline

`datanuggets-flow` (`src/datanuggets_flow/pick.py`) reads each FCS file with flowio, as stored and uncompensated, gates it with the finder above, leaving out the few events past a gate channel's range ([cli.md](cli.md#files-from-other-instruments)), and asks which populations to keep, file by file. It makes nuggets of each file's kept events, transformed as `arcsinh(x / c)` with each channel's cofactor `c` and scaled to standard deviation 1 over all the files ([Transform and Scale](#transform-and-scale)), with `create_dn`, pools them, and clusters the pooled nuggets once into `--k` clusters, with `WCluster`'s weighted k-means by default or the hierarchical tree with `--method tree`. The command does the printing and asking, around `gate_stage` and `cluster_stage` in `datanuggets_flow.pipeline`, and [cli.md](cli.md#what-a-run-does) lists the steps in order, with every flag, the prompt's grammar, the output files and the conditions on which the command stops.

### Design choices in the pipeline

These choices come from the code. Nothing in the repository measures how they affect the clusters.

- One clustering for all files. The clusters come from a single clustering of every file's nuggets, so a cluster has one definition, and cluster 3 in one file is the same region of marker space as cluster 3 in another. That makes the per-file percentages in `cluster_summary.csv` comparable. Clustering each file on its own would give labels with no correspondence between files.
- Nuggets per file. Each nugget holds the events of one file, so its cluster maps back to that file's events and the per-file counts are sums of whole nuggets. Each `create_dn` call also stays within one file's memory. A file gets at most `--dn-num2` nuggets whatever its event count, but its nuggets carry their event counts as weights in the clustering.
- Gating first, with the populations picked per file. The finder numbers a file's populations in the order of its peaks, so the same population can get a different number in another file, and the pick is made file by file.
- Weighted k-means by default, the hierarchical tree as an option. The paper's flow example clustered its nuggets with weighted k-means (Section 4), and so does the run by default, with `wkmeans`, the port of `WCluster`'s `Wkmeans`, on R's draws from `--seed`, so its clusters are the ones `Wkmeans` gives in R on the same nuggets and seed. `Wkmeans` starts from a random partition with every cluster on at least two nuggets, redrawn until all k clusters are used, then runs rounds of 20 weighted Lloyd steps followed by single-point moves. The paper's Algorithm 3 starts instead from K nugget centers and moves single nuggets. The run follows the R package, as the rest of the port does. `--num-init` is 10 because Section 4 reports that "Ten initial centers were used". `--max-iter` is 100, the package's own choice: `Wkmeans` defaults to 10 rounds, and Algorithm 3 repeats its single-nugget step until no nugget moves, allowing a cap it gives no value for. Weighted k-means makes `--k` clusters or stops: it needs two nuggets in use per cluster, and a start that draws 1,000 random partitions without filling every cluster ends the run where R would keep drawing ([cli.md](cli.md#failure-conditions)). It never lowers `--k`, so a run doesn't quietly give fewer clusters than asked. The tree, `--method tree`, needs no random starts and can be cut at any k without rerunning. It is cut into as many clusters as there are nuggets in use when that is fewer than `--k`.
- Original centers by default. `--center-method original` gives each nugget the event it was built around, a measured cell, where `mean` gives the mean of its events, which is `create.DN` 1.5.0's own default and what the paper's flow example used. `datanugget` 1.4.0 defaulted to `"original"`, and the default follows Prof. Cabrera's group, who cluster on these points rather than the means. The clustering, `nuggets_N.csv`, the PCA and the t-SNE use the centers. The tables of marker levels, `cluster_centers.csv`, `cluster_markers.csv` and `group_markers.csv`, use each nugget's mean of its events, so a cluster's levels are its events' own mean whatever the centers are. The flow doesn't refine its nuggets. `refine_dn`, as `refine.DN` does, would make every center a mean.
- The transform and the cluster count. arcsinh is close to linear for values well below the cofactor and close to logarithmic above it, so one cofactor doesn't suit every channel. By default the run picks one per clustered channel from the cells it clusters, before any arcsinh ([Transform and Scale](#transform-and-scale)): 150, unless the channel's cells below 0 spread wider than that, and then their spread. A larger cofactor keeps more of a channel linear and more of its long right tail. On whole public FACSAria-type files with no gate (FlowRepository FR-FCM-ZZZU's 0008, 0010 and 0155), 4 of the 8 marker channels kept a skewness beyond 5 either way at 6000, up to 54, and at 150 every one was between 0.30 and 1.85. FlowCAP's files gave the same picture. On four of the Aurora demo files with no gate (190.fcs, 193.fcs, 199.fcs and 223.fcs), whose marker channels run to 3,162,277, 6000 left 1 to 5 of the 32 marker channels with a skewness beyond 5, up to 7.90, and 150 left none, every channel between -1.89 and 2.91. Skewness favours the small cofactor on both instruments, so the rule starts from 150 and raises a channel's only where its negative cells need it. Until the per-channel rule, `auto` picked one cofactor for the whole run from the files' headers, 150 or 6000. Runs recorded under it keep that number. Nothing measures how the cofactors change the clusters, and no test or recorded result in the repository supports a particular k.
- Uncompensated events. They are clustered as the file stores them, and a file with a real spillover matrix gets only a warning. The code's reason is that spectral files are unmixed already.

`create_dn` runs here with `seed=RDraws(--seed)`, R's `set.seed` draws from 291102 unless another seed is given, so each file's nuggets are the ones `create.DN` makes from the same scaled events with that seed. `--draws numpy` passes the number itself, which draws from NumPy, as every run made before `--draws` existed did. Those nuggets aren't R's. Weighted k-means draws R's numbers from `--seed` either way. The shuffle in `create_dn` and the starts of weighted k-means are the only random steps up to the clusters, so the same files and settings give the same nuggets and clusters in the same environment. `--jobs` doesn't change them: `create_dn` shuffles the rows once before it splits them into chunks, and joins the chunks' centers in chunk order however many threads reduce them.

### Transform and Scale

Between the population choice and the nuggets, the clustered channels pass two stages, in this order. Each prints a line, and `run.json` records both.

**Transform.** Each channel becomes `arcsinh(x / c)`, with `c` its cofactor, or stays linear with `--cofactor 0`. A number given with `--cofactor` is `c` for every channel. The default, `auto`, picks a `c` for each clustered channel, once and before any arcsinh, from the raw values of the cells the run clusters: the chosen populations' cells that pass the row filters, pooled over the files the clustering keeps, so a file with fewer than 2 such cells counts for nothing. For each channel it takes `f`, the share of those cells below 0, and `sd`, the spread of the cells below 0: the median of `|x|` over them divided by 0.6745, which for a Gaussian centred on 0 is its SD, measured from its lower half alone so that the cells carrying the marker can't widen it. `c` is `sd`, but at least 150, when `f` is 1% or more, and 150 otherwise. Every file gets the same `c` for a channel. Fluorescence is skewed to the right, and after compensation or unmixing the cells that don't carry a marker spread around 0, some of them below it. arcsinh keeps the values near 0 and the negatives in order, since it is close to linear there, and pulls in the long right tail, since it is close to logarithmic above the cofactor.

The rule rests on one property of arcsinh. A cloud of cells centred on 0 with SD `s` stays one hump after `arcsinh(x / c)` when `c` is at least `s`, and splits into two, one on each side of 0, when `c` is smaller: at 0 the second derivative of the logarithm of the transformed density is `1 - c²/s²`, so 0 turns from the peak into a dip exactly when `c` drops below `s`. A cofactor under the spread of the unstained cells makes one population look like two, which is OMIQ's warning about too small a cofactor, and the logicle display (Parks, Roederer and Moore, Cytometry Part A, 2006) gives its linear zone the width of the negatives' spread for the same reason. Too large a cofactor has the opposite fault: the dim positives stay in the linear zone with the negatives, and the bright tail stays long. So the rule raises `c` only as far as a channel's negatives reach, and keeps 150, the usual cofactor for conventional fluorescence, everywhere else. The published choices for spectral data agree with the reason, if not the number: cyCombine (Nature Communications, 2022) recommends 6000 for spectral cytometry, Jaimes et al. (Cytometry Part A, 2022) chose 6000 for their spectral panel so that the negatives stayed one population, and CellEngine sets its scale from the width of the negatives. The 1% guard is for a channel with almost no cells below 0: it has no negative cloud to split, and the spread of a few stray events is noise.

The median is read from a histogram of `|x|` over each channel's cells below 0: 400 log-spaced bins per decade from 0.01 to 10⁸, with one bin below and one above, summed as the files are read, so the files can come in any order and only one file's events are in memory at a time. The count is located at half the `m` cells below 0 and placed linearly in `log10 |x|` within its bin, so the value is within one bin, about 0.6%, of the sorted `|x|` at rank `m / 2`: the middle value, or the lower of the two middle values when `m` is even. The usual median averages those two, and with few cells below 0 they can be more than a bin apart: on CD8, CD19 and CD123 of 190.fcs, taken 100 cells below 0 at a time, the usual median was typically about 1% above the lower middle value and at most 6%, and from 1,000 cells under 0.25%. The tally is one more pass over the kept files, the same read the Scale stage makes. On the four FlowCAP files below it took about 40% of the time of the Scale stage's pass. A number given with `--cofactor` skips it.

On whole public files with no gate, the rule gives every marker channel of FlowCAP's FACSAria-type files 0092, 0094, 0253 and 0255 a cofactor of 150: on each channel 5.9% to 20.9% of their 1,757,041 cells are below 0, with a spread of 16 to 36. On the four Aurora demo files' 193,293 cells it raises six of the 32 marker channels: CD8 to 338 (2.10% of the cells below 0), CD14 to 350 (1.31%), ACE2 to 210 (1.91%), CD19 to 204 (10.08%), CD123 to 198 (6.00%) and CCR4 to 175 (1.05%). The other 26 keep 150. CD86 and CD25 have 1.5% of their cells below 0, but a spread of 135 and 123, under the floor. CCR7's cells below 0 spread to 698 but are 0.12% of its cells, and CD161's (eFluor 450) 0.01%, so the guard keeps them at 150. DEAD and CD45 have no cell below 0. A run records each channel's cofactor, `f` and `sd` in `run.json` ([Flow run records](reproducibility.md#flow-run-records)).

**Scale.** Each transformed channel then has its mean subtracted and is divided by its standard deviation, computed with `ddof=0`, so every channel has mean 0 and SD 1. `create_dn` and both clusterings work on Euclidean distances, in which a channel counts in proportion to its variance. After the Transform the channels' spreads still differ, with the marker's brightness and with how well its cofactor fits it. On two public FlowCAP files at a cofactor of 6000, MHC II's SD was 13 times IFNa's, so in a squared distance it counted about 170 times as much. At 150, the cofactor `auto` gives every one of their channels, it was 5.2 times, about 27 times as much. Scaling gives every channel the same weight. A channel whose SD is 0 has one value in every kept event. It is divided by 1, so it is 0 after centring and adds nothing to the distances. `--no-standardize`, or `standardize=False` in `ClusterSettings`, skips the stage and gives the run of earlier versions.

The mean and SD are pooled: computed once over the kept events of every clustered file together, after the populations and row filters, and applied to every file.

- Not per file. Scaling each file by its own mean and SD would centre away the differences between files that the comparison is for, such as a marker that is brighter in one group, and would put one raw value at different places in different files. One map for every file keeps a cluster the same region of marker space in each file, which the [single clustering](#design-choices-in-the-pipeline) relies on.
- Over the cells clustered only. The events outside the chosen populations or the filters, and the files left out of the clustering, don't set the scale, so the events left out, such as debris, can't widen it.
- Each event counts once, so a file with more kept events counts more in the statistics, as its nuggets do in the clustering.

The SD is a fair measure of a channel's spread only when the channel has no long tail. Where a few cells lie far out, they set the SD, and dividing by it squeezes the other cells into a narrow band of the scaled axis, so the clusters there sit close together while the tail stretches the distances. The cofactor decides how long the tail stays. On those FlowCAP files, whose values are small next to 6000, every channel kept a skewness between 5.7 and 84.9 after `arcsinh(x / 6000)`. At a cofactor of 150, the one `auto` gives each of their channels, all but CD11c (5.61) were between -0.64 and 1.62. The stage therefore records each channel's pooled skewness, the third central moment over the SD cubed, prints it beside the mean and SD, and warns when any is beyond 5 either way. It doesn't change the cofactor or switch to a robust spread such as the IQR: either would change which cells count as close in a way the run can't check, so the choice stays with whoever picks the cofactor.

The statistics take one pass over the files, each read in turn, merging each file's count, mean, and sums of squared and cubed deviations into the running totals with the pairwise update, in float64. The nuggets then take a second pass, so only one file's events are in memory at a time. `datanuggets_flow.pipeline.pooled_scaling` gives the statistics from Python.

The tables report channel values in the Transform stage's units, since a mean of 0.3 SD is hard to read without the SD. The scaling is undone as `x * sd + mean`. The map is affine, so a weighted mean of scaled values undone is the weighted mean of the transformed values. That holds for the nugget centers, `cluster_centers.csv`, `cluster_markers.csv`, `group_markers.csv` and `cells.csv`. The PCA and the t-SNEs are of the scaled nuggets, and their coordinates are as computed. `pca_center.csv` holds the center in the transformed units and the pooled SD as `scale`, as R's `prcomp` records `center` and `scale`, so a row `x` scores `((x - center) / scale) @ loadings`. `nuggets_N.csv`'s `scale` is `create_dn`'s and stays in the scaled units.

Nothing in the repository shows that scaling gives better clusters on any data.

### Comparing groups of files

With `--groups`, a run compares groups of files in `group_summary.csv` and `group_markers.csv`. The comparison is descriptive. It reports means, spreads and differences of what the run counted and makes no test of whether a difference is real: no p-value, no confidence interval, no correction for comparing many clusters. Neither paper and no R code describes it. Its design is the package's own.

1. The unit is the file. A file's percentage in cluster c is its clustered cells in c over all its clustered cells, times 100, the `percent` of `cluster_summary.csv`. A file with no cells in c counts as 0.
2. For each group and cluster, `group_summary.csv` gives `samples`, the group's clustered files, and the mean, the standard deviation (n − 1 in the denominator, empty for a single file), the minimum and the maximum of their percentages. Every file weighs the same in its group's mean, whatever its cell count.
3. The reference group is the group of the lowest-numbered clustered file. In each cluster, every group's mean is set against the reference group's: `diff_vs_ref` is mean − reference, in percentage points, and `log2fc_vs_ref` is log2((mean + pc) / (reference + pc)). The reference group's own are 0.
4. The pseudocount pc, written in `log2fc_pseudocount`, is half a cell per file. For a file of N clustered cells, half a cell is 50 / N percentage points, and pc is the mean of that over the run's clustered files, one value for the whole table. It keeps a cluster with no cells in one group from giving an infinite fold change. For a cluster of a few cells per file it pulls the fold change towards 0, which is why the table keeps each group's raw mean and standard deviation beside it.
5. `group_markers.csv` gives, for each group, cluster and channel, the plain mean over the group's files with cells in the cluster of each file's mean of the channel there (`cluster_markers.csv`, in the Transform stage's units), the reference group's, and the difference. The mean is empty where the group has no file with cells in the cluster, and the difference where either side's mean is.

### Design choices in the run's added tables

These choices come from the code, like those above, and none comes from the papers or from R. Nothing in the repository measures how they affect a conclusion.

| Choice | What the code does | Constant in `_defaults` |
| --- | --- | --- |
| The unit of the group comparison | each file's percentage of its clustered cells, every file weighing the same in its group's mean | none |
| The spread | the sample standard deviation, n − 1 in the denominator and empty for one file, with the minimum and maximum | none |
| The reference group | the group of the lowest-numbered clustered file | none |
| The fold change's pseudocount | half a cell per file, 50 / N percentage points for a file of N clustered cells, averaged over the clustered files and written in `log2fc_pseudocount` | `FLOW_LOG2FC_CELLS` = 0.5 cells |
| The marker comparison | the unweighted mean of the per-file cluster means over the files with cells in the cluster, and its difference from the reference group's | none |
| A test of the differences | none | none |
| Cluster colours | `TAB10[:k]` up to 8 clusters. More fall in 8 families. With the tree, a family is one cluster of the same tree cut at 8. Weighted k-means has no tree, so a family is a block of neighbouring cluster numbers: cluster `c` of `k`, numbered from 0, is in family `c * 8 // k`. A family's first cluster keeps its `TAB10` colour, and each other colour is picked from the sRGB colours readable on `#ffffff` and `#111318` as the one farthest by CIEDE2000 from those already given, siblings counting at 5 and other families at 3 | `CLUSTER_PARENT_K`, `CLUSTER_GRID_LEVELS`, `CLUSTER_BACKGROUNDS`, `CLUSTER_MIN_CONTRAST` = 2.5, `CLUSTER_SIBLING_DE00` = 5, `CLUSTER_OTHER_DE00` = 3, `CLUSTER_SCORE_DECIMALS` |
| The sampled cells | up to `--cells-per-file` of each file's clustered cells, without replacement, with a generator seeded by `--seed` and the file number | `FLOW_CELLS_PER_FILE` = 2000 |
| The PCA tables' signs | each component's largest loading made positive, as `clusters_pca.png` draws it | none |
| The live-cells histograms | each channel's kept cells on `arcsinh(x / c)`, `c` that channel's cofactor, or raw with cofactor 0, in bins every file shares, spanning the pooled 0.1% to 99.9% quantiles widened by 5% of that width on each side but not past the data, with the cells outside counted below or above | `LIVECELLS_BINS` = 128, `LIVECELLS_RANGE_QUANTILES`, `LIVECELLS_RANGE_PAD`, `LIVECELLS_FLAT_WIDTH` |
| The live-cells channel suggestion | by the channels' names alone, never their values: a viability dye by its usual names, and CD45 as a word of its own not followed by an isoform such as RA or RO. No threshold is ever suggested | none |

### Staged runs

A `--gates-only` run saves each file's populations as masks. A `--from-gates` run takes the kept events from those masks and doesn't run the finder again, so the populations it clusters are the ones its gate figures show. [Staged runs](cli.md#staged-runs) describes the gate folder and the checks that hold the masks to the files they were found in.

### The t-SNE figure

`clusters_tsne.png` places the nugget centers in two dimensions with scikit-learn's `TSNE`. It draws the clusters and plays no part in making them. `_defaults.TSNE_ARGS` pins the arguments that shape the picture, `n_components=2`, `init="pca"`, `learning_rate="auto"` and `max_iter=1000`, so a change of scikit-learn's defaults can't move it through them. The perplexity, 30 by default, and the seed, 0 by default, come from `--tsne-perplexity` and `--tsne-seed`. For n nuggets the perplexity is lowered to (n − 1) / 3 when that is smaller, since scikit-learn needs it below n. The other arguments are scikit-learn's defaults. With `--no-tsne` the figure is left out and scikit-learn isn't imported.

### The clustering step from Python

The steps after gating can be run without the command line. With `files` a list holding each file's kept, transformed events as arrays of one row per event, this is what the Scale stage and steps 5 and 6 of [a run](cli.md#what-a-run-does) do, up to rounding:

```python
import numpy as np
from datanuggets import RDraws, create_dn, get_dn_means, wkmeans, wmean

pooled = np.vstack(files)
mean, sd = pooled.mean(axis=0), pooled.std(axis=0)  # ddof=0, every file's events together
sd[pooled.min(axis=0) == pooled.max(axis=0)] = 1  # a constant channel is divided by 1
scaled = [(x - mean) / sd for x in files]

seed = RDraws(291102)  # R's set.seed(291102) draws, restarted on every call
dns = [
    create_dn(x, center_method="original", dn_num2=min(1000, len(x)), seed=seed, n_jobs=-1)
    for x in scaled
]
centers = np.vstack([d.centers for d in dns])
weights = np.concatenate([d.weights for d in dns]).astype(float)
use = weights > 0
km = wkmeans(centers[use], 8, w=weights[use], num_init=10, max_iter=100, seed=seed)
labels = np.full(len(centers), -1)
labels[use] = np.unique(km.labels, return_inverse=True)[1]  # R's numbers, with no gaps
means = np.vstack([get_dn_means(x, d) for x, d in zip(scaled, dns)])  # each nugget's events' mean
cluster_means = wmean(means[use], labels[use], weights[use]) * sd + mean  # transformed units
```

`np.vstack` holds every file's events at once. `pooled_scaling` gets the same statistics a file at a time. For a `--no-standardize` run, set `scaled = files`, so that `create_dn` and `get_dn_means` both read the transformed events themselves, and drop the last line's `* sd + mean`. With `--method tree`, the `wkmeans` call and the `np.unique` line become `labels[use] = cut_tree(whclust(centers[use], weights[use]), k=8)`, with `cut_tree` and `whclust` imported. On the two halves of the public `202_fluor.npz` fixture's 50,000 events, transformed as `arcsinh(x / 150)`, this code gives the centers, labels and total WWCSS of `cluster_nuggets` exactly, and its cluster means to within 2.3e-16, since `get_dn_means` sums in long double.

The nuggets of file `i` are the next `dns[i].n_nuggets` entries of `labels`, and `dns[i].assignments` gives each of its events a nugget. With `--method tree`, the pooled tree holds an n by n matrix over all the files' nuggets, so with 1,000 nuggets a file, ten files make the 10,000-row case that needs 800 MB. Weighted k-means holds no such matrix.

`cluster_stage` in `datanuggets_flow.pipeline` does the same from gated files, reading each one again for its kept events, and writes the tables and figures too. [api.md](api.md#the-flow-pipeline-library) has an example.

## Relation to the papers

Beavers et al. (2025) define data nuggets (Algorithms 1 and 2, Section 3) and weighted k-means for nuggets (Algorithm 3, Section 3.1). They apply them to a flow cytometry dataset of over one million observations (Section 4). That example made nuggets of the whole dataset with mean centers, R = 5,000, C = 0.01, Minit = 10,000, M = 2,000 and Euclidean distance. It refined them with the tuning value ν = .25 and Nmin = 2. It compared weighted PCA of the nuggets with PCA of the full data and of a random sample. It clustered the refined nuggets with weighted k-means and chose the number of clusters by comparing WWCSS across a range of k.

`datanuggets-flow` differs from that example in these ways:

| | Paper, Section 4 | `datanuggets-flow` |
| --- | --- | --- |
| Input | one dataset | one or more FCS files, gated on forward and side scatter first (FSC-A and SSC-A on the demo files), with populations picked per file |
| Transform | none stated | `arcsinh(x / c)` by default, `c` per channel: 150, or the spread of the channel's cells below 0 where that's wider and at least 1% of the cells are below 0 |
| Scaling | none stated | every channel to mean 0 and SD 1 over all the clustered files' kept events, by default |
| Nuggets | one set for the whole dataset, then refined | one set per file, not refined |
| Centers | mean centers | original centers by default, the event each nugget was built around, with `--center-method mean` or `random` as options. Without refinement they stay as built. `refine.DN` would make every center its members' mean |
| `create_dn` settings | C = 0.01, M = 2,000 | the library default C = 0.1, Minit = 10,000 and 1,000 nuggets a file |
| Clustering | weighted k-means with "ten initial centers", the configuration with the least WWCSS kept, k from 5 to 15 compared by WWCSS, 12 chosen by a "second difference method" | weighted k-means on the pooled nuggets at a given k, as `WCluster`'s `Wkmeans` runs it, with 10 starts of up to 100 rounds, or the hierarchical tree cut at a given k with `--method tree` |
| Weights across files | not applicable, one dataset | each nugget weighs its event count, so a file with more kept events weighs more in the clustering |
| PCA | weighted PCA compared with PCA of the data | a weighted PCA figure of the nuggets |
| Conditions | not applicable, one dataset | with `--groups`, a descriptive comparison of groups of files against a reference group, with no test ([Comparing groups of files](#comparing-groups-of-files)) |

The paper reports that the first three principal components are "moderately recovered" with the 2,000 nuggets before refinement and "strongly recovered" with the 3,135 refined ones (Section 4). `datanuggets-flow` doesn't refine. The library's `refine_dn(x, dn, ev_tol=0.25, min_nugget_size=2)` runs the paper's refinement on one file's nuggets, as the library's [methodology](https://github.com/ron2k1/datanuggets/blob/main/docs/methodology.md#refining-nuggets) describes.

The paper says Section 3.1 describes its second difference method, but Section 3.1 doesn't. For a tree over `n` rows, `whclust`'s heights give the WWCSS of every cut from 1 to `n - 1` clusters without reclustering. The height of merge `n - k`, counted from 1, equals `wwcss(x, cut_tree(tree, k=k), w)`, which is `tree.height[n - k - 1]` in Python. These are the WWCSS of the tree's nested cuts, not of a k-means fit at each k, so a rule applied to them needn't choose the paper's k. A weighted k-means run records its own total WWCSS in `run.json`, one k per run.

The gate finder isn't in the paper. It comes from Prof. Cabrera's own scripts.

Cherasia, Cabrera, Fernholz and Fernholz (2023) use data nuggets for regression. They build the nuggets from the features alone, without the response. Of the three estimators they compare, weighted least squares on the nugget centers and mean responses, with the row counts as weights, performs best. In Section 6 they propose, without an example, keeping each nugget's count of each class for a binary or categorical response. For a binary one they propose splitting nuggets until none mixes outcomes. Their standard errors assume i.i.d. errors. In `datanuggets-flow` every nugget holds the events of one file, so each nugget belongs to one sample and one condition. The chapter doesn't treat replicate samples. The comparison of groups of files ([Comparing groups of files](#comparing-groups-of-files)) takes nothing from it or from the 2025 paper. It sets each group's mean per-file cluster percentages and marker means against a reference group's and tests no difference.

## Evaluation

### Against Cabrera's script

The reference for the flow finder is Prof. Cabrera's Python, not the original R code. `benchmarks/flow/` holds the reference functions word for word, the whole reference script with only its two paths read from the command line, and the reference finder cut at its steps. `check_reference.py` runs the whole reference script with FlowKit and checks that its masks equal the masks of those pieces. On an Apple M4 machine with 16 GB it matched on all four files it was given.

The suite compares with three fixtures recorded from the reference code on files of the record, each thinned to 50,000 events:

- The grid's bins and coordinates, the focal maxima and the refined peaks must equal the reference values exactly. The grid's log counts must equal the reference counts to 1 unit in the last place, since on an x86 CPU without AVX-512 numpy's `log1p` is the C library's, which can differ in the last bit.
- `find_area` must equal the corrected rule written out as a plain distance test, and the reference code's recorded cells must equal the mirrored disc written out the same way.
- The gate on the reference cells must give the reference masks, and so must the whole finder given the reference area rule, or differ only on events within 1e-9 of the data's range from the hull's edge.
- The reference code's guards and its row and column limits are each tested on both sides of the line.

`compare.py` runs the reference code and ours piece by piece on any FCS file or folder, on the same arrays on both sides, and exits with 1 if a piece differs beyond the hull's edge. It pairs per-sample thresholds with the workbook's rows, where the reference script pairs them with the samples in FlowKit's `$FIL` order. On the same machine over all 44 files, the grid, the maxima and the peaks equal the reference output on every file. The gate on the reference cells and the finder with the reference `find_area` equal the reference output on 40, and on the other 4 one event each differs, lying exactly on the hull's edge. `stress.py` joined the 44 files into one sample of 10,183,290 events, and ours given the reference `find_area` gave the reference masks for every event. The record has no reference gates, so these checks do not establish biological validity. [reproducibility.md](reproducibility.md#flow-comparepy-piece-by-piece) has the comparison runs.

### What is tested and what is not

| Part | Status |
| --- | --- |
| Data nuggets, the `WCluster` functions, `cut_tree` | the `datanuggets` library's, checked against R's recorded output there, as its [methodology](https://github.com/ron2k1/datanuggets/blob/main/docs/methodology.md#against-r) describes |
| The gate finder's pieces | ported, and checked against the reference code on the fixtures and on the 44 files |
| `find_area`'s disc on the peak | a correction of the reference code, tested against an independent statement of the corrected rule. Whether it stands is an [open problem](limitations.md#open-problems) |
| `--disc reference`, `datanuggets_flow.mirrored_area` | `tests/flow/test_flow_area.py` checks it gives the reference code's recorded cells on all three fixtures, and `test_flow_gate.py` that the finder takes it as `area=` |
| `datanuggets-flow`'s argument and population parsing, the union of picks, the file listing, the prompt | unit tests in `tests/flow/test_flow_pick.py` |
| `datanuggets-flow`'s transform, per-file nuggets, pooling, clustering method and `k` | design choices. `test_flow_pick.py` runs the command end to end on 50,000 real events of `202.fcs` from the fixtures, not on an FCS file, and pins its tables' digests. That catches a change in the output but doesn't show the clusters are right |
| The Scale stage | `tests/flow/test_flow_scale.py` checks on real events of the fixtures that the pooled statistics give every channel mean 0 and SD 1 over two files and count only the events clustered. It checks that a constant channel is divided by 1, that `cells.csv`'s placement is scaled the same way, that the value tables stay in the transformed units, and that `--no-standardize` writes the earlier tables. Whether scaling gives better clusters is a design choice, not a tested result |
| The finder's parameters, the flow settings' checks | `tests/flow/test_flow_settings.py` pins every constant in the tables above and every default, and checks each refusal |
| Staged runs, `gates.json` and `run.json` | `tests/flow/test_flow_state.py` saves and loads gate folders and refuses each damaged one. `test_flow_stages.py` checks that the two stages give the one-shot run's table digests on one and three files of the fixtures, and `test_flow_fcs_integration.py` that they write its tables byte for byte from an FCS file |
| The group comparison, `--groups` | a design choice. `tests/flow/test_flow_outputs.py` recomputes `group_summary.csv` and `group_markers.csv` from the run's own tables and the pseudocount from its events tables. That shows the tables follow the rules above, not that a difference they show is real |
| The clusters as cell types | not validated. No result in the repository shows a cluster is a cell type |
| The paper's claims about structure preservation | not tested here |

The clustering steps of `datanuggets-flow` call `create_dn`, `wkmeans`, `whclust`, `cut_tree` and `wmean`, the library functions checked against R. What isn't checked is the pipeline that composes them. No test compares a whole flow run with R. The R calls a run records ([Flow run records](reproducibility.md#flow-run-records)) were run in R outside the suite and matched bit for bit on four runs: one file, three files, the automatic cofactor and the Scale stage.

## References

Beavers, T. E., Cheng, G., Duan, Y., Cabrera, J., Lubomirski, M., Amaratunga, D., and Teigler, J. E. "Data Nuggets: A Method for Reducing Big Data While Preserving Data Structure." Journal of Computational and Graphical Statistics 34(1), 330-342, 2025. Published online in 2024. DOI: `10.1080/10618600.2024.2341896`.

Cherasia, K. E., Cabrera, J., Fernholz, L. T., and Fernholz, R. "Data Nuggets in Supervised Learning." In M. Yi and K. Nordhausen (eds.), Robust and Multivariate Statistical Methods: Festschrift in Honor of David E. Tyler, 429-449. Springer, 2023. Published online in 2022. DOI: `10.1007/978-3-031-22687-8_20`.

Flow data: [Zenodo record 22079206](https://zenodo.org/records/22079206), "Flow cytometry data of PBMC of critically ill, mechanically ventilated patients", by Kreutmair and Unger, licensed under CC BY 4.0.
