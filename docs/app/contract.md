# datanuggets-flow app: build contract

The contract the app was built to. It pins the repository layout, the package functions the app
calls, the HTTP API under `/api/v1`, the page's behaviour, the fixtures and the acceptance checks.
It was written for four builders (package, server, web, docker), and each section still names the
builder it was for. Section 3 is the API the server implements. A new endpoint is added there in
the same change.

## 1. Layout and ownership

| Builder | Files |
|---|---|
| package | `src/datanuggets_flow/**`, `tests/**`, `docs/**` except `docs/app/**`, `README.md`, `pyproject.toml`, `uv.lock` |
| server | `app/pyproject.toml`, `app/uv.lock`, `app/server/**` (import package `dnapp`), `app/tests/**` |
| web | `app/web/**` |
| docker | `Dockerfile`, `.dockerignore`, `compose.yaml`, `.github/workflows/app.yml`, `.github/workflows/image.yml`, `.github/dependabot.yml`, `app/demo/**`, `app/scripts/**`, `docs/app/running-locally.md`, root `.gitignore` |

```
src/datanuggets_flow/       the PyPI package "datanuggets-flow", built on the "datanuggets" library
app/pyproject.toml          project "datanuggets-app", never published (classifier "Private :: Do Not Upload")
app/server/dnapp/           FastAPI backend: config.py (every cap/env/default), main.py (create_app),
                            workspace.py, uploads.py, jobs.py, worker.py, views.py, limits.py
app/tests/                  server tests (pytest, httpx TestClient)
app/web/                    index.html, css/, js/ (ES modules), vendor/, fixtures/, tools/
app/demo/                   manifest.json, data/ (fetched at build, never committed)
app/scripts/                fetch_demos.py, smoke.py
```

The app depends on the package through `[tool.uv.sources] datanuggets-flow = { path = "..", editable = true }`
with `datanuggets-flow` and `datanuggets>=0.1.0a3,<0.2` in its dependencies, plus `fastapi>=0.115`,
`uvicorn>=0.30`, `python-multipart>=0.0.9`. Its dev group is `pytest>=8`, `pytest-xdist>=3.6`, `httpx>=0.27`.
`requires-python = ">=3.12"`. The root `pyproject.toml` stays the package's alone (no uv workspace).

## 2. Package API additions (package builder)

Rules: no matplotlib import in `colors.py`, `filters.py`, `projection.py`. Every new default goes
in `src/datanuggets_flow/_defaults.py`. Existing
tables keep their columns and existing figures stay byte-identical for k <= 8. No statistical
tests in v1. k has no cap beyond today's clamp to the nuggets in use (the hierarchical tree's;
weighted k-means, the flow's default since, clusters at k or fails the run, section 2's Cluster
stage).

### 2.1 `datanuggets.colors`

```python
TAB10: tuple[str, ...]   # matplotlib's default cycle, lowercase "#rrggbb", 10 entries
PARENT_K = 8             # in _defaults as CLUSTER_PARENT_K

def cluster_colors(k: int, parents: Sequence[int] | None = None) -> list[str]
def tree_parents(tree: WhclustResult, k: int) -> list[int]
def block_parents(k: int) -> list[int]
def population_colors(events: Sequence[int]) -> list[str | None]
```

- `cluster_colors`: k lowercase hex strings; entry c is cluster c (from 0). k <= 8: exactly
  `TAB10[:k]` (parents ignored). k > 8: `parents` (length k, values 0..7; default
  `block_parents(k)`) picks a family; family j's base is `TAB10[j]`. A family with one child gets the
  base itself. A family with n >= 2 children, taken in cluster order i = 0..n-1, t = i/(n-1):
  HLS of the base (colorsys), `l = 0.30 + 0.45 t`, `h = (h + 0.06 (t - 0.5)) mod 1`,
  `s = s if s == 0 else max(s, 0.55)`, back to hex by `round(255 v)`. All k strings distinct.
- `tree_parents(tree, k)`: child labels `cut_tree(tree, k=k)`, parent labels
  `cut_tree(tree, k=min(PARENT_K, k))`; result[c] = parent label of any member of child c (the
  cuts nest, so it is unique). For k <= 8 it is `list(range(k))`.
- `block_parents(k)`: `[c * PARENT_K // k for c in range(k)]` for k > 8, else `list(range(k))`
  (used where there is no tree: k-means).
- `population_colors(events)`: per population (from 0) the colour `plot.gates` draws it in under
  default rcParams: the i-th population with events > 0 gets `TAB10[i % 10]`, an empty one None.
- `flow.figures.result_figures` passes `colors=cluster_colors(k, tree_parents(pool.tree, k))` to
  the PCA and t-SNE panels and the legend, so the PNGs match the app. `_label_colors` and
  `_palette` do not change. A run clustered with weighted k-means has no tree (`pool.tree` is
  None), and `flow.outputs.pool_parents` gives `block_parents(k)` for it instead.

### 2.2 `datanuggets.filters`

```python
OPS = ("<", "<=", ">", ">=", "==", "!=", "between", "in")
@dataclass(frozen=True)
class RowFilter:
    column: str
    op: str
    value: float | str | tuple[float, float] | tuple[float | str, ...]
def parse_filter(text: str) -> RowFilter
def format_filter(f: RowFilter) -> str
def filter_mask(get_column: Callable[[str], np.ndarray], filters: Sequence[RowFilter], n: int) -> np.ndarray
```

- Grammar: `COLUMN OP VALUE`. OP is one of OPS with whitespace on both sides. COLUMN is everything
  before the first such OP, stripped, or a `[...]` bracketed name (needed when the name contains
  an OP word or edge spaces). VALUE: one value for comparisons, `lo,hi` for `between` (inclusive
  both ends, lo <= hi), one or more comma-separated values for `in`. A value that parses as a
  finite float is a number; otherwise a string, allowed only with `==`, `!=`, `in`. Strings
  cannot contain `,` `[` `]`. Examples: `MedInc >= 3`, `species in setosa,versicolor`,
  `[FJComp-BV510-A] between 0,50000`.
- `format_filter` writes the canonical spec (column bracketed when it holds whitespace, starts with `[` or is an operator);
  `parse_filter(format_filter(f)) == f` always.
- `filter_mask`: AND of all filters, bool array length n. Numbers compare as float64; a cell
  that is not a finite number under a numeric filter raises `ValueError` naming the column and
  0-based data row. Strings compare by exact text. Bad specs raise `ValueError` (in flow,
  re-raised as `FlowError(..., "row_filters")`).

### 2.3 `datanuggets.projection`

```python
class PcaView(NamedTuple):
    center: np.ndarray          # (p,) weighted column means
    rotation: np.ndarray        # (p, q) as the run's own figures draw it
    scores: np.ndarray          # (n, q) of the centers given
    sdev: np.ndarray            # (q,)
    variance_ratio: np.ndarray  # (q,), NaN sdev counted as 0, sums to 1
def pca_view(centers, weights, *, fix_signs: bool) -> PcaView
def project(x, view: PcaView, n_components: int | None = None) -> np.ndarray
def tsne_2d(centers, *, perplexity: float = TSNE_PERPLEXITY, seed: int = TSNE_SEED) -> np.ndarray
def tsne_3d(centers, *, perplexity: float = TSNE_PERPLEXITY, seed: int = TSNE_SEED) -> np.ndarray | None
```

- `pca_view` = `wpca(centers, wrow=weights)`; `fix_signs=True` multiplies rotation and scores by
  `plot.pca._signs` logic (largest absolute loading positive) without importing matplotlib. Flow
  uses `fix_signs=True` (clusters_pca.png); the general CLI uses `fix_signs=False` (its pca.png and
  pca_scores.csv draw raw LAPACK signs).
- `project(x, view, m)` = `(x - center) @ rotation[:, :m]`; `project(centers, view)` equals
  `view.scores` to 1e-9 relative.
- `tsne_2d` = the flow t-SNE (TSNE_ARGS, perplexity capped at (n - 1) / 3, random_state seed);
  `flow.pipeline.tsne_embedding` calls it and gives identical output. Missing scikit-learn raises
  `ImportError('t-SNE needs scikit-learn: pip install "datanuggets[tsne]"')`, the library's message.
- `tsne_3d` = a separate 3-component fit with the same TSNE_ARGS, perplexity cap and seed (not
  tsne_2d plus an axis); None when centers have fewer than 3 columns or rows (init="pca" can't
  give 3 components). Every t-SNE run writes it beside the 2-D one as `tsne3d.csv`; no figure draws it.

### 2.4 General analysis library + CLI

New `datanuggets.analysis`; `cli.py`'s `_run` becomes a thin wrapper that prints `on_line` text.

```python
@dataclass(frozen=True, kw_only=True)
class AnalysisSettings:
    columns: tuple[str, ...]
    row_filters: tuple[RowFilter, ...] = ()
    transform: tuple[str, ...] = ("none",)
    cofactor: float = 5.0
    nuggets: int = 200
    intermediate_nuggets: int = 1000
    center_method: str = "original"                    # choices mean random original
    analysis: tuple[str, ...] = ("kmeans", "pca")     # choices kmeans hclust pca tsne none
    clusters: int = 3
    refine: bool = False
    max_splits: int = 2
    num_init: int = 10
    max_iter: int = 100
    seed: int = 291102                                 # 0 to 2**31 - 1, R's set.seed range
    jobs: int = 1
    plots: bool = True
    cells: int = 2000                                  # rows sampled into cells.csv; 0 = none
def run_analysis(input: Path, out: Path, settings: AnalysisSettings, *,
                 on_line: Callable[[str], None] | None = None) -> Path   # returns out
```

- Raises `ValueError` for every bad input (same messages as today's CLI). `out` must not exist.
- create_dn, refine_dn and the k-means each draw a fresh `RDraws(seed)`, R's `set.seed(seed)`
  draws, so R's create.DN, refine.DN and DN.Wkmeans with the same arguments give the same nuggets
  and clusters. `center_method` is create_dn's, `--center-method` on the CLI. A k-means start the
  package gives up drawing raises `ValueError` "k-means can't make K clusters of these N occupied
  nuggets (...). Reduce --clusters, or increase --nuggets if they are near 2K".
- CLI flags added: `--filter SPEC` (repeatable, ANDed), `--cells N`, analysis choice `tsne`.
  Filter columns may be any header column, feature or not.
- Rows: filters apply to raw CSV text before transforms. `row0` everywhere stays the original
  0-based data-record index of the kept row. Fewer than 2 rows after filters: `ValueError`.
- New outputs: `cluster_colors.csv` (`method,cluster,parent,color`; cluster and parent numbered
  from 0 like the CLI's clusters; hclust parents from `tree_parents`, kmeans from `block_parents`),
  `tsne.csv` (`nugget0,tsne1,tsne2`, only with `tsne`), `tsne3d.csv` (`nugget0,tsne1,tsne2,tsne3`,
  only with `tsne`, 3+ features and 3+ nuggets), `cells.csv` (`row0,nugget0`,
  then `kmeans_cluster` / `hclust_cluster` when run, then `PC1..PCm` with m = min(5, p) when pca
  ran, projected with `project` on the same raw-sign view as pca_scores.csv, then
  `feature:<name>` transformed values). Cells: uniform without replacement,
  `numpy.random.default_rng(seed)`, min(cells, rows), sorted by row0.
- `run.json` adds `row_filters` (list of `format_filter` strings), `input_row_count` (data rows
  read), `cells_sampled`; `row_count` becomes rows analysed after filters. Existing keys stay.

### 2.5 Flow additions

`ClusterSettings` gains (to_dict/from_dict carry them; old records without them still load):

```python
row_filters: tuple[str, ...] = ()        # parse_filter specs on $PnN channels, raw (untransformed) values
groups: tuple[str, ...] | None = None    # one group name per gated file, in file order
cells_per_file: int = FLOW_CELLS_PER_FILE  # 2000, in _defaults; 0 = no cells.csv
```

- CLI: `--filter SPEC` (repeatable; `FLAGS["row_filters"] = "--filter"`), `--groups "a;a;b;b"`
  (one per file, `;`-separated, like per-file `--pops`), `--cells-per-file N`.
- `check()`: each filter parses (`FlowError` param `row_filters`); group names match
  `^[A-Za-z0-9][A-Za-z0-9 _.+-]{0,39}$`; count checked against files in `cluster_stage`
  (`FlowError` param `groups`); `cells_per_file` whole >= 0. A filter column missing from a file:
  `FlowError` param `row_filters` naming the file. New `pipeline.parse_groups(spec: str, n_files: int) -> tuple[str, ...]`.
- Filters AND with the chosen populations inside the file read `make_nuggets` already does; the
  MIN_KEPT_EVENTS rule counts cells after filters. `selection.csv` gains `filtered` and
  `filtered_percent` (100 * filtered / events) only when filters are given, and is then written
  after the nugget step.
- Reference group = first group, in file order, among kept files.
- New module `datanuggets_flow.compare`:
  ```python
  def cluster_markers(kept: Sequence[Kept], pool: Pool, labels: Sequence[str]) -> pd.DataFrame
  def group_summary(summary: pd.DataFrame, groups: Mapping[int, str]) -> pd.DataFrame
  def group_markers(markers: pd.DataFrame, groups: Mapping[int, str], channels: Sequence[str], labels: Sequence[str]) -> pd.DataFrame
  ```
  `FLOW_LOG2FC_CELLS = 0.5` (cells of each kept file) in `_defaults`, written as
  `log2fc_pseudocount` in percentage points.
- New files `cluster_stage` writes, after today's tables and before the figures, in this order
  (each is in `RunResult.files`):

| File | Columns | Notes |
|---|---|---|
| `cluster_colors.csv` | `cluster,parent,color` | cluster and parent from 1; k rows (k = pool.k) |
| `cluster_markers.csv` | `file_number,file,cluster,cells,<label 1>..<label p>` | every kept file x cluster 1..k. Mean per channel of that file's cells in that cluster, in the Transform stage's units (arcsinh(x / cofactor), or linear when cofactor 0) with the Scale stage undone, computed as the weight-weighted mean of that file's nugget centers in the cluster. With create_dn's center_method "mean", a nugget center is the mean of its assigned cells (R's formula, rounding aside) and weight = count, so this equals the direct cell mean to 1e-9 relative. Empty when cells = 0. |
| `pca_scores.csv` | `file_number,nugget0,PC1..PCp` | nuggets in use, pooled order, `pca_view(..., fix_signs=True)` |
| `pca_loadings.csv` | `channel,label,PC1..PCp` | |
| `pca_variance.csv` | `component,sdev,variance_ratio` | |
| `pca_center.csv` | `channel,label,center[,scale]` | center in the Transform stage's units; `scale`, each channel's pooled SD, only when the Scale stage ran, so a row x scores ((x - center) / scale) @ loadings |
| `tsne.csv` | `file_number,nugget0,tsne1,tsne2` | only when tsne on; same array as clusters_tsne.png |
| `tsne3d.csv` | `file_number,nugget0,tsne1,tsne2,tsne3` | only when tsne on, 3+ channels and 3+ nuggets; `tsne_3d` of the same nuggets, same rows as tsne.csv; no figure |
| `cells.csv` | `file_number,event0,nugget0,cluster,PC1..PCm,<label 1>..<label p>` | m = min(5, p); per kept file min(cells_per_file, kept cells) uniform without replacement by `default_rng([seed, file_number])`, sorted by event0; values in the Transform stage's units; PCs by `project` on the run's view, of the values scaled as the nuggets were |
| `groups.csv` | `file_number,file,group,kept` | only with groups; every gated file; kept is true/false |
| `group_summary.csv` | `group,cluster,samples,mean_percent,sd_percent,min_percent,max_percent,reference,diff_vs_ref,log2fc_vs_ref,log2fc_pseudocount` | only with groups. Rows: every group of the gated files in first-appearance order x cluster 1..k (a group with no kept file has samples 0 and empty stats). samples = kept files in the group; percent per file from cluster_summary.csv (a 0 counts); sd ddof=1, empty when samples < 2; diff = mean - reference mean; log2fc = log2((mean + pc) / (ref mean + pc)) with pc = log2fc_pseudocount, half a cell per file: the mean over the run's kept files f of 50 / N_f percentage points, N_f = the cells of f that its cluster percents are computed from (D2, 2026-10-28; same value on every row); the reference group's own diff and log2fc are 0. Descriptive only: no significance test, and no basis in the paper or the R code (a phase-2 design choice). Runs from before D2 have no log2fc_pseudocount column and used pc = 0.5 |
| `group_markers.csv` | `group,cluster,channel,label,samples,mean,reference,diff_vs_ref` | only with groups. samples = files in the group with cells > 0 in the cluster; mean = unweighted mean of those files' cluster_markers means; empty when samples = 0; diff empty when either side is empty |

- `state.write_run` needs no new keys for these tables (settings carry the new fields). The
  `cluster` StageEvent data gains `"k": pool.k`.
- The Transform and Scale stages ([methodology](../methodology.md#transform-and-scale)) run
  between `select` and `nuggets`, each with its StageEvent (`"transform"`, `"scale"`). With
  cofactor `"auto"`, `negative_tally` first reads every kept file once and sends a `"cofactor"`
  event per file read, with `file` set, an empty message and data `{"cells": n}`; the worker
  moves the bar from `FLOW_STEPS["select"]` to `FLOW_STEPS["cofactor"]` on them with the
  progress message `Cofactor: read file i of n`, checks for a cancel, and logs nothing. A set
  cofactor sends none. While the Scale stage pools its stats it sends a `"scale"` event per file
  read, with `file` set, an empty message and data `{"cells": n}`; the worker moves the bar from
  `FLOW_STEPS["transform"]` to `FLOW_STEPS["scale"]` on them and checks for a cancel, and logs
  nothing. The stage's own `"scale"` event (`file` None) follows. The events come in the order
  select, cofactor per file, transform, scale per file, scale, nuggets per file, cluster.
  `state.write_run(..., scaling=result.pool.scaling, cofactor=result.cofactor, pool=result.pool)`
  records them in run.json as `transform` and `standardize`, and the Cluster stage as
  `clustering` (below) (`{"mean", "sd", "ddof": 0, "cells", "skew"}` or
  `false`); it raises ValueError when scaling and `settings.standardize` disagree, or when an
  auto cofactor doesn't give one value per channel. `transform` is one of:

  ```text
  {"name": "arcsinh", "cofactor_from": "auto", "cofactors": [c_j], "negative_fraction": [f_j],
   "negative_sd": [sd_j | null], "floor": 150.0, "min_negative_fraction": 0.01}   auto, by channel
  {"name": "arcsinh", "cofactor": c, "cofactor_from": "set"}                       a number
  {"name": "none"}                                                                  0
  {"name": "arcsinh", "cofactor": c, "cofactor_from": "auto", "range": r}          the earlier rule
  ```

  The auto record's lists are in `channels` order, unrounded, and it has no `cofactor`. A
  run.json from before still loads: `state.run_transform` passes a per-channel record and one
  of the earlier header rule (one auto number with its `range`, null when a header gave none)
  through as written, reads an arcsinh without `cofactor_from` as set, and reads a record
  without `transform` from its settings' cofactor (6000 when it has none), as set. A record
  whose settings say `"auto"` but that has no `transform`, which `write_run` never writes,
  raises ValueError there.
- The Cluster stage clusters the pooled nuggets of weight above 0 with `settings.method`:
  `"wkmeans"` (the default, WCluster's Wkmeans as the package ports it, `num_init` 10 starts of
  `max_iter` 100 rounds, on R's `set.seed(seed)` draws) or `"tree"` (the hierarchical tree,
  Whclust cut into k). `settings.center_method` says where each nugget sits: `"original"` (the
  default, on one of its own cells) or `"mean"` (on the mean of its cells); the package and the
  API also take `"random"`, which the page offers only when "Use rX's choice" copies it from a
  run. `settings.draws` says how create_dn draws each file's nuggets: `"r"` (the default, R's
  `set.seed(seed)` draws, so they equal create.DN's) or `"numpy"` (the int seed's own, as every
  run before draws existed). Weighted k-means needs two nuggets in use per cluster: fewer than 2k
  fails the run with a FlowError, param `dn_num2`, "weighted k-means needs two nuggets in use per
  cluster: k = 12 needs 24, and the kept cells fill 20; lower k or increase dn_num2". A start
  the package gives up drawing fails it with one of param `k`, "weighted k-means can't make k =
  12 clusters of these 30 nuggets (...); lower k or use method tree": more nuggets help only
  near 2k, and on a large pool of few channels they make the start fail more often. The job
  reports either as `invalid_setting` with its param. The tree lowers k to the nuggets in use
  instead, as before. With the pool,
  `write_run` adds `state.clustering_record(settings, pool)` to run.json:

  ```text
  "clustering": {"method": "wkmeans|tree", "k": k asked, "k_used": int,
                 "nuggets_clustered": int, "nuggets_dropped": int, "total_wwcss": float | null,
                 "r": {"create.DN": str | null, "cluster": str}}
  ```

  `k_used` is the clusters the run has: the tree's k lowered to the nuggets in use, or weighted
  k-means' k less any cluster that ended empty (R's numbering, compacted). `nuggets_clustered`
  is the nuggets in use (weight above 0) and `nuggets_dropped` those of weight 0. `total_wwcss`
  is the clusters' total weighted within-cluster sum of squares. `r` gives the calls that
  rebuild the run with CRAN datanugget 1.5.0 and WCluster 1.3.0, e.g.
  `create.DN(x, center.method = "original", DN.num1 = 10000, DN.num2 = 1000, seed = 291102)`
  and `Wkmeans(centers, k = 8, obs.weights = weights, num.init = 10, max.iterations = 100,
  seed = 291102)` or `cutree(Whclust(centers, w = weights), k = 8)`; `create.DN` is null for
  draws `"numpy"`, which create.DN can't draw. A run.json from before has no `clustering`, and
  `ClusterSettings.from_dict` reads settings without `method` as the tree on mean centers and
  without `draws` as numpy, so an old run replays as it ran.
- The Transform stage's cofactor is `"auto"` by default. `resolve_cofactor` picks one per
  clustered channel, once per run and before any arcsinh, from `negative_tally`'s counts of the
  raw values of the cells the run clusters (the chosen populations after the row filters, in
  the files `make_nuggets` keeps): with `f_j` the share of channel j's cells below 0 and `sd_j`
  the median of `|x|` over those cells / 0.6745 (null when there are none), `c_j = max(150,
  sd_j)` when `f_j >= 0.01`, else 150. The median comes from a log-binned histogram (400 bins
  per decade over [0.01, 1e8), one bin below and one above), within one bin, about 0.6%, of the
  sorted `|x|` at rank `m_j / 2` of channel j's `m_j` cells below 0 (the lower middle value
  when `m_j` is even); with few cells below 0 that can sit a few percent under the usual
  median, the mean of the two middle values. A number, 0 included, is used as set for every channel and no tally is made. The stage's
  event says which: for auto a header line, `Transform: arcsinh(x / c) of every clustered
  channel, c per channel (auto: the SD of the cells below 0 where at least 1% of the kept cells
  are below 0, at least 150; else 150)`, then one line per channel such as
  `  CD123 (PE-A): 150  (3.5% below 0, SD 24)`, the SD shown where the rule used it; for a
  number `Transform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set`.

## 3. HTTP API v1 (server builder; the web builder codes against it)

All routes under `/api/v1`, JSON unless stated. The page and its assets are served from `/`
(`StaticFiles(directory=DN_WEB_DIR, html=True)`). Timestamps are ISO 8601 UTC strings. Floats in
payloads are rounded to 4 significant digits, except a flow plot's nugget weights (section
3.5), which are exact counts; NaN and missing become `null`.

Error shape (every non-2xx): `{"error": {"code": str, "message": str, "param": str | null}}`.

| HTTP | code |
|---|---|
| 400 | `invalid_host` (the Host header names a server the app does not answer for, see 3.7) |
| 401 | `no_workspace` (trial, no valid cookie on a workspace route) |
| 404 | `not_found` |
| 409 | `wrong_state` (e.g. run not done, upload in use, gate not done) |
| 410 | `workspace_expired` (cookie cleared in the response) |
| 411 | `length_required` |
| 413 | `too_large` |
| 415 | `unsupported_type` |
| 422 | `invalid_setting` (param = JSON field), `unreadable_file` |
| 429 | `rate_limited` (with `Retry-After` seconds) |
| 503 | `busy` (queue full, with `Retry-After`) |
| 507 | `out_of_space` |
| 500 | `internal` (message "Something went wrong (ref <8-char id>)"; details only in the log) |

FlowError messages are sent as `e.cli(lambda name: name)` with `param` = the JSON field name.
Absolute paths never leave the server: every message and record is scrubbed to file names.

### 3.1 Workspace and cookie

- `MODE=local`: one workspace `local` at `DATA_DIR/ws/local`, no cookie, no expiry, survives
  restarts. All caps off except the k <= 100 UI limit.
- `MODE=trial`: cookie `dn_ws` = `secrets.token_urlsafe(16)`, `HttpOnly; SameSite=Strict; Path=/api`,
  `Secure` when `DN_COOKIE_SECURE=1`, `Max-Age` = seconds to the hard cap. Idle expiry 6 h after the
  last request that touched it, and a hard cap 24 h after creation. Trial workspaces live in
  `DATA_DIR/trial/<ws>`, and boot wipes `DATA_DIR/trial` only, so a trial start on the data folder
  local mode uses leaves `DATA_DIR/ws/local` alone. A sweep every 10 min deletes expired workspaces
  whose jobs are not running.
- Layout: `<workspace>/meta.json` (the workspace folder is `DATA_DIR/ws/local` or
  `DATA_DIR/trial/<ws>`), `uploads/<uid>/<safe name>`, `gates/<gid>/` (gate folder),
  `runs/<rid>/` (run folder), `jobs/<jid>.json`, `jobs/<jid>.log`. Ids are per-workspace counters:
  `u1`, `g1`, `r1`, `j1`, `d1`. Safe names keep `[A-Za-z0-9._-]`, at most 100 chars, no leading
  `.` or `-`, de-duplicated with `-2`, `-3`.
- `meta.json` holds the records of the uploads, gates, runs, live-cells sets
  ([contract-livecells.md](contract-livecells.md)) and dataset names, and the id counters. A
  dataset name is kind `datasets`, record `{id, channels, name}`, with no folder. A `meta.json`
  from before a kind was added reads that kind as empty.

`GET /workspace` -> 200 (trial: creates one and sets the cookie when there is none or it expired)
```json
{"mode": "trial", "created": "...", "idle_expires_at": "...|null", "expires_at": "...|null",
 "uploads": [Upload], "gates": [Gate], "runs": [RunSummary], "jobs": [Job],
 "datasets": [Dataset]}
```
`Dataset` is in 3.3. `DELETE /workspace` -> 204: deletes every upload, gate, run, job and dataset
name (refuses 409 while a job runs).

### 3.2 Health and config

`GET /health` -> 200 `{"status": "ok", "mode": str, "version": str, "jobs": {"running": int, "queued": int}}`

`GET /config` -> 200
```json
{"mode": "local|trial", "version": "<app version>", "package_version": "<datanuggets-flow version>",
 "caps": Caps | null,
 "ttl": {"idle_s": 21600, "max_s": 86400} | null,
 "defaults": {"gate": {GateSettings().to_dict()}, "cluster": {ClusterSettings().to_dict() minus n_jobs},
              "cofactor_auto": {"rule": "per_channel", "floor": 150.0, "min_negative_fraction": 0.01}},
 "limits": {"k_max": 100},
 "docker_command": "docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data ghcr.io/ron2k1/datanuggets-flow:<package_version>",
 "build_command": "docker build -t datanuggets-flow https://github.com/ron2k1/datanuggetsflowcytometry.git#v<package_version>",
 "build_run_command": "docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data datanuggets-flow",
 "storage_note": "Files stay in a temporary workspace and are deleted within 24 hours. Do not upload identifiable patient data." }
```
The three commands name the running `package_version`: the published image of that version, and
a build of that version's release tag with the command that runs it. `DN_DOCKER_COMMAND`
replaces `docker_command` only. The image name and the repository are `IMAGE` and `SOURCE_REPO`
in `app/server/dnapp/core/config.py`. Local `storage_note` is `"Files stay on this computer."`. `Caps` mirrors section 4's trial caps
(same key names, lower case). `defaults.cluster` has `"method": "wkmeans"`,
`"center_method": "original"`, `"draws": "r"`, `"num_init": 10` and `"max_iter": 100`; the page
starts its Clustering and Nugget centers selects on the first two and never sends the other
three. `defaults.cluster.cofactor` is `"auto"`; `defaults.cofactor_auto`
says how auto picks, from the package's constants (`FLOW_COFACTOR_FLOOR`,
`FLOW_COFACTOR_MIN_NEGATIVE`): `rule` `"per_channel"`, one cofactor per clustered channel from
the cells the run clusters, the SD of its cells below 0 where at least `min_negative_fraction`
of them are below 0, never under `floor`, and `floor` otherwise. It needs the cells, so a
client can't preview the numbers and shows the rule instead. Until the per-channel rule this
block was `{"range_max": 262144, "narrow": 150.0, "wide": 6000.0}`, the header rule's numbers.

### 3.3 Uploads

`POST /uploads` multipart, one field `file`. An FCS file is known by its header, whatever its
name, since some instruments name theirs otherwise (a FACSCalibur's `.B08`): the file must start
with `FCS2.0`, `FCS3.0` or `FCS3.1`, else 415 `unsupported_type` ("This is not an FCS 2.0, 3.0
or 3.1 file."), and one the reader cannot parse is 422 `unreadable_file`. The name is kept, made
safe. A name the system keeps for itself, such as `NUL` on Windows, is 422 `invalid_setting`
(param `file`) and the upload is removed.
Trial: `Content-Length` required (411), size checked while streaming (413, partial file
deleted). -> 201 `Upload`:
```json
{"id": "u1", "name": "190.fcs", "kind": "fcs", "bytes": 11096133, "rows": 71106,
 "columns": [{"name": str, "label": str, "numeric": bool, "min": float|null, "max": float|null,
              "mean": float|null, "missing": int, "range": float|null}],
 "created": "...", "demo": str|null}
```
`name` is the channel's `$PnN` and `label` its `$PnS` (`""` when none). `rows` = events. Stats
over every event; `missing` is 0 (it counted a CSV's empty or non-numeric cells).
`range` is the channel's `$PnR` decoded as `pipeline.read_ranges` decodes it, not
rounded, as the header gives it; null when the header gives no usable range. The auto cofactor
no longer reads it. An FCS upload described before ranges were recorded has no `range` key;
readers treat a missing key as unknown.

`GET /uploads` -> `{"uploads": [Upload]}`. `GET /uploads/{uid}` -> Upload.
`DELETE /uploads/{uid}` -> 204 (409 when a gate uses it).

Datasets. An FCS upload's colour channels are the `$PnN` names in its `columns` that the
package's `pipeline.default_channels` clusters, compared exactly as stored: those that end in
`-A` and do not start with `FS` or `SS`, or, when there are fewer than two, every channel but
scatter and Time (flow-only-and-datasets.md part 2). Their order and the stains (`$PnS`) do not
count. A channel with no `$PnN` is named `P` and its number. The uploads whose colour channels
are the same set are one dataset, and a gate takes files from one dataset (3.4). The page groups
uploads into datasets (`shared/datasets.js`); the server keeps only the names given to them.

`POST /datasets` `{"channels": [pnn], "name": str}` -> 200 `{"datasets": [Dataset]}`, every name
in the workspace, Dataset = `{"id": "d1", "channels": [pnn], "name": str}` with `channels` sorted.
It names the channel set, matched as a set: a known set's record is renamed, a new set gets a new
record, and a name that is blank once trimmed removes the set's record (a set with no record is
left as it is). `channels` is 1 to 512 names, each non-empty, at most 100 characters and listed
once, and the list is at most 16,000 bytes as Python's `json.dumps` writes it (each character
outside ASCII escaped, 6 bytes, or 12 past U+FFFF). A channel name is otherwise kept as an upload
has it, control characters too: a `$PnN` that is not UTF-8 is read as ISO-8859-1, so a
Windows-1252 dash is U+0096. `name` is trimmed as Python's `str.strip()` trims, then at most 60
characters with no control character: Unicode `Cc`, a line or paragraph separator (U+2028,
U+2029) or a bidi control (U+061C, U+200E, U+200F, U+202A to U+202E, U+2066 to U+2069). Neither
holds a lone surrogate (U+D800 to U+DFFF), which a JSON escape can carry and UTF-8 cannot. A
workspace keeps at most 100 names: a new set's name at that cap first removes the names of the
sets no FCS upload in the workspace has, and is refused (`name`) when every name left is an
upload's set, removing none. The body is exactly `{channels, name}`: an unknown field is 422
`invalid_setting` with that field as param, and a body that is not a JSON object has param null.
Every other refusal is 422 `invalid_setting` with param `channels` or `name`. These limits hold in
both modes (`DATASET_*` in `app/server/dnapp/core/config.py`). A name may be given to a set no
upload has: it is kept and listed until the cap makes room, and the page does not show it.

### 3.4 Runs, gates and jobs

Filter JSON (used by flow runs): `{"column": str, "op": "<|<=|>|>=|==|!=|between|in", "value": number | string | [number, number] | [number|string, ...]}`.
The server builds `format_filter` strings and lets the package validate; strings containing `,`
`[` `]` are 422 `invalid_setting` param `row_filters`.

`POST /flow/gates` -> 202 `{"job": Job, "gate_id": "g1"}`
`{"uploads": ["u2","u3"], "settings": {GateSettings fields, any subset}}`
The uploads are FCS files of one dataset (3.3). Before a job is queued, each later upload, in
request order, is compared with the first, and the first whose colour channels differ is 422
`invalid_setting`, param `uploads`: "`<b>` has different colour channels from `<a>` (it `<diff>`).
A gate takes files from one dataset." `<a>` and `<b>` are the uploads' `name`s. `<diff>` is
"lacks " and the channels `a` has and `b` lacks, and/or "adds " and those `b` adds, joined by
"; " when both; each list is sorted, at most three names joined by ", ", then " and N more" when
more remain. A file with fewer than two colour channels is, like any file, in one dataset with the
files that have the same colour channels; it gates, and the cluster step refuses it in the run's
job (param `channels`).

`GET /flow/gates/{gid}` -> 200 `Gate`:
```json
{"id": "g1", "status": "queued|running|done|failed|cancelled", "created": "...",
 "settings": {GateSettings.to_dict()},
 "files": [{"number": 1, "upload": "u2", "name": "190.fcs", "n_events": int,
            "channels": [{"pnn": str, "pns": str}], "default_channels": [pnn],
            "local_maxima": int,
            "populations": [{"pop": 1, "events": int, "percent": float, "median_fsc": float,
                             "median_ssc": float, "peak": [int, int], "color": "#rrggbb"|null}]}],
 "figures": {"local_maxima": "/api/v1/flow/gates/g1/figures/local_maxima.png",
             "gates": "/api/v1/flow/gates/g1/figures/gates.png"}}
```
`files` is `[]` until done. `color` from `population_colors`. `default_channels` = every `-A`
channel but scatter (`FS`, `SS`), or every channel but those and Time when fewer than two (the package's
rule). `settings.fsc` and `settings.ssc` name the two channels the gate took, set or settled on
file 1 by the package's `gate_channels`. `GET /flow/gates/{gid}/figures/{local_maxima.png|gates.png}` -> image/png.
`DELETE /flow/gates/{gid}` -> 204 (409 while the gate's job is running, a run from it is
queued/running, or a live-cells set of it is loading; [deleting.md](deleting.md)).

`POST /flow/runs` -> 202 `{"job": Job, "run_id": "r2"}`
```json
{"gate_id": "g1", "pops": [[1], [1], [1, 2], [1]], "groups": ["ctrl","ctrl","case","case"] | null,
 "channels": [pnn] | null, "exclude_channels": [pnn], "row_filters": [Filter], "k": 8,
 "method": "wkmeans", "center_method": "original",
 "cofactor": "auto", "standardize": true, "dn_num1": 10000, "dn_num2": 1000, "seed": 291102,
 "tsne": true, "tsne_perplexity": 30, "tsne_seed": 0, "cells_per_file": 2000}
```
`pops` has one list per gate file (`[]` leaves a file out). `method` is the Cluster stage's
clustering, `"wkmeans"` (weighted k-means) or `"tree"` (the hierarchical tree), and
`center_method` where each nugget sits, `"original"` or `"mean"` (the package also takes
`"random"`); section 2 has what they do. Left out, they take `GET /config`'s
`defaults.cluster`, weighted k-means on the original points, and the run draws its nuggets
with R's draws (`draws` `"r"`). Any other value is 422 `invalid_setting` with param `method` or
`center_method`, from the package's check ("method is 'kmeans'; it takes wkmeans or tree").
`draws`, `num_init` and `max_iter` aren't request fields: the body forbids extra keys, so each
is 422 `invalid_setting` with itself as param, and a run takes the package's defaults for them.
The manifest's `settings` and run.json's `settings` keep all five. Too few nuggets in use for
weighted k-means at k fails the job, not the request (section 2), since the count is known
only once the files' nuggets are built. `cofactor` is the Transform stage:
`"auto"` (the default: one cofactor per clustered channel, section 2's rule over the cells the
run clusters) or a number from 0 (0 = linear), used as set for every channel; anything else
(another string, a negative or non-finite number, a list) is 422 `invalid_setting` with param
`cofactor`. The manifest's `settings.cofactor` keeps what was sent (`"auto"` or the number); the
cofactors used and how they were chosen are in `record.transform`.
`standardize` is the Scale stage: true or false only, anything else is 422
`invalid_setting` with param `standardize`; left out it takes `GET /config`'s
`defaults.cluster.standardize`, true. The worker runs
`state.load_gates` -> `state.check_new` -> `state.begin` -> copy the gate PNGs ->
`pipeline.cluster_stage` -> `state.write_run` -> `state.finish`. `n_jobs` is server-set.
Before a job is queued, the done gate's uploads are compared as `POST /flow/gates` compares them,
since a gate made before that check, which a local workspace keeps, can mix datasets: such a gate
is 422 `invalid_setting`, param `gate_id`, "`<b>` has different colour channels from `<a>` (it
`<diff>`). A run takes files from one dataset."

Job:
```json
{"id": "j1", "kind": "gate|flow", "status": "queued|running|done|failed|cancelled",
 "progress": 0.0, "stage": str|null, "message": str|null, "log_tail": [str],
 "created": "...", "started": "...|null", "finished": "...|null",
 "run_id": str|null, "gate_id": str|null,
 "error": {"code": "invalid_setting|unreadable_file|timeout|cancelled|out_of_memory|internal",
           "message": str, "param": str|null} | null}
```
`progress` in [0, 1], never decreasing, 1.0 only when done. `log_tail` = last 50 log lines
(scrubbed). `GET /jobs` -> `{"jobs": [Job]}`; `GET /jobs/{jid}` -> Job;
`POST /jobs/{jid}/cancel` -> 202 Job (queued: removed at once; running: cooperative, the worker
checks `jobs/<jid>.cancel` at every StageEvent/step and stops, its partial outputs deleted).
A running job whose worker reaches its end before the next check ends as the worker left it, a
done one with its outputs, although its cancel answered 202 with status `running`.
A job that has already ended (done, failed or cancelled) is left as it is: 200 Job, its record
and a done job's outputs unchanged. A client's job list is a poll behind, so its cancel can
arrive after the job ended; that is not an error.

`GET /runs` -> `{"runs": [RunSummary]}`;
RunSummary = `{"id", "kind": "flow", "status", "created", "title": str, "source": "g1", "k": int|null}`.

`GET /runs/{rid}` -> manifest:
```json
{"id": "r2", "kind": "flow", "status": "done", "created": "...", "title": str,
 "settings": {...as sent, defaults filled},
 "record": {run.json, scrubbed},
 "k": 8,
 "clusters": [{"cluster": 1, "parent": 1, "color": "#1f77b4"}],
 "files": [{"name": "cluster_summary.csv", "bytes": int, "kind": "csv|png|json|txt"}],
 "warnings": [str]}
```
`record.clustering` is run.json's clustering block (section 2). The page's run record shows it
as a Clustering section (the clustering and k, with the k asked when the k used differs, the
nugget centers, the nuggets clustered and dropped, the total WWCSS, and the two R calls), and
the plot's inspector shows the clustering and the nugget centers from `settings`. A run whose
`settings` name no `method` was made before the app sent it and clustered with the hierarchical
tree on mean centers; the page reads it so (`shared/clustering.js` `clusteringOf`), and "Use
rX's choice" copies those two choices into the cluster form with the run's populations.
`DELETE /runs/{rid}` -> 204 (409 while running).

A local workspace from before the flow-only amendment (section 9) can still hold CSV uploads,
general runs and general jobs. `GET /workspace`, `/uploads`, `/runs` and `/jobs` still list them,
with kind `csv` or `general`, and a run's files still download (3.6). `DELETE /uploads/{uid}`
and `DELETE /runs/{rid}` still remove the uploads and runs; no route deletes a job, so their
general jobs stay in `GET /jobs` and `/workspace` until `DELETE /workspace`. `GET /runs/{rid}`,
`/runs/{rid}/plot`, `/runs/{rid}/cells` and `/runs/{rid}/compare` answer 409 `wrong_state` for a
run whose kind is not `flow`.

### 3.5 Plot, cells and comparison payloads

API cluster numbers are always from 1.

`GET /runs/{rid}/plot` -> 200
```json
{"run_id": "r2", "kind": "flow", "method": null,
 "columns": [str], "short_columns": [str],
 "transform": [{"name": "arcsinh", "cofactor_from": "auto", "cofactors": [float], ...},
               {"name": "scale", "mean": [float], "sd": [float]}],
 "k": 8,
 "clusters": [{"cluster": 1, "parent": 1, "color": "#1f77b4"}],
 "nuggets": {"n": int, "nugget0": [int], "file": [int], "weight": [float],
             "cluster": [int], "centers": [[float]]},
 "pca": {"components": ["PC1", ...], "scores": [[float]], "variance": [float],
         "loadings": [[float]], "center": [float], "scale": [float] | null} | null,
 "tsne": {"d2": [[float, float]], "d3": [[float, float, float]] | null} | null,
 "files": [{"number": 1, "name": "190.fcs", "group": str|null}],
 "groups": [str] | null,
 "warnings": [str]}
```
Nuggets in use only (weight > 0), in pooled file order; `weight` is the nugget's count of cells,
exact. `method` is always null: it named a
general run's clustering, and stays so the key set is unchanged. `columns` = the CSV column
labels (`"CD38 (FJComp-APC-Cy5.5-A)"`); `short_columns` = text before `" ("`. `pca.scores`
n x q and `loadings` p x q with q = min(5, p); `variance` is the ratio (0..1) of those q.
`transform` = run.json's `transform` as `state.run_transform` reads it, unrounded, one of
section 2's shapes: auto's `{"name":"arcsinh","cofactor_from":"auto","cofactors":[c_j],
"negative_fraction":[f_j],"negative_sd":[sd_j|null],"floor":150.0,"min_negative_fraction":0.01}`
with channel j's cofactor at `columns[j]`, a set `{"name":"arcsinh","cofactor":c,
"cofactor_from":"set"}`, or the earlier header rule's `{"name":"arcsinh","cofactor":c,
"cofactor_from":"auto","range":r}` (`range` null when a header gave none); nothing with
cofactor 0; a run.json from before `cofactor_from` reads as set, and one from before the stage
takes its settings' cofactor. It is followed by
`{"name":"scale","mean":[float],"sd":[float]}` when run.json's `standardize` is a record. `centers`
are in the Transform stage's units, since the CSVs undo the Scale stage, and so is `pca.center`.
The `scale` entry says the nuggets were clustered on scaled values; the viewer does not convert
by it. `pca.scale` is pca_center.csv's `scale` (null without
it), so a row x in the centers' units scores `((x - center) / scale) @ loadings`.
`tsne.d2` and `tsne.d3` are tsne.csv and tsne3d.csv in the nuggets' order (matched on the key
columns); `d3` is null for a run without tsne3d.csv (one made before it, or of fewer than 3
columns or nuggets), which the viewer then plots without a 3-D t-SNE.

`GET /runs/{rid}/cells` -> 200
```json
{"run_id": "r2", "n": int, "cap_per_file": int, "columns": [str],
 "file": [int], "row0": [int], "nugget0": [int], "cluster": [int],
 "pca": [[float]] | null, "values": [[float]]}
```
From cells.csv (`event0` -> `row0`). Server caps total cells at `CELLS_MAX_TOTAL`.

`GET /runs/{rid}/compare` -> 200
```json
{"run_id": "r2", "k": 8, "clusters": [{"cluster", "parent", "color"}],
 "files": [{"number": 1, "name": "190.fcs", "group": str|null, "cells": int}],
 "counts": [[int]], "percent": [[float]],
 "groups": [str] | null, "group_files": [int] | null, "reference": str | null,
 "log2fc_pseudocount": float | null,
 "group_summary": [{"group", "cluster", "samples", "mean_percent", "sd_percent", "min_percent",
                    "max_percent", "diff_vs_ref", "log2fc_vs_ref"}] | null,
 "channels": [str],
 "cluster_markers": [{"file_number", "cluster", "cells", "means": [float|null]}],
 "group_markers": [{"group", "cluster", "channel", "samples", "mean", "diff_vs_ref"}] | null}
```
`counts`/`percent` rows follow `files` (kept files), columns clusters 1..k, from
cluster_summary.csv. `means` follow `channels` (labels). `group_markers.channel` = label.

- `groups`: every group of the run (all gated files, not only kept ones), in first appearance by
  file number, which is group_summary.csv's order; null for a run without groups. A group whose
  files were all left out (no population chosen) is listed, and group_summary.csv has its rows
  with `samples` 0 and null means.
- `group_files`: the kept files in each group, aligned with `groups`; 0 marks a group with no
  kept file. null with `groups`.
- `reference`: the group of the first kept file (lowest file number), as the package picks it.
  It need not be `groups[0]`.
- Group names are the text the run was given: the server reads the group, file and label
  columns of groups.csv, group_summary.csv and group_markers.csv as text (only an empty cell is
  missing), so names such as `None`, `NA`, `nan`, `01` and `1` stay distinct and unchanged.
- `log2fc_pseudocount`: group_summary.csv's `log2fc_pseudocount` column (the same value on every
  row), in percentage points, to `SIG_DIGITS`; null when the file or the column is missing (a run
  from before the package wrote it). The package sets it to half a cell per file: the mean over
  the kept files of 50 / (that file's cells), and log2fc_vs_ref = log2((mean_percent + pc) /
  (reference mean + pc)). The server never computes it. The page shows the raw mean and sd next
  to log2FC with the note "log2FC adds half a cell per file (<pc> percentage points) to every
  group. Descriptive only: no significance test.", and leaves the number out when the field is
  null. The group comparison is a phase-2 design choice with no basis in the paper or the R
  code, and the docs and the page call it descriptive.
- `pseudocount` (a fixed 0.5 from the package's defaults) is gone; `log2fc_pseudocount`
  replaces it.

### 3.6 Downloads and demos

`GET /runs/{rid}/files/{name}` -> the file (`Content-Disposition: attachment`), only names in the
manifest's `files` (404 otherwise; no path separators). CSV cells starting with `= + - @ \t \r`
are prefixed with `'` on the way out, except a cell that reads as a float, finite or not (`-1.5`,
`-inf`, `-Infinity`, `-nan` keep their text; `-1+1` and `=cmd` are prefixed).
`GET /runs/{rid}/download.zip` -> every manifest file.

`GET /demos` -> `{"demos": [{"id", "title", "kind", "files": [{"name", "bytes"}], "license",
"license_url", "source_url", "attribution", "rows", "description", "available": bool}]}` from
`app/demo/manifest.json` (`available` false when a file is missing on disk). The demo card shows
the license, linked to `license_url` when there is one, the source link and the `attribution`
text as the manifest has them.
`POST /demos/{id}/load` -> 201 `{"uploads": [Upload]}` (copies into the workspace; demo bytes do
not count against the trial upload cap; `Upload.demo` = demo id).

### 3.7 Headers

Every response: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. HTML responses:
`Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`.
No `'unsafe-eval'` and no inline scripts anywhere. No CORS middleware (same origin).

Host check, before any route: local mode answers only the Host names `localhost`, `127.0.0.1`
and `[::1]`, with or without a port, plus the names `DN_ALLOWED_HOSTS` lists. Any other Host gets
400 `invalid_host`, so a page on another site that points its own name at this computer (DNS
rebinding) cannot reach the API, which has no login in local mode. Trial mode answers any Host
until `DN_ALLOWED_HOSTS` lists a name, and then it answers those and the loopback names. `*` in
the list answers any name in either mode. Names compare in lower case, ports are ignored, and an
IPv6 address keeps its brackets (`[::1]:8000` is `[::1]`). An entry that is not a host name stops
the server at start.

## 4. MODE config (`app/server/dnapp/config.py`, one frozen dataclass `Settings.from_env()`)

| Env | Default | Meaning |
|---|---|---|
| `DN_MODE` | `local` | `local` or `trial` |
| `DN_DATA_DIR` | `<repo>/tmp/appdata` outside Docker; `/data` in the image | workspaces and job files |
| `DN_WEB_DIR` | `<repo>/app/web`; `/app/app/web` in the image | static page |
| `DN_DEMO_DIR` | `<repo>/app/demo`; `/app/app/demo` in the image | demo manifest and data |
| `HOST` | `127.0.0.1`; image sets `0.0.0.0` | bind address |
| `PORT` | `8000` | bind port |
| `DN_WORKERS` | trial 1, local min(2, cpu count) | ProcessPoolExecutor(spawn) size |
| `DN_JOBS` | trial 1, local -1 | create_dn n_jobs / CLI --jobs |
| `DN_COOKIE_SECURE` | `0` | `Secure` cookie flag |
| `DN_TRUST_PROXY` | `0` | `1`: client IP from `X-Real-IP` |
| `DN_DOCKER_COMMAND` | `docker_command` in 3.2 | the run command "Run it locally" shows |
| `DN_ALLOWED_HOSTS` | empty | comma-separated Host names the app answers besides the loopback ones (3.7), or `*` for any |

Trial caps (constants in config.py; local: none, except k <= 100 and the cells bounds below):

| Name | Value |
|---|---|
| `UPLOAD_FCS_BYTES` | 200 MB |
| `WORKSPACE_BYTES` | 1 GB |
| `FCS_EVENTS` | 3,000,000 per file |
| `FCS_FILES_PER_GATE` | 8 |
| `K_MAX` | 100 (both modes) |
| `DN_NUM1_MAX` / `DN_NUM2_MAX` | 10,000 / 2,000 |
| `POOLED_NUGGETS_MAX` | 8,000 (kept files x dn_num2) |
| `CELLS_PER_FILE_MAX` / `CELLS_MAX_TOTAL` | 2,000 / 50,000 (local: 5,000 / 200,000) |
| `RUNS_PER_WORKSPACE` | 10 |
| `JOBS_PENDING_PER_IP` | 2 (queued + running) |
| `JOBS_PER_IP_HOUR` | 20 |
| `WORKSPACES_PER_IP_HOUR` | 5 |
| `HEAVY_BUDGET_S_PER_DAY` | 14,400 (sum of job run seconds across all IPs, UTC day) |
| `JOB_TIMEOUT_S` | 900 (local: none) |
| `QUEUE_MAX` | 8 |
| `TTL_IDLE_S` / `TTL_MAX_S` | 21,600 / 86,400 |
| `SWEEP_S` | 600 |
| `MIN_FREE_BYTES` | 1 GB (507 below) |

Uvicorn: `python -m dnapp` runs `uvicorn.run(create_app(), host=HOST, port=PORT, workers=1)`.
Dev ports: server 8811, web fixture server 8812, integration 8810.

## 5. `app/demo/manifest.json`

```json
{"schema": "datanuggets-demos/1",
 "demos": [{"id": "pbmc", "title": "PBMC spectral flow, 4 samples", "kind": "fcs",
            "files": [{"name": "190.fcs", "path": "data/190.fcs", "bytes": 11096133, "sha256": "<hex>",
                       "url": "https://zenodo.org/records/22079206/files/190.fcs?download=1"}, ...],
            "license": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "source_url": "https://doi.org/10.5281/zenodo.22079206",
            "attribution": "Stefanie Kreutmair and Susanne Unger (2026). ...",
            "rows": 193293, "description": "4 PBMC samples from ICU patients, ...",
            "suggested": {"pops": [[1], [1], [1, 2], [1]], "groups": ["A", "A", "B", "B"], "k": 8,
                          "cofactor": 6000}}]}
```
`kind` is `fcs`; `path` is relative to `app/demo/`; `url` set means the file is fetched
at image build by `app/scripts/fetch_demos.py` (sha256-checked; mismatch fails the build) and not
committed; `rows` = total events. Demos: PBMC flow (Zenodo 22079206, CC BY 4.0, 4 FCS files
190/193/199/223, fetched; sha256 in notes). `suggested` (flow `pops`, `groups`, `k`,
`cofactor`) stays in the manifest: `GET /demos` does not send it, and neither the page, the
fixture builder nor `smoke.py` reads it.

## 6. Frontend fixture mode (web builder)

- `app/web/fixtures/` holds JSON files whose bodies are exactly API responses. Name = method +
  path after `/api/v1/` with `/` -> `__`, query dropped, `.json`:
  `GET__config.json`, `GET__workspace.json`, `GET__runs__r3__plot.json`, `POST__flow__runs.json`.
  PNGs as `fixtures/png/<name>.png`, referenced by the fixture Gate's `figures` URLs.
- `?fixtures=1` (or `localStorage["dn-fixtures"] = "1"`) makes `js/api.js` read fixtures instead of
  the network; a missing fixture shows the error shape `{"error": {"code": "not_found", ...}}`.
  `?fixtures=1&mode=local` swaps `GET__config.json` for `GET__config.local.json`.
- Fixture numbers come from real datanuggets runs on public data (mock-up `out/` folders and the
  4 Zenodo FCS files), built by `app/web/tools/build_fixtures.py` (run with the
  app's environment and `src` and `app/server` on `PYTHONPATH`, since it uses the server's own
  flow worker and readers). Never hand-typed numbers. Group names are labels the builder assigns
  to real files. The flow run r3's run.json predates the recorded Transform stage (it reads as
  cofactor 6000, set); r7 is a flow run the builder makes with the server's worker on the same
  gate and pops with cofactor auto, so its run.json has the per-channel transform (150 on 25 of
  the 32 channels; on the gated cells CD38 293, CD123 196, CD8 310, ACE2 208, CCR6 196, CD19 190
  and CD14 352), 250 nuggets and 500 cells per file to keep the fixtures small. Its job is j10;
  r6 and j7 to j9 stay the ids the POST fixtures hand back. Both runs were built before the
  Cluster stage was recorded: their settings name no `method` and their run.json has no
  `clustering` block, so the page reads them as the hierarchical tree on mean centers, which is
  how they ran (each has its `dendrogram.png`). A full rebuild makes r7 with the current
  defaults, weighted k-means on the original points, and r3 stays as it ran. The `/config`
  fixtures have section 3.2's `defaults.cluster`, method and draws included. The ids keep the gaps the general
  fixtures left (section 9): uploads u3 to u6 (`POST__uploads.json` is u3, 190.fcs), runs r3 and
  r7, jobs j1, j4 and j7 to j10.
- No fixture dataset has a name: `GET__workspace.json` and `GET__workspace.local.json` list
  `"datasets": []`, and there is no `POST__datasets.json`. In fixture mode the transport keeps the
  names given in the tab, as it keeps uploads read in the tab.
- No fixture answers a DELETE. `DELETE /uploads/{uid}` of a file read in the tab forgets it in the
  tab; any other DELETE shows the missing-fixture error ([deleting.md](deleting.md)).
- Fixture server: `uv run python -m http.server 8812 --bind 127.0.0.1 -d app/web`.

## 7. Web behaviour pinned here

- Theme: light "paper" is the initial theme whatever the OS says; the toggle switches light/dark;
  the choice persists in `localStorage["dn-theme"]` (`"light"|"dark"`, try/catch). No
  `prefers-color-scheme` default.
- Copy: trial `"Files stay in a temporary workspace and are deleted within 24 hours. Do not upload identifiable patient data."`;
  local `"Files stay on this computer."`; both read from `/config.storage_note`. A "Run it locally"
  entry shows `docker_command`, then `build_command` and `build_run_command` as the build from
  source, each with a copy button. No "account" wording.
- Colours always come from the payload's `clusters[].color`; nothing cycles a palette.

## 8. Acceptance criteria

### Package (P)
- P1 `cluster_colors(k)` for k = 1..8 equals `TAB10[:k]`; for every k in 9..100, with
  `block_parents(k)` and with `tree_parents` of a Whclust tree of real nuggets (tests/fixtures/flow
  202 events), the k strings are distinct lowercase `#rrggbb`.
- P2 `tree_parents`: each child's members all share one parent label; k <= 8 gives `range(k)`.
- P3 `population_colors` equals the colours `plot.gates` draws (read back from the Line2D artists).
- P4 Existing figure tests stay byte-identical.
- P5 `parse_filter` / `format_filter` round-trip for every op, bracketed names, numbers and
  strings; bad specs raise ValueError naming the problem.
- P6 `filter_mask` on iris: `species == setosa` keeps 50 rows; `petal_length between 1,1.5`
  matches a direct numpy count.
- P7 (general CLI, not part of this repository) `--filter ... --cells 100 --analysis kmeans hclust pca tsne` on iris
  writes cluster_colors.csv, tsne.csv, cells.csv with the pinned columns; `row0` maps to the
  original records; run.json has `row_filters`, `input_row_count`, `cells_sampled`.
- P8 `run_analysis` equals the CLI's outputs byte for byte (except timestamps in run.json).
- P9 `project(centers, view)` equals `view.scores` (1e-9 relative); flow
  `pca_scores.csv` equals the scores drawn in clusters_pca.png (`gid="scores"` offsets).
- P10 `cluster_markers.csv` equals direct per-file per-cluster cell means (1e-9 relative) on a
  real-event flow run; cells counts sum to the cluster_summary cells.
- P11 `group_summary.csv` / `group_markers.csv` values recomputed from cluster_summary.csv /
  cluster_markers.csv in a test match; reference rows have diff 0 and log2fc 0.
- P12 Flow `--filter` reduces kept cells by exactly the mask count; `selection.csv` gains
  `filtered`, `filtered_percent` only with filters.
- P13 `--groups` with the wrong count, an empty or invalid name raises FlowError param `groups`.
- P14 `cells.csv`: per file min(cells_per_file, kept) rows, sorted event0, cluster equals
  events_N.csv's cluster for those events, PCs equal `project` of the values.
- P15 On 202.fcs's Pop 1, the tree cut into k = 100 of 400 nuggets per file runs; a k above the
  nuggets in use clamps as before and the cluster event reports the k used. Weighted k-means has
  no clamp: k = 50 of 400 nuggets is made exactly, and k = 100 of the same 400, where every random
  start leaves a cluster empty, stops with a FlowError of param `k` once the package's 1,000
  draws are spent. Neither run hangs or clusters with a smaller k than asked.
- P16 `ruff check` clean on changed files; docs/cli.md and docs/api.md describe the new flags and
  functions.

### Server (S)
- S1 `uv sync --project app` then `uv run --project app python -m dnapp` serves `/` (index.html)
  and `/api/v1/health` on 127.0.0.1:8811 (PORT=8811).
- S2 Every endpoint in section 3 exists with the pinned shapes; a test per endpoint asserts the
  key sets, including error shape and status codes listed.
- S3 Trial cookie: created on `GET /workspace`, HttpOnly + SameSite=Strict, unknown cookie -> new
  workspace, expired -> 410 + cleared cookie (clock injected in tests).
- S4 Trial caps each return their status and code (413, 411, 415, 422 param, 429 with
  Retry-After, 503, 507) in tests; local mode accepts the same requests.
- S5 Jobs run in a spawn ProcessPoolExecutor; the event loop answers `/health` within 200 ms while a
  flow job runs (test).
- S6 End to end on real public data in tests, on real flow events:
  `tests/fixtures/flow/202.npz` + `202_fluor.npz` (FSC-A, SSC-A and 3 fluorescence
  channels, 50,000 real events) written to a temporary FCS with `flowio.create_fcs`, uploaded
  twice as two samples -> gate -> flow run with groups -> plot, cells, compare payloads; numbers
  equal the run's CSVs.
- S7 Cancel: queued job removed; running job stops at the next stage, status `cancelled`, outputs
  gone. Cancelling a job that has already ended gives 200 and changes nothing: a done run still
  loads and plots.
- S8 Job JSON files survive a restart in local mode (jobs that were running become `failed`
  with code `internal`, message "The server restarted during this job.").
- S9 No absolute path in any response body (test greps for DATA_DIR in every payload).
- S10 Downloads: allow-list enforced, `../` refused, CSV injection prefix applied, zip holds every
  manifest file.
- S11 CSP header exactly as pinned on `/`; `nosniff` on all.
- S12 The server never imports matplotlib.pyplot in the main process and never reimplements
  package math (payloads read the run's CSVs).

### Web (W)
- W1 `app/web` loads with no build step; only ES modules from `app/web/js/`; Plotly from
  `vendor/plotly-3.0.1-strict.min.js` whose sha384 is
  `7MNE81UJ6IGFHgMnhm0R2flmfujIE65CunV+chyM1Q84nhCC0S5PvTcX2PDrcYDZ`; no inline scripts, no eval,
  no network but same origin; works offline.
- W2 `?fixtures=1` renders every screen from fixtures with zero console errors at 1440 and 390 px.
- W3 Light theme on first load with OS in dark mode; toggle to dark persists across reload.
- W4 Upload screen: FCS upload (`.fcs` only) with each channel's stats; demos list with "Load".
- W5 Gate screen: local_maxima/gates PNGs, populations per file with their colours, pops picker,
  group name per file.
- W6 Run form: flow settings with defaults from `/config`, row filters (column, op, value(s)) and
  channel checkboxes; k slider 2..100.
- W7 Jobs: progress bar 0..1, log tail, cancel.
- W8 Nuggets view: solid opaque markers, no outlines, colour = cluster colour from the payload,
  size by weight on by default, the diameter following ln(1 + w) / ln(1 + wmax) with a size key
  ([cluster-panel.md](cluster-panel.md)); a Point size control scales every marker from 0.5x to
  3x; 100 clusters each get their own legend entry with the payload colour. Clicking a point opens
  the point card: each marker's value as plotted and back in the file's units, c x sinh(v). The
  card, or Open box plots under the plot, opens the run's box plots tab on a cluster.
- W9 Cells view (R3): sampled events, opaque, no outlines, same colours; toggle Nuggets/Cells.
- W10 Exact views (R4): axis picker (any 3 of PC1..PC5 or variables) with an animated transition;
  parallel coordinates across all dims coloured by cluster; variance explained shown on PC axis
  labels.
  No colour = PC4 and no size = PC5 encodings remain.
- W11 Compare screen (R2): sample x cluster counts and percents table + stacked bars per sample;
  group summary (mean, sd, diff, log2fc vs reference) and per-cluster marker means by group.
- W12 Storage copy and "Run it locally" from `/config` (R9); no "account" text anywhere.
- W13 The unfixed findings in the v3 review (F1..) that touch carried-over code are fixed.

### Docker (D)
- D1 One `Dockerfile` (python:3.12-slim, non-root user, `uv sync --project app --locked --no-dev`),
  `ENV HOST=0.0.0.0 PORT=8000 DN_DATA_DIR=/data DN_MODE=local`, `EXPOSE 8000`, `VOLUME /data`,
  `HEALTHCHECK` on `/api/v1/health`, `CMD ["python", "-m", "dnapp"]` from the app venv.
- D2 `.dockerignore` is an allowlist. It lets in only the paths the `Dockerfile` copies, and inside
  them keeps out `app/web/fixtures`, `app/web/tools`, tests, caches and data files. A build from a
  git URL gets no `.dockerignore`, so the `Dockerfile`'s runtime stage copies the page by name and
  the server without its tests, and leaves the same paths out on its own.
- D3 `compose.yaml`: service `app`, port 8000, named volume `datanuggets-data:/data`, `DN_MODE`
  overridable.
- D4 `.github/workflows/app.yml` runs on pull_request, on push to `main`, on manual dispatch and inside every
  release before the upload to an index. It builds the image natively on amd64 and on arm64
  (both blocking) and runs it in `local` and in `trial` mode. `app/scripts/smoke.py` checks
  health, config (mode, caps null or not), the `/` CSP, loading the PBMC demo, a gate and a flow
  run to done, and the run's plot payload, files and zip. It also runs the app tests from `app/`
  with `-n 2`, so both testpaths run. It pushes nothing.
  Actions are pinned by SHA like the other workflows, with `permissions: contents: read`.
- D4b `.github/workflows/image.yml` publishes a release to `ghcr.io/ron2k1/datanuggets-flow` from a
  tag `v<version>` on `main`. `release.yml` calls it after the PyPI upload. It pushes the build
  by digest, smoke-tests that digest on both architectures and only then tags it.
  `.github/dependabot.yml` proposes new base image digests and action SHAs weekly.
- D5 `app/demo/manifest.json` per section 5 with real sha256 values; `fetch_demos.py` verifies
  them and refuses a mismatch; the demo data under `app/demo/data/` is fetched and gitignored,
  never committed.
- D6 `docs/app/running-locally.md`: build, run, volume, MODE, ports, how data stays on disk.

### Integration (I)
- I1 Every fixture in `app/web/fixtures` has the same key set as the live server's response on
  127.0.0.1:8810 for the same request (script compares).
- I2 Browser pass on the live server: upload FCS files -> gate -> pops -> flow run -> plot
  (nuggets + cells + exact views); load PBMC demo -> gate -> pick pops + groups -> flow run
  k = 20 -> compare screen.

## 9. Amendments

- [contract-livecells.md](contract-livecells.md) adds the Live cells step between Populations and
  Cluster on the flow path: the package module `datanuggets_flow.livecells` (built), a job kind
  `"livecells"`, four routes under `/flow/gates/{gid}/livecells` and `LIVECELLS_*` caps (server),
  the web step and its five fixtures, and criteria P17-P21, S13-S17, W14-W19 and I3. It extends
  this file where it speaks: the Job `kind` list gains `"livecells"` and the id counters gain
  `l1`. Where it is silent, this file holds.
- [flow-only-and-datasets.md](flow-only-and-datasets.md), part 1, makes the app a flow cytometry
  app. General mode leaves the server, the page, the demos and the fixtures: `POST /runs/general`,
  CSV upload with `GET /uploads/{uid}/rows`, the general branches of runs, plot and cells, the
  iris and California housing demos with their CSVs, and the AIS set in `app/demo/large.json`
  (nkg2a stays). `POST /runs/general` and `GET /uploads/{uid}/rows` answer 404 `not_found`, and a
  CSV upload is refused like any other file that isn't FCS: 415 `unsupported_type`, "This is not
  an FCS 2.0, 3.0 or 3.1 file." The Upload JSON loses `preview`, the run manifest loses `methods`, and
  `/runs/{rid}/plot` and `/cells` lose the `method` query parameter (FastAPI ignores it if sent).
  `/config` loses `defaults.general` and the caps `upload_csv_bytes`, `csv_rows`, `csv_columns`,
  `general_nuggets_max` and `general_intermediate_max`. A local workspace from before can still
  hold CSV uploads, general runs and general jobs: they are still listed, `DELETE` still removes
  the uploads and runs, their general jobs stay in `GET /jobs` and `/workspace` until
  `DELETE /workspace`, and a run's files still download, but `GET /runs/{rid}`, `/plot` and
  `/cells` answer 409 `wrong_state` for a run whose kind is not `flow`, as `/compare` already did.
  The fixtures lose the general runs r1, r2 and r4, the CSV uploads u1 and u2, the general jobs
  j2, j3, j5 and j6, the iris and housing demo loads and `POST__runs__general.json`; the ids that
  stay keep their gaps, so no flow fixture and no document that names one changes. Sections 1, 3
  to 6 and 8 are edited in place to match, with S6, W4, W6, D4 and I2 restated for the flow path.
  Section 2.4 and P5 to P8 described the general CLI, which isn't part of this repository.
- [flow-only-and-datasets.md](flow-only-and-datasets.md), part 2, groups a workspace's FCS uploads
  into datasets by their colour channels (3.3). `POST /flow/gates` refuses uploads of two datasets
  before a job is queued: 422 `invalid_setting`, param `uploads`, with the message in 3.4.
  `POST /flow/runs` refuses a gate whose uploads mix datasets, as one made before that check can:
  422 `invalid_setting`, param `gate_id`, the same message ending "A run takes files from one
  dataset." So a run has files of one dataset. Before, such a mix failed later as a gate or run
  job error, or ran when every file had file 1's channels. The server keeps the names given
  to datasets: `POST /datasets`, a `datasets` kind in `meta.json` with ids `d1`, `d2`, ..., and
  `"datasets": [Dataset]` in `GET /workspace`, which `DELETE /workspace` empties. The page groups
  the uploads; the workspace fixtures list `"datasets": []`. Sections 3 and 6 are edited in place
  to match; I1 holds as it stands, since the fixtures carry the new key.
