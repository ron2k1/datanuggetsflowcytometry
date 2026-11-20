# Limitations and open problems

`datanuggets-flow` is a research alpha. The API may still change, and nothing in this repository validates its clusters as cell types. Its gates, transform, scaling and clustering need checking on each dataset you run it on. Record the package version and the run's `run.json` with every result.

The reduction and the weighted clustering are the `datanuggets` library's. Its own limits, such as where it differs from R, its eigen solvers and its planned API changes, are on the library's [limitations](https://github.com/ron2k1/datanuggets/blob/main/docs/limitations.md) and [compatibility](https://github.com/ron2k1/datanuggets/blob/main/docs/compatibility.md) pages.

## CLI safeguards and boundaries

1. **Each run needs a new output folder.** The default creates `outputs/flow-<timestamp>/` relative to the current directory. An existing `--out` path is refused, even if empty. A failed or cancelled run keeps its partial results with an `INCOMPLETE.txt` marker. Treat them as incomplete work and retry in a new folder.
2. **At least two distinct fluorescence channels are required.** The CLI checks this before asking for populations. Its PCA figure needs two components, and a one-dimensional workflow isn't supported.
3. **Clustering needs at least three occupied pooled nuggets, and weighted k-means two per cluster.** Very small retained samples or `--dn-num2 2` on a single file can fall short. The CLI reports this before clustering. Weighted k-means, the default, needs twice `--k` occupied nuggets. It stops when there are fewer, and it stops when a start can't draw a partition that fills `--k` clusters. It never lowers `--k` for you. With too few nuggets, keep more cells, lower `--k`, or raise `--dn-num2`, which must stay below `--dn-num1`. When a start fails on a large pool, lower `--k` or use `--method tree`. More nuggets make that failure more likely, as [Weighted k-means starts](#weighted-k-means-starts) describes.

The [CLI guide](cli.md) explains the output policy and errors.

## Limitations

### Memory

- The hierarchical tree, `--method tree`, keeps an n by n float64 matrix over all the pooled nuggets: 32 MB at 2,000 nuggets and about 800 MB at 10,000.
- The run pools the nuggets of every kept file. At the default of 1,000 nuggets a file, 44 files give 44,000 pooled nuggets, and the tree's matrix alone then needs about 15.5 GB. Reducing each file separately doesn't bound the tree's memory for a whole folder.
- Weighted k-means, the default, builds no such matrix.
- Each file's `create_dn` call builds a square distance matrix over its first-stage centers. That's about 800 MB at the default `--dn-num1` of 10,000. The library's limitations page has the detail.

### Weighted k-means starts

The run's weighted k-means is the library's `wkmeans`, the port of `WCluster`'s `Wkmeans`. Each start draws random partitions until one puts every cluster on at least two nuggets and leaves no cluster without a nearest nugget. A start may draw 1,000 partitions. When none of them fills all `k` clusters, `wkmeans` raises an error where R would keep drawing. A start found within that cap is R's start, so the cap changes no result it lets through.

The cap is reached near `n = 2k`, where few partitions put every label on two nuggets. It's also reached far above `2k` on few channels. Each label of a random partition then holds many nuggets, so the labels' weighted means all sit near the overall mean, and some label is nearest to no nugget. More nuggets make that worse. Two measurements on public data show it:

- On the `202_fluor.npz` fixture's 50,000 events, three channels on `arcsinh(x / 150)` scaled to SD 1 and split into 2, 4 and 8 files of 1,000 nuggets each, a start at `k = 20` was found for 2,000 and 4,000 pooled nuggets. For 8,000 it wasn't found within 1,000 draws.
- On Pop 1 of `202.fcs`, `--k 50` of 400 nuggets clustered in under 3 seconds. `--k 100` hit the cap with 400 nuggets and with 1,000.

The command turns the error into one that names `--k` and ends `lower --k or use method tree` ([failure conditions](cli.md#failure-conditions)). A lower `--k` or the tree always helps. More nuggets help only near twice `--k`.

### Tests

- The FCS reader and the whole command are tested on an FCS 3.1 file rebuilt from measured fixture data, the recorded `202` events with their channel names and labels. That doesn't cover every instrument's encoding or metadata.
- No test compares a whole flow run with R. The [methodology](methodology.md#what-is-tested-and-what-is-not) lists what the suite covers.

### Flow cytometry

- The finder's cutoffs are Prof. Cabrera's: a peak's row above 10 and below 90 and its column below 90, with no lower limit on the column, the 0.85 and 0.9 quantiles, and `t11` to `t22`. They haven't been tuned for other panels or instruments. On the 44 PBMC files of the Zenodo record that [reproducibility.md](reproducibility.md) lists, the finder found 2 to 7 populations per file.
- `datanuggets-flow` reads FCS files through flowio, one of its dependencies. It clusters the events as stored, uncompensated, and warns when a file's spillover matrix isn't the identity. The functions `datanuggets_flow` exports take arrays and don't read FCS files. `datanuggets_flow.pipeline.read_fcs` reads one for the command and the stages.
- The default channels are every channel of the first file whose name ends in `-A` and doesn't start with FSC or SSC. A viability dye recorded on such a channel is clustered with the markers unless `--exclude-channels` leaves it out or `--channels` lists the channels to use.
- A gate folder doesn't record a file's spillover matrix. `--from-gates` reads each file again and repeats the spillover warning, but neither stage compensates, and the folder doesn't show whether a file needed it. A file that moves or changes after gating has to be gated again ([Staged runs](cli.md#staged-runs)).
- The group comparison `--groups` writes is descriptive. `group_summary.csv` and `group_markers.csv` give each group's mean, spread and range of per-file cluster percentages and its marker means. They set each against a reference group, the group of the lowest-numbered clustered file, as a difference and a log2 fold change. Nothing tests whether a difference is real. There's no p-value, no confidence interval, no correction for comparing many clusters, and no model of how files vary within a group. The fold change adds half a cell per file, so for a cluster of a few cells it reads closer to 0 than the raw means. Read it with the means and standard deviations beside it. The design is the package's own, from neither paper nor R ([methodology.md](methodology.md#comparing-groups-of-files)).

## Open problems

1. **The gate area rule.** Which rule should place each peak's area is undecided. `--disc reference`, the default, mirrors the reference code: its density test reads the peak's cell, and its distance disc sits on the mirrored cell. `--disc peak` centers the disc on the peak. The library function `lymphmacro_finder` uses the peak rule unless it's given `area=mirrored_area`. On `202.fcs` the two rules put 107,909 of the 282,270 events in a different set of populations. Over the 44 files of the public PBMC record, they gate 1.4% to 38.7% of a file's events differently, 8.0% at the median. [methodology.md](methodology.md#the-disc---disc-reference-and---disc-peak) explains the difference.
2. **Viability channels in the default set.** Whether the default channels should leave out a viability dye is undecided. For now, leave it out with `--exclude-channels` or list the channels with `--channels`.
