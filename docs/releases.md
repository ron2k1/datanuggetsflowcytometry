# Release notes

## 0.1.0a5

This release fixes three of the limits listed for 0.1.0a4: scatter names, a label column in the default channels, and the app's upload check. It's on PyPI as `datanuggets-flow==0.1.0a5` and is the app image `ghcr.io/ron2k1/datanuggets-flow:0.1.0a5`. The `datanuggets` library and the dependencies are those of 0.1.0a3.

### Changed

- Scatter is a channel named `FS` or `SS` followed by `C`, a space, a dash, an underscore or nothing, in any case. So `FSC-A`, a spectral cytometer's `SSC-B-A`, a Navios's `FS INT` and a lowercase `fsc-a` are scatter. A marker named from those letters, such as `SSEA4-A`, isn't, and names such as `FS1-A` or `FSPeak-A` are now marker channels too.
- Files with lowercase scatter or a marker whose name starts with `SS` get different default channels than under 0.1.0a4. Clustering a 0.1.0a4 gate folder with `--from-gates` takes the new defaults unless `--channels` names the channels.
- A default channel holding NaN or an infinite value among the kept cells, as a processed file's label column can, is left out with a warning. When fewer than two default channels are left, the run stops and asks for `--channels`. A channel named with `--channels` is still refused.
- That check reads each kept file once before the selection, so a run on the default channels makes one more pass over the files.

### App

- The page reads an upload's first six bytes and refuses a file without an FCS 2.0, 3.0 or 3.1 header before sending it. The server still refuses such a file when the browser can't read those bytes.
- The progress bar moves while a run checks the default channels, and Cancel stops the run there.
- The Cluster form sends no channel list when the ticked channels are the defaults, with or without a viability dye left out, so the package's default rule applies in both cases.
- Datasets group uploads by the new scatter rule, so lowercase scatter or an `SSEA4` marker can put a file in a different dataset than under 0.1.0a4.

## 0.1.0a4

This release runs FCS files from instruments other than the PBMC demo's. It's on PyPI as `datanuggets-flow==0.1.0a4` and is the app image `ghcr.io/ron2k1/datanuggets-flow:0.1.0a4`. The `datanuggets` library and the dependencies are those of 0.1.0a3.

### Changed

- Scatter is known by name, as a channel starting with `FS` or `SS`, such as `FSC-A` or a Navios's `FS INT`. The gate uses the first file's forward and side scatter unless `--fsc` and `--ssc` name others. A file with no scatter is gated on its first two default channels ([Files from other instruments](cli.md#files-from-other-instruments)).
- When a file has fewer than two distinct `-A` channels, as with a FACSCalibur's heights or a mass cytometer's isotopes, the default channels are every channel but scatter and Time.
- Events past a gate channel's range (`$PnR`) are left out of every population when they're at most 1% of the file's events. The gate's log counts them, and `gates.png` keeps its axes on the rest. When more are past range, none are left out.
- A run warns when a clustered channel takes one value in every kept cell, and when files give one detector different stains (`$PnS`). The CLI prints each warning once as a `warning:` line.
- Clustering refuses a channel that holds NaN or an infinite value among the kept cells, and names it.
- The message for a file without the scatter channel names the flag to set.

### App

- An upload is taken as an FCS file by its header (FCS 2.0, 3.0 or 3.1) whatever its name, so a FACSCalibur's `.B08` or an `.LMD` file loads.
- The gate form's X and Y channel lists start on the scatter the file has, else on two different channels it offers. The form refuses one channel for both.
- Datasets group uploads by the package's default channels, so two mass cytometry panels no longer share a dataset.

## 0.1.0a3, first alpha

The first release of `datanuggets-flow`, on PyPI as `datanuggets-flow==0.1.0a3` and as the app image `ghcr.io/ron2k1/datanuggets-flow:0.1.0a3`. It needs Python 3.12 or newer and depends on `datanuggets>=0.1.0a3,<0.2`, numpy, scipy, flowio, matplotlib, pandas and scikit-learn. The code is GPL-2.0-only.

### Included

- The `datanuggets-flow` command. It gates FCS files with Prof. Cabrera's finder, asks which populations to keep in each file, and clusters the kept events of every file together. It runs at once or in two stages, `--gates-only` and `--from-gates` ([Staged runs](cli.md#staged-runs)).
- The Transform and Scale stages. Each clustered channel becomes `arcsinh(x / c)`, with a cofactor picked per channel from the cells being clustered, and is scaled to mean 0 and SD 1 over all clustered files ([Transform and Scale](cli.md#transform-and-scale)).
- Per-file nuggets with `create_dn`, pooled and clustered once with weighted k-means, `WCluster`'s `Wkmeans`, by default or with the hierarchical tree, `--method tree`. The nuggets and the k-means starts use R's draws from seed 291102, so `create.DN` and `Wkmeans` in R build the same nuggets and clusters ([rerunning a flow run in R](reproducibility.md#rerunning-a-flow-run-in-r)).
- Tables and figures for each run: per-file cluster shares, cluster marker levels, a weighted PCA, a 2-D and a 3-D t-SNE, a sample of cells and, with `--groups`, a descriptive comparison of groups of files. `run.json` records the settings, the cofactors, the R calls that rebuild the run and the package versions ([flow run records](reproducibility.md#flow-run-records)).
- The Python library in `datanuggets_flow.settings`, `.pipeline`, `.state` and `.figures`, which gates and clusters without the command ([API](api.md#the-flow-pipeline-library)).
- The web app in one Docker image for linux/amd64 and linux/arm64, with four public PBMC files as a demo ([Running the app locally](app/running-locally.md)).

### Before using it on your data

The API may change before a stable release. Pin the version and keep each run's `run.json` and gate folder. Look at the gates of every file. The command doesn't compensate, and nothing in this repository validates its clusters as cell types. Weighted k-means stops rather than clustering into fewer than `--k` clusters, and a large `--k` can fail to start ([limitations.md](limitations.md#weighted-k-means-starts)). Read the [limitations](limitations.md) and the [methodology](methodology.md) before interpreting results.
