"""The tables a datanuggets-flow run writes for a viewer (flow.outputs and flow.compare), on real
events: 202.fcs read as three files a.fcs, b.fcs and c.fcs that keep different populations, so
each file's cells differ. Every value is checked against the cells themselves or the run's own
tables, recomputed here. The module run sets the cofactor 6000, so its values are recomputed with
it; the other runs take the auto cofactors."""

import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from datanuggets.colors import TAB10, block_parents, cluster_colors, tree_parents
from datanuggets.filters import filter_mask, parse_filter
from datanuggets.projection import tsne_3d

from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.figures import result_figures
from datanuggets_flow.outputs import pool_colors
from datanuggets_flow.pipeline import cluster_stage, gate_files, parse_groups
from datanuggets_flow.settings import ClusterSettings, GateSettings, cli_flag
from exactcsv import read_exact
from flowcases import LABELS, read_202

CHANNELS = ["FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"]
NAMES = ("a.fcs", "b.fcs", "c.fcs")
CHOSEN = [[1], [6], [3]]  # 39,860, 2,292 and 13,308 cells
GROUPS = ("ctrl", "ctrl", "treated")
COFACTOR = 6000.0  # the module run's, given, as its values are recomputed with it


def _csv(folder, name):
    return read_exact(folder / name)


@pytest.fixture(scope="module")
def gated():
    return gate_files([Path(n) for n in NAMES], GateSettings(), read=read_202)


@pytest.fixture(scope="module")
def run(gated, tmp_path_factory):
    out = tmp_path_factory.mktemp("viewer")
    events = []
    settings = ClusterSettings(
        dn_num2=60, k=5, n_jobs=1, groups=GROUPS, cells_per_file=500, cofactor=COFACTOR
    )
    result = cluster_stage(gated, CHOSEN, out, settings, read=read_202, on_event=events.append)
    return out, result, events, settings


def _cells_of(result, number):
    """The kept cells of file number after the Transform stage, as make_nuggets read them."""
    events, _, _ = read_202(None)
    kp = next(k for k in result.kept if k.number == number)
    return kp, np.arcsinh(events[np.ix_(kp.rows, [2, 3, 4])] / COFACTOR)


def test_files_are_written_after_the_tables_and_before_the_figures(run):
    out, result, events, _ = run
    names = [p.name for p in result.files]
    viewer = [
        "cluster_colors.csv",
        "cluster_markers.csv",
        "pca_scores.csv",
        "pca_loadings.csv",
        "pca_variance.csv",
        "pca_center.csv",
        "tsne.csv",
        "tsne3d.csv",
        "cells.csv",
        "groups.csv",
        "group_summary.csv",
        "group_markers.csv",
    ]
    start = names.index("cluster_centers.csv") + 1
    assert names[start : start + len(viewer)] == viewer
    # weighted k-means, the default, has no tree, so the PCA is the first figure
    assert names[start + len(viewer)] == "clusters_pca.png"
    assert "dendrogram.png" not in names
    assert sorted(names) == sorted(p.name for p in out.iterdir())
    cluster = next(e for e in events if e.stage == "cluster")
    assert cluster.data["k"] == result.pool.k == 5


def test_cluster_colors_name_each_cluster_and_its_family(run):
    out, _, _, _ = run
    colors = pd.read_csv(out / "cluster_colors.csv")
    assert list(colors.columns) == ["cluster", "parent", "color"]
    assert colors["cluster"].tolist() == [1, 2, 3, 4, 5]
    assert colors["parent"].tolist() == [1, 2, 3, 4, 5]
    assert colors["color"].tolist() == list(TAB10[:5])


def test_pca_scores_are_the_points_clusters_pca_draws(run, close_figures):
    """P9: pca_scores.csv holds the nuggets in use in pooled order, on the signs the figure
    draws them with."""
    out, result, _, settings = run
    pool = result.pool
    scores = _csv(out, "pca_scores.csv")
    assert list(scores.columns) == ["file_number", "nugget0", "PC1", "PC2", "PC3"]
    files = np.concatenate([np.full(k.dn.n_nuggets, k.number) for k in result.kept])
    rows = np.concatenate([np.arange(k.dn.n_nuggets) for k in result.kept])
    assert scores["file_number"].tolist() == files[pool.use].tolist()
    assert scores["nugget0"].tolist() == rows[pool.use].tolist()
    figs = result_figures(
        pool, result.tables.centers, LABELS, settings.cofactor, None, colors=pool_colors(pool)
    )
    ax = figs["clusters_pca.png"].axes[0]
    (drawn,) = [c for c in ax.collections if c.get_gid() == "scores"]
    np.testing.assert_allclose(scores[["PC1", "PC2"]].to_numpy(), drawn.get_offsets(), rtol=1e-12)
    loadings = _csv(out, "pca_loadings.csv")
    assert loadings["channel"].tolist() == CHANNELS and loadings["label"].tolist() == LABELS
    center = _csv(out, "pca_center.csv")
    c, scale = center["center"].to_numpy(), center["scale"].to_numpy()
    centers = pool.scaling.undo(pool.centers[pool.use])  # in arcsinh units, as the tables give
    rotation = loadings[["PC1", "PC2", "PC3"]].to_numpy()
    np.testing.assert_allclose(
        ((centers - c) / scale) @ rotation, scores[["PC1", "PC2", "PC3"]].to_numpy(), rtol=1e-9
    )
    variance = _csv(out, "pca_variance.csv")
    assert variance["component"].tolist() == ["PC1", "PC2", "PC3"]
    assert variance["variance_ratio"].sum() == pytest.approx(1.0)


def test_tsne_csv_is_the_array_clusters_tsne_draws(run):
    out, result, _, _ = run
    tsne = _csv(out, "tsne.csv")
    assert list(tsne.columns) == ["file_number", "nugget0", "tsne1", "tsne2"]
    assert np.array_equal(tsne[["tsne1", "tsne2"]].to_numpy(), result.tsne.astype(float))
    scores = _csv(out, "pca_scores.csv")
    assert tsne["nugget0"].tolist() == scores["nugget0"].tolist()


def test_tsne3d_csv_is_a_3d_fit_of_the_same_nuggets(run):
    """The same nuggets as tsne.csv, fitted again with three components and the run's
    perplexity and seed; clusters_tsne.png still draws the 2-D fit."""
    out, result, _, settings = run
    tsne3d, tsne = _csv(out, "tsne3d.csv"), _csv(out, "tsne.csv")
    assert list(tsne3d.columns) == ["file_number", "nugget0", "tsne1", "tsne2", "tsne3"]
    keys = ["file_number", "nugget0"]
    assert tsne3d[keys].to_numpy().tolist() == tsne[keys].to_numpy().tolist()
    pool = result.pool
    want = tsne_3d(
        pool.centers[pool.use], perplexity=settings.tsne_perplexity, seed=settings.tsne_seed
    )
    assert np.array_equal(tsne3d[["tsne1", "tsne2", "tsne3"]].to_numpy(), want.astype(float))


def test_cluster_markers_are_each_files_cell_means(run):
    """P10: each file's mean per cluster of its own cells, from events_N.csv's clusters, equals
    the nugget-weighted mean cluster_markers.csv gives; the cells add up to cluster_summary's."""
    out, result, _, _ = run
    markers = _csv(out, "cluster_markers.csv")
    assert list(markers.columns) == ["file_number", "file", "cluster", "cells", *LABELS]
    assert len(markers) == 3 * 5
    summary = _csv(out, "cluster_summary.csv")
    assert markers["cells"].tolist() == summary["cells"].tolist()
    for number in (1, 2, 3):
        _, x = _cells_of(result, number)
        cluster = pd.read_csv(out / f"events_{number}.csv")["cluster"].to_numpy()
        mine = markers[markers["file_number"] == number].set_index("cluster")
        assert mine["file"].eq(NAMES[number - 1]).all()
        for c in range(1, 6):
            at = cluster == c
            assert mine.loc[c, "cells"] == at.sum()
            got = mine.loc[c, LABELS].to_numpy(dtype=float)
            if at.any():
                np.testing.assert_allclose(got, x[at].mean(axis=0), rtol=1e-9)
            else:
                assert np.isnan(got).all()


def test_groups_csv_names_every_file(run):
    out, _, _, _ = run
    groups = pd.read_csv(out / "groups.csv", dtype={"kept": str})
    assert groups.to_dict("list") == {
        "file_number": [1, 2, 3],
        "file": list(NAMES),
        "group": list(GROUPS),
        "kept": ["true", "true", "true"],
    }


def _half_cell(out, numbers):
    """The fold change's pseudocount recomputed from the run's events tables: half a cell of each
    kept file in percentage points, 100 * 0.5 / N_f, N_f its rows in events_N.csv (one per kept
    cell), averaged over the kept files."""
    sizes = [len(pd.read_csv(out / f"events_{n}.csv")) for n in numbers]
    return sum(50 / n for n in sizes) / len(sizes), sizes


def test_group_summary_recomputed_by_hand(run):
    """P11: from cluster_summary.csv and the events tables alone; ctrl, the group of the first
    kept file, is the reference."""
    out, _, _, _ = run
    summary = _csv(out, "cluster_summary.csv")
    got = _csv(out, "group_summary.csv")
    assert list(got.columns) == [
        "group",
        "cluster",
        "samples",
        "mean_percent",
        "sd_percent",
        "min_percent",
        "max_percent",
        "reference",
        "diff_vs_ref",
        "log2fc_vs_ref",
        "log2fc_pseudocount",
    ]
    assert got["group"].tolist() == ["ctrl"] * 5 + ["treated"] * 5
    pc, sizes = _half_cell(out, (1, 2, 3))
    assert sizes == [39_860, 2_292, 13_308]
    assert got["log2fc_pseudocount"].tolist() == pytest.approx([pc] * len(got), rel=1e-12)
    assert got["log2fc_pseudocount"].nunique() == 1  # one value for the whole run
    files = {"ctrl": [1, 2], "treated": [3]}
    for row in got.itertuples():
        c = row.cluster
        pct = [
            summary.loc[(summary.file_number == f) & (summary.cluster == c), "percent"].item()
            for f in files[row.group]
        ]
        ref = [
            summary.loc[(summary.file_number == f) & (summary.cluster == c), "percent"].item()
            for f in files["ctrl"]
        ]
        mean, ref_mean = sum(pct) / len(pct), sum(ref) / len(ref)
        assert row.samples == len(pct)
        assert row.mean_percent == pytest.approx(mean, rel=1e-12)
        assert row.min_percent == min(pct) and row.max_percent == max(pct)
        if len(pct) > 1:
            sd = math.sqrt(sum((p - mean) ** 2 for p in pct) / (len(pct) - 1))
            assert row.sd_percent == pytest.approx(sd, rel=1e-12)
        else:
            assert math.isnan(row.sd_percent)
        assert row.reference == pytest.approx(ref_mean, rel=1e-12)
        if row.group == "ctrl":
            assert row.diff_vs_ref == 0 and row.log2fc_vs_ref == 0
        else:
            assert row.diff_vs_ref == pytest.approx(mean - ref_mean, rel=1e-12, abs=1e-12)
            want = math.log2((mean + pc) / (ref_mean + pc))
            assert row.log2fc_vs_ref == pytest.approx(want, rel=1e-12, abs=1e-12)


def test_groups_with_the_same_percents_have_a_fold_change_of_exactly_0(gated, tmp_path):
    """Three files that keep the same population of 202.fcs give the same nuggets and the same
    percents, so a treated group of one of them has a log2 fold change of exactly 0 against the
    ctrl group of the other two, in every cluster, whatever the pseudocount."""
    out = tmp_path / "same"
    out.mkdir()
    settings = ClusterSettings(
        dn_num2=60, k=5, n_jobs=1, groups=GROUPS, cells_per_file=0, tsne=False
    )
    cluster_stage(gated, [[1], [1], [1]], out, settings, read=read_202)
    summary = _csv(out, "cluster_summary.csv")
    percent = summary.pivot(index="cluster", columns="file_number", values="percent")
    assert (percent[1] == percent[2]).all() and (percent[1] == percent[3]).all()
    got = _csv(out, "group_summary.csv")
    treated = got[got.group == "treated"]
    assert len(treated) == 5
    assert treated["log2fc_vs_ref"].tolist() == [0.0] * 5
    assert treated["diff_vs_ref"].tolist() == [0.0] * 5
    pc, _ = _half_cell(out, (1, 2, 3))
    assert got["log2fc_pseudocount"].tolist() == pytest.approx([pc] * 10, rel=1e-12)


def test_group_markers_recomputed_by_hand(run):
    """P11: from cluster_markers.csv alone, the files with cells in the cluster counting once
    each."""
    out, _, _, _ = run
    markers = _csv(out, "cluster_markers.csv")
    got = _csv(out, "group_markers.csv")
    assert list(got.columns) == [
        "group",
        "cluster",
        "channel",
        "label",
        "samples",
        "mean",
        "reference",
        "diff_vs_ref",
    ]
    assert len(got) == 2 * 5 * 3
    files = {"ctrl": [1, 2], "treated": [3]}

    def mean_of(group, c, label):
        m = markers[markers.file_number.isin(files[group]) & (markers.cluster == c)]
        m = m[m.cells > 0]
        return len(m), (m[label].sum() / len(m) if len(m) else math.nan)

    for row in got.itertuples():
        assert (row.channel, row.label) in set(zip(CHANNELS, LABELS))
        n, mean = mean_of(row.group, row.cluster, row.label)
        _, ref = mean_of("ctrl", row.cluster, row.label)
        assert row.samples == n
        for value, want in ((row.mean, mean), (row.reference, ref)):
            assert value == pytest.approx(want, rel=1e-12, nan_ok=True)
        if math.isnan(mean) or math.isnan(ref):
            assert math.isnan(row.diff_vs_ref)
        elif row.group == "ctrl":
            assert row.diff_vs_ref == 0
        else:
            assert row.diff_vs_ref == pytest.approx(mean - ref, rel=1e-12, abs=1e-12)


def test_cells_are_sampled_kept_cells_in_the_runs_pca(run):
    """P14: min(cells_per_file, kept) cells per file, sorted by event0, each in the cluster
    events_N.csv gives it, at its place in the run's PCA."""
    out, result, _, settings = run
    cells = _csv(out, "cells.csv")
    assert list(cells.columns) == [
        "file_number",
        "event0",
        "nugget0",
        "cluster",
        "PC1",
        "PC2",
        "PC3",
        *LABELS,
    ]
    center = _csv(out, "pca_center.csv")
    c, scale = center["center"].to_numpy(), center["scale"].to_numpy()
    rotation = _csv(out, "pca_loadings.csv")[["PC1", "PC2", "PC3"]].to_numpy()
    for number in (1, 2, 3):
        kp, x = _cells_of(result, number)
        mine = cells[cells["file_number"] == number]
        assert len(mine) == min(settings.cells_per_file, len(kp.rows))
        event0 = mine["event0"].to_numpy()
        assert (np.diff(event0) > 0).all()
        at = np.sort(
            np.random.default_rng([settings.seed, number]).choice(
                len(kp.rows), size=len(mine), replace=False
            )
        )
        assert np.array_equal(event0, kp.rows[at])
        events = pd.read_csv(out / f"events_{number}.csv").set_index("event0")
        assert mine["cluster"].tolist() == events.loc[event0, "cluster"].tolist()
        assert mine["nugget0"].tolist() == events.loc[event0, "nugget0"].tolist()
        values = mine[LABELS].to_numpy()
        np.testing.assert_allclose(values, x[at], rtol=1e-15)
        np.testing.assert_allclose(
            mine[["PC1", "PC2", "PC3"]].to_numpy(),
            ((values - c) / scale) @ rotation,
            rtol=1e-9,
            atol=1e-12,
        )


def test_small_k_figures_are_the_same_with_or_without_the_colours(run, tmp_path, close_figures):
    """Up to 8 clusters, cluster_colors gives tab10's own colours, so passing them draws the
    figures byte for byte as before."""
    _, result, _, settings = run
    pool = result.pool
    args = (pool, result.tables.centers, LABELS, settings.cofactor, result.tsne)
    before = result_figures(*args)
    after = result_figures(*args, colors=pool_colors(pool))
    for name in before:
        a, b = tmp_path / f"a_{name}", tmp_path / f"b_{name}"
        before[name].savefig(a, dpi=60)
        after[name].savefig(b, dpi=60)
        assert a.read_bytes() == b.read_bytes(), name


def test_row_filters_keep_exactly_the_cells_that_pass(gated, tmp_path):
    """P12: the kept cells are the chosen populations' cells that pass every filter on the raw
    values, and selection.csv counts them."""
    specs = ("FJComp-BV510-A > 10000", "[FJComp-Spark Blue-A] <= 40000")
    settings = ClusterSettings(dn_num2=40, k=3, n_jobs=1, tsne=False, row_filters=specs)
    result = cluster_stage(gated, CHOSEN, tmp_path, settings, read=read_202)
    events, pnn, _ = read_202(None)
    selection = pd.read_csv(tmp_path / "selection.csv")
    assert list(selection.columns)[-2:] == ["filtered", "filtered_percent"]
    filters = [parse_filter(s) for s in specs]
    for i, pops in enumerate(CHOSEN):
        rows = np.flatnonzero(gated[i]["masks"][:, pops[0] - 1])
        mask = filter_mask(lambda c, rows=rows: events[rows, pnn.index(c)], filters, len(rows))
        assert 0 < mask.sum() < len(rows)
        kp = result.kept[i]
        assert np.array_equal(kp.rows, rows[mask])
        assert len(pd.read_csv(tmp_path / f"events_{i + 1}.csv")) == mask.sum()
        row = selection.iloc[i]
        assert row["kept"] == len(rows) and row["filtered"] == mask.sum()
        assert row["filtered_percent"] == pytest.approx(100 * mask.sum() / len(events))


def test_without_filters_selection_keeps_its_columns(run):
    out, _, _, _ = run
    assert "filtered" not in pd.read_csv(out / "selection.csv").columns


def test_a_filter_column_a_file_lacks_names_the_file(gated, tmp_path):
    settings = ClusterSettings(dn_num2=40, k=3, n_jobs=1, row_filters=("CD3-A > 1",))
    with pytest.raises(FlowError) as e:
        cluster_stage(gated, CHOSEN, tmp_path, settings, read=read_202)
    assert e.value.param == "row_filters"
    assert e.value.cli(cli_flag).startswith("--filter names CD3-A, which a.fcs doesn't have")


def test_filters_that_keep_nothing_stop_the_run(gated, tmp_path):
    settings = ClusterSettings(dn_num2=40, k=3, n_jobs=1, row_filters=("FJComp-BV510-A > 1e12",))
    with pytest.raises(FlowError, match="row_filters keeps fewer than 2 cells in every file"):
        cluster_stage(gated, CHOSEN, tmp_path, settings, read=read_202)


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        (("ctrl", "ctrl"), "groups gives 2 names for 3 files; give one per file"),
        (("ctrl", "", "x"), "groups has an empty name"),
        (("ctrl", "a/b", "x"), "groups has 'a/b'"),
    ],
)
def test_bad_groups_stop_before_any_read(gated, tmp_path, groups, message):
    """P13."""
    seen = []

    def read(path):
        seen.append(path)
        return read_202(path)

    with pytest.raises(FlowError) as e:
        cluster_stage(gated, CHOSEN, tmp_path, ClusterSettings(groups=groups), read=read)
    assert e.value.param == "groups"
    assert str(e.value).startswith(message)
    assert seen == [] and list(tmp_path.iterdir()) == []


def test_parse_groups_reads_one_name_per_file():
    assert parse_groups(" ctrl ; ctrl;IL-2 treated", 3) == ("ctrl", "ctrl", "IL-2 treated")
    with pytest.raises(FlowError) as e:
        parse_groups("ctrl;treated", 3)
    assert e.value.param == "groups"
    assert e.value.cli(cli_flag) == (
        "--groups gives 2 names for 3 files; give one per file, separated by ;"
    )
    for spec in ("ctrl;;b", "ctrl;_b;c"):
        with pytest.raises(FlowError) as e:
            parse_groups(spec, 3)
        assert e.value.param == "groups"


def test_a_hundred_clusters_of_the_tree_run(gated, tmp_path):
    """P15: the hierarchical tree cut into k = 100 of 202.fcs's 39,860 Pop 1 cells, each
    cluster's colour from its family in the tree."""
    settings = ClusterSettings(
        dn_num2=400, k=100, n_jobs=1, tsne=False, cells_per_file=0, method="tree"
    )
    result = cluster_stage(gated[:1], [[1]], tmp_path, settings, read=read_202)
    assert result.pool.k == 100
    colors = pd.read_csv(tmp_path / "cluster_colors.csv")
    assert len(colors) == 100 and colors["color"].nunique() == 100
    parents = tree_parents(result.pool.tree, 100)
    assert colors["parent"].tolist() == [p + 1 for p in parents]
    assert colors["color"].tolist() == cluster_colors(100, parents)
    assert not (tmp_path / "cells.csv").exists()


def test_the_tree_clamps_a_larger_k_to_the_nuggets_in_use(gated, tmp_path):
    """P15: the tree cut into k = 500 of no more than 40 nuggets makes one cluster per nugget in
    use, and the cluster event reports the k used. It runs on mean centers with NumPy's draws,
    the configuration a run.json written before method existed loads as."""
    events = []
    settings = ClusterSettings(
        dn_num2=40, k=500, n_jobs=1, tsne=False, method="tree", center_method="mean", draws="numpy"
    )
    run = cluster_stage(gated[:1], [[1]], tmp_path, settings, read=read_202, on_event=events.append)
    used = int(run.pool.use.sum())
    assert used < 500
    assert run.pool.k == used
    assert next(e for e in events if e.stage == "cluster").data["k"] == used
    assert len(pd.read_csv(tmp_path / "cluster_colors.csv")) == used


WKMEANS_WALL = 60.0  # seconds: a bound far above the second or so either run below takes


def test_weighted_k_means_makes_a_feasible_k_or_stops_naming_it_in_bounded_time(gated, tmp_path):
    """P15 for weighted k-means, which has no clamp: k = 50 of 400 nuggets is made exactly, with
    a colour each and no tree. k = 100 of the same nuggets stops with a FlowError naming k once
    wkmeans' cap of draws is spent, where R would keep drawing: at this seed 996 of the 1,000
    random partitions put a label on fewer than two nuggets, and the other 4 fill only 86 to 94
    clusters. Neither run hangs, and neither clusters with a smaller k."""
    events = []
    settings = ClusterSettings(dn_num2=400, k=50, n_jobs=1, tsne=False, cells_per_file=0)
    start = time.perf_counter()
    run = cluster_stage(gated[:1], [[1]], tmp_path, settings, read=read_202, on_event=events.append)
    assert time.perf_counter() - start < WKMEANS_WALL
    assert run.pool.tree is None and run.pool.k == 50 and int(run.pool.use.sum()) == 400
    assert next(e for e in events if e.stage == "cluster").data["k"] == 50
    colors = pd.read_csv(tmp_path / "cluster_colors.csv")
    parents = block_parents(50)  # no tree, so neighbouring cluster numbers share a family
    assert colors["cluster"].tolist() == list(range(1, 51))
    assert colors["parent"].tolist() == [p + 1 for p in parents]
    assert colors["color"].tolist() == cluster_colors(50, parents)
    assert colors["color"].nunique() == 50
    (tmp_path / "k100").mkdir()
    start = time.perf_counter()
    with pytest.raises(FlowError) as e:
        cluster_stage(gated[:1], [[1]], tmp_path / "k100", replace(settings, k=100), read=read_202)
    assert time.perf_counter() - start < WKMEANS_WALL
    assert str(e.value).startswith(
        "weighted k-means can't make k = 100 clusters of these 400 nuggets (none of 1,000 random "
        "partitions filled all k = 100 clusters"
    )
    assert e.value.param == "k"
    assert e.value.cli(cli_flag).endswith("lower --k or use method tree")
