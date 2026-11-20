# Release notes

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
