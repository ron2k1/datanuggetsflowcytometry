"""The two stages a flow run takes after the populations are chosen, on 202's recorded events:
Transform, arcsinh(x / cofactor), and Scale, every channel centred and scaled to SD 1 by the mean
and SD pooled over every clustered file's kept cells. b.fcs is 202 read at 40 times the
fluorescence gain, so its channels spread differently from a.fcs's. The nuggets, their
clustering, the PCA, the t-SNE and cells.csv's places use the scaled values; every table of channel
values is back in arcsinh units."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from datanuggets import RDraws, create_dn

from datanuggets_flow import state
from datanuggets_flow._defaults import FLOW_SKEW_WARN
from datanuggets_flow._pipeline.stages import _scale_event
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.pipeline import (
    Cofactor,
    Scaling,
    cluster_stage,
    gate_files,
    make_nuggets,
    pooled_scaling,
)
from datanuggets_flow.settings import ClusterSettings, GateSettings, cli_flag
from exactcsv import read_exact
from flowcases import LABELS, digest, load_case, read_202

GAIN = 40.0  # b.fcs's fluorescence, read at another gain
COFACTOR = 6000.0  # given to every run: the numbers and tables here were pinned with it
CHANNELS = ["FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"]
CHOSEN = [[1], [6]]  # 39,860 and 2,292 cells
FILTER = "[FJComp-BV510-A] > 20000"


def _events(name):
    """202's events as the file name reads them: b.fcs at GAIN times the fluorescence."""
    events, pnn, pns = read_202(None)
    if name == "b.fcs":
        events = events.copy()
        events[:, 2:] *= GAIN
    return events, pnn, pns


def _read(path):
    return _events(Path(path).name)


def _sample(name, masks):
    events, pnn, _ = _events(name)
    return {"path": Path(name), "n_events": len(events), "pnn": pnn, "masks": masks}


def _arcsinh(name, rows):
    """The cells at rows of the file name after the Transform stage."""
    events, _, _ = _events(name)
    return np.arcsinh(events[np.ix_(rows, [2, 3, 4])] / COFACTOR)


def _pop(masks, pop):
    return np.flatnonzero(masks[:, pop - 1])


def _skew(x):
    """Each column's skewness, the third central moment over the SD cubed (ddof 0)."""
    d = x - x.mean(axis=0)
    return (d**3).mean(axis=0) / (d**2).mean(axis=0) ** 1.5


def test_pooled_scaling_gives_every_channel_mean_0_and_sd_1_over_the_files():
    """The mean and SD (ddof 0) are the pooled cells' own, not any one file's: after scaling the
    pool has mean 0 and SD 1 in every channel while each file keeps its own offset."""
    masks = load_case("202").his_masks
    samples = [_sample("a.fcs", masks), _sample("b.fcs", masks)]
    s = pooled_scaling(samples, CHOSEN, CHANNELS, ClusterSettings(cofactor=COFACTOR), read=_read)
    parts = [_arcsinh("a.fcs", _pop(masks, 1)), _arcsinh("b.fcs", _pop(masks, 6))]
    pooled = np.vstack(parts)
    assert isinstance(s, Scaling)
    assert (s.cells, s.files) == (len(pooled), 2) == (39_860 + 2_292, 2)
    np.testing.assert_allclose(s.mean, pooled.mean(axis=0), rtol=1e-12)
    np.testing.assert_allclose(s.sd, pooled.std(axis=0), rtol=1e-12)
    np.testing.assert_allclose(s.skew, _skew(pooled), rtol=1e-9)
    scaled = s.apply(pooled)
    np.testing.assert_allclose(scaled.mean(axis=0), 0, atol=1e-12)
    np.testing.assert_allclose(scaled.std(axis=0), 1, rtol=1e-12)
    for part in parts:  # pooled, not per file: neither file is centred on its own mean
        assert np.abs(s.apply(part).mean(axis=0)).max() > 0.1
    assert not np.allclose(parts[0].std(axis=0), parts[1].std(axis=0), rtol=0.1)
    np.testing.assert_allclose(s.undo(scaled), pooled, rtol=1e-12, atol=1e-12)
    assert s.record() == {
        "mean": s.mean.tolist(),
        "sd": s.sd.tolist(),
        "ddof": 0,
        "cells": len(pooled),
        "skew": s.skew.tolist(),
    }


def test_make_nuggets_builds_each_files_nuggets_on_the_scaled_cells():
    """Each file's nuggets are create_dn's of its scaled cells, with the run's center method and
    R's set.seed(seed) draws, the defaults."""
    masks = load_case("202").his_masks
    samples = [_sample("a.fcs", masks), _sample("b.fcs", masks)]
    settings = ClusterSettings(dn_num2=50, n_jobs=1, cofactor=COFACTOR)
    s = pooled_scaling(samples, CHOSEN, CHANNELS, settings, read=_read)
    kept = make_nuggets(samples, CHOSEN, CHANNELS, settings, read=_read, scaling=s)
    for kp, name, pop in zip(kept, ("a.fcs", "b.fcs"), (1, 6)):
        rows = _pop(masks, pop)
        x = s.apply(_arcsinh(name, rows))
        want = create_dn(
            x, center_method="original", dn_num2=50, n_jobs=1, seed=RDraws(settings.seed)
        )
        assert np.array_equal(kp.rows, rows)
        for field in ("centers", "weights", "scales", "assignments"):
            assert np.array_equal(getattr(kp.dn, field), getattr(want, field)), field


def test_the_stats_count_only_the_cells_clustered():
    """Row filters take cells out of the stats as they take them out of the nuggets, and a file
    left out for keeping too few cells counts for nothing."""
    masks = load_case("202").his_masks
    one = np.zeros_like(masks)
    one[_pop(masks, 1)[:1], 0] = True  # c.fcs keeps a single cell
    samples = [_sample("a.fcs", masks), _sample("b.fcs", masks), _sample("c.fcs", one)]
    chosen = [*CHOSEN, [1]]
    settings = ClusterSettings(dn_num2=50, n_jobs=1, row_filters=(FILTER,), cofactor=COFACTOR)
    s = pooled_scaling(samples, chosen, CHANNELS, settings, read=_read)
    passed = {}
    for name, pop in (("a.fcs", 1), ("b.fcs", 6)):
        events, _, _ = _events(name)
        rows = _pop(masks, pop)
        passed[name] = rows[events[rows, 3] > 20000]
    assert 0 < len(passed["a.fcs"]) < 39_860 and len(passed["b.fcs"]) > 0
    pooled = np.vstack([_arcsinh(name, rows) for name, rows in passed.items()])
    assert (s.cells, s.files) == (len(pooled), 2)
    np.testing.assert_allclose(s.mean, pooled.mean(axis=0), rtol=1e-12)
    np.testing.assert_allclose(s.sd, pooled.std(axis=0), rtol=1e-12)
    filtered = {}
    kept = make_nuggets(
        samples, chosen, CHANNELS, settings, read=_read, filtered=filtered, scaling=s
    )
    assert [kp.number for kp in kept] == [1, 2]
    assert filtered[3] < 2
    assert sum(len(kp.rows) for kp in kept) == s.cells


def test_a_channel_with_sd_0_is_scaled_by_1(tmp_path):
    """A channel with one value in every kept cell has SD 0: it is centred and scaled by 1, so
    its scaled values are all 0 and its tables give the value back."""
    level = 1500.0

    def read(path):
        events, pnn, pns = _read(path)
        events = events.copy()
        events[:, 3] = level
        return events, pnn, pns

    gated = gate_files([Path("a.fcs"), Path("b.fcs")], GateSettings(), read=read)
    s = pooled_scaling(gated, CHOSEN, CHANNELS, ClusterSettings(cofactor=COFACTOR), read=read)
    assert s.sd[1] == 1.0 and s.mean[1] == pytest.approx(np.arcsinh(level / COFACTOR), rel=1e-15)
    assert (s.sd[[0, 2]] != 1.0).all()
    settings = ClusterSettings(
        dn_num2=40, k=3, n_jobs=1, tsne=False, cells_per_file=50, cofactor=COFACTOR
    )
    out = tmp_path
    run = cluster_stage(gated, CHOSEN, out, settings, read=read)
    assert s.skew[1] == 0.0 and np.isfinite(s.skew).all()
    assert (run.pool.centers[:, 1] == 0).all()
    want = np.arcsinh(level / COFACTOR)
    for name in ("cluster_centers.csv", "nuggets_1.csv", "cells.csv"):
        table = pd.read_csv(out / name)
        np.testing.assert_allclose(table[LABELS[1]], want, rtol=1e-15)
    for name in ("pca_scores.csv", "cells.csv", "cluster_markers.csv"):
        values = pd.read_csv(out / name).select_dtypes("number").to_numpy()
        assert np.isfinite(values[~np.isnan(values)]).all()


@pytest.fixture(scope="module")
def scaled_run(tmp_path_factory):
    """a.fcs and b.fcs gated, Pop 1 and Pop 6 clustered with the Scale stage on, in groups."""
    out = tmp_path_factory.mktemp("scaled")
    gated = gate_files([Path("a.fcs"), Path("b.fcs")], GateSettings(), read=_read)
    settings = ClusterSettings(
        dn_num2=60,
        k=5,
        n_jobs=1,
        groups=("x", "y"),
        cells_per_file=400,
        tsne_perplexity=10,
        cofactor=COFACTOR,
    )
    events = []
    run = cluster_stage(gated, CHOSEN, out, settings, read=_read, on_event=events.append)
    return out, run, events, settings, gated


def _cells(gated, number):
    name = ("a.fcs", "b.fcs")[number - 1]
    return _arcsinh(name, _pop(gated[number - 1]["masks"], CHOSEN[number - 1][0]))


def test_the_run_scales_by_the_pooled_stats(scaled_run):
    _, run, _, settings, gated = scaled_run
    want = pooled_scaling(gated, CHOSEN, run.channels, settings, read=_read)
    assert run.pool.scaling.cells == want.cells
    assert np.array_equal(run.pool.scaling.mean, want.mean)
    assert np.array_equal(run.pool.scaling.sd, want.sd)
    # the nuggets' cell means, weighted by their cells, are the mean of every scaled cell
    used = run.pool.cell_means()[run.pool.use]
    weights = run.pool.weights[run.pool.use]
    np.testing.assert_allclose(np.average(used, axis=0, weights=weights), 0, atol=1e-9)


def test_stage_events_name_the_transform_and_the_scale(scaled_run):
    """The run reports both stages, in order, between the selection and the nuggets. The Scale
    stage's pass over the files reports each file with nothing to print, so a backend can move
    its bar and stop the run there, then the stage's lines; the default channels' check before
    the selection reports each file the same way."""
    _, run, events, _, _ = scaled_run
    assert [(e.stage, e.file) for e in events] == [
        ("channels", 1),
        ("channels", 2),
        ("select", None),
        ("transform", None),
        ("scale", 1),
        ("scale", 2),
        ("scale", None),
        ("nuggets", 1),
        ("nuggets", 2),
        ("cluster", None),
    ]
    transform, scale = events[3], events[6]
    counted = [(2, "", {"cells": 39_860}), (2, "", {"cells": 2_292})]
    assert [(e.n_files, e.message, e.data) for e in events[4:6]] == counted
    assert [(e.n_files, e.message, e.data) for e in events[:2]] == counted
    assert transform.message == (
        "\nTransform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set"
    )
    assert transform.data == {
        "transform": {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
    }
    s = run.pool.scaling
    lines = scale.message.split("\n")
    assert lines[0] == (
        f"Scale: every channel to mean 0 and SD 1, pooled over 2 files' {s.cells:,} cells"
    )
    assert np.abs(s.skew).max() < FLOW_SKEW_WARN  # so no warning
    assert lines[1:] == [
        f"  {label}: mean {m:.4g}, SD {sd:.4g}, skew {g:.3g}"
        for label, m, sd, g in zip(LABELS, s.mean, s.sd, s.skew)
    ]
    assert scale.data == {"standardize": s.record()}


def test_the_scale_stage_warns_of_a_skewed_channel(tmp_path):
    """With Transform none, 202's pooled channels keep their long tails (skewness about 11, 6.4
    and 6.8 over a.fcs and b.fcs). Their mean and SD follow the tail, and the scale event says
    so under the channels' lines."""
    events = []
    gated = gate_files([Path("a.fcs"), Path("b.fcs")], GateSettings(), read=_read)
    settings = ClusterSettings(dn_num2=40, k=3, n_jobs=1, tsne=False, cofactor=0)
    run = cluster_stage(gated, CHOSEN, tmp_path, settings, read=_read, on_event=events.append)
    s = run.pool.scaling
    assert (np.abs(s.skew) > FLOW_SKEW_WARN).all()
    lines = next(e for e in events if e.stage == "scale" and e.file is None).message.split("\n")
    assert len(lines) == 1 + len(LABELS) + 2
    assert lines[-2:] == [
        (
            f"  Warning: 3 of 3 channels have skewness beyond {FLOW_SKEW_WARN:g} either way after "
            "the transform."
        ),
        (
            "  Their mean and SD follow the long tail, so most cells take a narrow band of each "
            "scaled axis; a smaller cofactor compresses the tail."
        ),
    ]
    # one channel past the line reads in the singular
    one = s._replace(skew=np.array([s.skew[0], 0.0, 0.0]))
    line = _scale_event(one, LABELS, 2).message.split("\n")[-2]
    assert line.startswith("  Warning: 1 of 3 channels has skewness beyond")


# recorded from the scaled_run fixture when weighted k-means on original centers with R's draws
# became the default, once R's create.DN and Wkmeans on the scaled cells each file gave create_dn
# gave the same nuggets and clusters, bit for bit; the PCA's loadings are left out, since an SVD
# may flip a component's sign between platforms
SCALED_DIGESTS = {
    "nuggets_1.csv": "b6f3c9e2919e2b0ab56a205002e10e202edc1a05c9ae1f723ed4a9c8514a2656",
    "nuggets_2.csv": "cbe6304205df5fb8fbecdfe2d6bf146c240b844506b91468a02ce4eb54539aff",
    "cluster_centers.csv": "a04b654742ad95cf1918bddffd3d5af36fc048f10f3560fe2032838c03169c33",
    "cluster_markers.csv": "d83170a95d9b80069dce5c0f3936d204bbdc23503a74a5137fd1b1b29fa93acb",
    "pca_center.csv": "4e198f75ba9fbec59ffa84dab13bec260552a1fef27c862d3708ac409399f481",
}


def test_the_scaled_runs_tables_are_pinned(scaled_run):
    """The tables of a run with the Scale stage on, as flowcases.digest reads them: a change to
    the default numbers (the stats, the scaling of one consumer and not another) fails here even
    where the stage's own tests, which recompute the same values, would not."""
    out = scaled_run[0]
    assert {name: digest(out / name) for name in SCALED_DIGESTS} == SCALED_DIGESTS


def test_value_tables_are_in_arcsinh_units(scaled_run):
    """nuggets_N.csv gives each nugget's center, create.DN's with center.method "original": the
    point the nugget was built around, one of the cells events_N.csv assigns to that nugget,
    taken back to arcsinh units.
    cluster_centers.csv and cluster_markers.csv give means of the cells' arcsinh values, from
    events_N.csv's nuggets and clusters, not of the scaled values."""
    out, run, _, _, gated = scaled_run
    centers = pd.read_csv(out / "cluster_centers.csv").set_index("cluster")[LABELS]
    markers = pd.read_csv(out / "cluster_markers.csv")
    s = run.pool.scaling
    pooled, clusters = [], []
    for number in (1, 2):
        x = _cells(gated, number)
        ev = pd.read_csv(out / f"events_{number}.csv")
        nug = pd.read_csv(out / f"nuggets_{number}.csv")
        given = nug[LABELS].to_numpy(dtype=float)
        np.testing.assert_allclose(given, s.undo(run.kept[number - 1].dn.centers), rtol=1e-12)
        weight, nugget0 = nug["weight"].to_numpy(), ev["nugget0"].to_numpy()
        np.testing.assert_array_equal(weight, np.bincount(nugget0, minlength=len(nug)))
        for j in np.flatnonzero(weight > 0):  # each center is one of its own nugget's cells
            gap = np.abs(x[nugget0 == j] - given[j]).max(axis=1).min()
            assert gap <= 1e-9 * np.abs(given[j]).max(), (number, j, gap)
        mine = markers[markers["file_number"] == number].set_index("cluster")
        cl = ev["cluster"].to_numpy()
        for c in np.unique(cl):
            got = mine.loc[c, LABELS].to_numpy(dtype=float)
            np.testing.assert_allclose(got, x[cl == c].mean(axis=0), rtol=1e-9)
        pooled.append(x)
        clusters.append(cl)
    x, cl = np.vstack(pooled), np.concatenate(clusters)
    for c in centers.index:
        np.testing.assert_allclose(centers.loc[c].to_numpy(), x[cl == c].mean(axis=0), rtol=1e-9)
    groups = pd.read_csv(out / "group_markers.csv")
    row = groups[(groups["group"] == "y") & (groups["cluster"] == cl[-1])]
    want = markers[(markers["file_number"] == 2) & (markers["cluster"] == cl[-1])]
    for label in LABELS:
        got = row.loc[row["label"] == label, "mean"].item()
        assert got == pytest.approx(want[label].item(), rel=1e-12)


def test_the_pca_is_of_the_scaled_nuggets_and_its_center_reads_in_arcsinh_units(scaled_run):
    """pca_center.csv gives the center in arcsinh units and each channel's scale, prcomp's
    center and scale, so ((x - center) / scale) @ rotation places any arcsinh-unit row."""
    out, run, _, _, _ = scaled_run
    center = pd.read_csv(out / "pca_center.csv")
    assert list(center.columns) == ["channel", "label", "center", "scale"]
    assert center["channel"].tolist() == CHANNELS
    s = run.pool.scaling
    np.testing.assert_array_equal(center["scale"].to_numpy(), s.sd)
    loadings = pd.read_csv(out / "pca_loadings.csv")
    rotation = loadings[["PC1", "PC2", "PC3"]].to_numpy()
    scores = pd.read_csv(out / "pca_scores.csv")
    used = run.pool.centers[run.pool.use]
    arcsinh = s.undo(used)
    c, sc = center["center"].to_numpy(), center["scale"].to_numpy()
    np.testing.assert_allclose(
        ((arcsinh - c) / sc) @ rotation, scores[["PC1", "PC2", "PC3"]], rtol=1e-9, atol=1e-12
    )
    weighted = np.average(used, axis=0, weights=run.pool.weights[run.pool.use])
    np.testing.assert_allclose(c, s.undo(weighted), rtol=1e-12)


def test_cells_are_placed_by_the_same_scaling(scaled_run):
    """cells.csv's channels are the sampled cells' arcsinh values as read, and their PCs place
    those values scaled by the run's pooled stats in the nuggets' PCA."""
    out, run, _, settings, gated = scaled_run
    cells = read_exact(out / "cells.csv")
    center = pd.read_csv(out / "pca_center.csv")
    rotation = pd.read_csv(out / "pca_loadings.csv")[["PC1", "PC2", "PC3"]].to_numpy()
    s = run.pool.scaling
    for number in (1, 2):
        x = _cells(gated, number)
        mine = cells[cells["file_number"] == number]
        assert len(mine) == settings.cells_per_file
        kp = run.kept[number - 1]
        at = np.searchsorted(kp.rows, mine["event0"].to_numpy())
        values = mine[LABELS].to_numpy()
        np.testing.assert_array_equal(values, x[at])
        pcs = mine[["PC1", "PC2", "PC3"]].to_numpy()
        c = center["center"].to_numpy()
        np.testing.assert_allclose(
            pcs, (s.apply(values) - s.apply(c)) @ rotation, rtol=1e-9, atol=1e-12
        )
        scaled = (values - c) / center["scale"].to_numpy()
        np.testing.assert_allclose(pcs, scaled @ rotation, rtol=1e-9, atol=1e-12)


def test_tsne_is_of_the_scaled_nuggets(scaled_run):
    from datanuggets.projection import tsne_2d

    out, run, _, settings, _ = scaled_run
    want = tsne_2d(
        run.pool.centers[run.pool.use],
        perplexity=settings.tsne_perplexity,
        seed=settings.tsne_seed,
    )
    np.testing.assert_array_equal(run.tsne, want)
    assert pd.read_csv(out / "tsne3d.csv").shape[1] == 5


def test_without_the_scale_stage_the_run_is_as_before(tmp_path):
    """standardize=False: no scaling, the pooled centers are the arcsinh values themselves,
    pca_center.csv keeps its three columns, and the scale event says so."""
    events = []
    gated = gate_files([Path("a.fcs"), Path("b.fcs")], GateSettings(), read=_read)
    settings = ClusterSettings(
        dn_num2=40, k=3, n_jobs=1, tsne=False, standardize=False, cofactor=COFACTOR
    )
    run = cluster_stage(gated, CHOSEN, tmp_path, settings, read=_read, on_event=events.append)
    assert run.pool.scaling is None
    assert list(pd.read_csv(tmp_path / "pca_center.csv").columns) == ["channel", "label", "center"]
    scale = next(e for e in events if e.stage == "scale")
    assert scale.message == "Scale: none; the channels keep the transform's units"
    assert scale.data == {"standardize": False}
    nug = read_exact(tmp_path / "nuggets_1.csv")
    np.testing.assert_array_equal(nug[LABELS].to_numpy(), run.kept[0].dn.centers)


def test_a_linear_run_says_its_transform_is_none(tmp_path):
    events = []
    gated = gate_files([Path("a.fcs")], GateSettings(), read=read_202)
    settings = ClusterSettings(dn_num2=40, k=3, n_jobs=1, tsne=False, cofactor=0)
    run = cluster_stage(gated, [[6]], tmp_path, settings, read=read_202, on_event=events.append)
    transform = next(e for e in events if e.stage == "transform")
    assert transform.message == "\nTransform: none; the channels are clustered as stored"
    assert transform.data == {"transform": {"name": "none"}}
    assert run.cofactor == Cofactor(0.0, "set")
    assert run.cofactor.transform() == {"name": "none"}


def test_standardize_is_a_setting_and_a_flag():
    from datanuggets_flow import pick

    assert ClusterSettings().standardize is True
    assert cli_flag("standardize") == "--no-standardize"
    parser = pick._parser()
    assert parser.parse_args([]).standardize is None  # left out: the setting's default
    assert parser.parse_args(["--no-standardize"]).standardize is False
    assert ClusterSettings(standardize=False).check().standardize is False
    for bad in (1, "yes", None):
        with pytest.raises(FlowError) as e:
            ClusterSettings(standardize=bad).check()
        assert (e.value.param, str(e.value)) == (
            "standardize",
            f"standardize is {bad}; it takes true or false",
        )


def test_run_json_records_both_stages(tmp_path):
    settings = ClusterSettings(
        channels=("CD3-A", "CD4-A"), dn_num2=50, k=3, tsne=False, cofactor=COFACTOR
    )
    s = Scaling(np.array([1.25, 2.5]), np.array([0.5, 1.0]), 1234, 2, np.array([0.75, -2.0]))
    channels, labels = ["CD3-A", "CD4-A"], ["CD3 (CD3-A)", "CD4-A"]
    path = state.write_run(
        tmp_path, tmp_path / "gates", settings, [[1], [2]], channels, labels, scaling=s
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["transform"] == {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
    assert record["standardize"] == {
        "mean": [1.25, 2.5],
        "sd": [0.5, 1.0],
        "ddof": 0,
        "cells": 1234,
        "skew": [0.75, -2.0],
    }
    assert record["settings"]["cofactor"] == 6000.0 and record["settings"]["standardize"] is True
    off = ClusterSettings(cofactor=0, standardize=False)
    (tmp_path / "off").mkdir()
    path = state.write_run(tmp_path / "off", tmp_path / "gates", off, [[1]], channels, labels)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert (record["transform"], record["standardize"]) == ({"name": "none"}, False)


def test_a_record_from_before_the_scale_stage_still_loads():
    """run.json's settings from before standardize existed read back with every other setting
    as written."""
    old = ClusterSettings(k=5, cofactor=150.0).to_dict()
    old.pop("standardize")
    s = ClusterSettings.from_dict(json.loads(json.dumps(old)))
    assert (s.k, s.cofactor) == (5, 150.0)
    assert s.check() is s
