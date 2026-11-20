"""The flow run's library steps, which a backend calls without the CLI: gating, the population
choice, the kept cells read file by file into nuggets, their clusters and t-SNE, the tables and
figures a run writes, and the events that carry the lines the CLI prints. None of them prints,
prompts or leaves a pyplot figure open."""

import builtins
import functools
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from datanuggets import RDraws, create_dn, cut_tree, whclust, wkmeans, wmean, wwcss

from datanuggets_flow import finder_peaks
from datanuggets_flow._pipeline import clustering
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.pipeline import (
    Kept,
    Pool,
    PopStats,
    cluster_nuggets,
    cluster_stage,
    gate_files,
    gate_stage,
    make_nuggets,
    parse_selection,
    pops_spec,
    population_stats,
    population_table,
    resolve_channels,
    selection_choices,
    tsne_embedding,
)
from datanuggets_flow.settings import ClusterSettings, GateSettings, cli_flag
from flowcases import (
    COLUMNS,
    DIGESTS,
    FIGURES,
    FLOW,
    LABELS,
    VIEWER,
    digest,
    load_case,
    read_202,
)

PNN = ["FSC-A", "SSC-A", "CD3-A", "CD4-A"]  # the synthetic files' channels
RESULT_FIGURES = sorted(set(FIGURES) - {"local_maxima.png", "gates.png"})  # cluster_stage's
# what the library's TSNE_ARGS holds, written out because the library keeps it private
TSNE_ARGS = {"n_components": 2, "init": "pca", "learning_rate": "auto", "max_iter": 1000}


def _pool(seed=0):
    """A pool as the clustering step gives it: 40 nuggets, the weight-0 ones out of use, cut
    into 3 clusters."""
    rng = np.random.default_rng(seed)
    centers, weights = rng.normal(size=(40, 3)), rng.integers(0, 20, 40).astype(float)
    use = weights > 0
    tree = whclust(centers[use], weights[use])
    cl = np.full(len(centers), -1)
    cl[use] = cut_tree(tree, k=3)
    return Pool(centers, weights, use, tree, cl, 3)


def _files(kept, n=60):
    """Gated files a.fcs, b.fcs, ... of n events each, Pop 1 of file i its first kept[i] events
    and Pop 2 the ten after them, and a reader of their events that records each name it reads."""
    rng = np.random.default_rng(0)
    events, samples, seen = {}, [], []
    for i, k in enumerate(kept):
        name = f"{'abcd'[i]}.fcs"
        events[name] = rng.normal(size=(n, len(PNN)))
        masks = np.zeros((n, 2), dtype=bool)
        masks[:k, 0] = masks[k : k + 10, 1] = True
        samples.append({"path": Path(name), "n_events": n, "pnn": PNN, "masks": masks})

    def read(path):
        seen.append(path.name)
        return events[path.name], list(PNN), [""] * len(PNN)

    return samples, read, seen


def _gated_202():
    """202.fcs gated as datanuggets-flow gates it by default."""
    return gate_files([Path("202.fcs")], GateSettings(), read=read_202)


def _read_202_by_height(path):
    """202.fcs with its scatter channels named FSC-H and SSC-H: the same events, under names the
    default settings don't gate on."""
    events, pnn, pns = read_202(path)
    return events, ["FSC-H", "SSC-H", *pnn[2:]], pns


def test_cluster_nuggets_needs_three_occupied_nuggets():
    with np.load(FLOW / "202_fluor.npz") as data:
        x = data["fluor"][:2, :2].astype(float)
    kept = [Kept(1, "202.fcs", np.arange(len(x)), create_dn(x, dn_num2=2))]
    with pytest.raises(FlowError, match="fewer than 3 occupied nuggets") as e:
        cluster_nuggets(kept, k=2)
    assert e.value.param == "dn_num2"
    assert "increase dn_num2" in str(e.value)
    assert "increase --dn-num2" in e.value.cli(cli_flag)


def test_make_nuggets_reads_each_kept_file_once_in_order():
    """b.fcs keeps nothing and d.fcs one event, too few for nuggets: neither is read."""
    samples, read, seen = _files([20, 20, 20, 1])
    settings = ClusterSettings(dn_num2=5, n_jobs=1, cofactor=6000.0)
    kept = make_nuggets(samples, [[1], [], [1, 2], [1]], PNN[2:], settings, read=read)
    assert seen == ["a.fcs", "c.fcs"]
    assert [(k.number, k.name, len(k.rows)) for k in kept] == [(1, "a.fcs", 20), (3, "c.fcs", 30)]


def test_nothing_kept_raises_before_any_read():
    samples, read, seen = _files([20, 1])
    with pytest.raises(FlowError) as e:
        make_nuggets(samples, [[], [1]], PNN[2:], ClusterSettings(), read=read)
    assert str(e.value) == "no file has cells kept, so there is nothing to cluster"
    assert seen == []


def _kept_202(settings):
    """make_nuggets of 202.fcs's Pop 6 (2,292 cells) with settings, and those cells after the
    Transform stage, as create_dn is to be given them."""
    events, pnn, _ = read_202(None)
    masks = load_case("202").his_masks
    sample = {"path": Path("202.fcs"), "n_events": len(events), "pnn": pnn, "masks": masks}
    (kept,) = make_nuggets([sample], [[6]], pnn[2:], settings, read=read_202)
    rows = np.flatnonzero(masks[:, 5])
    assert (kept.number, kept.name) == (1, "202.fcs")
    assert np.array_equal(kept.rows, rows)
    return kept, np.arcsinh(events[np.ix_(rows, [2, 3, 4])] / settings.cofactor)


def _same_nuggets(got, want):
    for field in ("centers", "weights", "scales", "assignments"):
        assert np.array_equal(getattr(got, field), getattr(want, field)), field


@pytest.mark.parametrize("center_method", ["original", "mean"])
def test_make_nuggets_with_r_draws_equals_create_dn_with_rdraws(center_method):
    """draws "r", the default: each file's nuggets are create_dn's with R's set.seed(seed)
    draws, so create.DN with the same center.method, DN.num1, DN.num2 and seed builds them. The
    int seed's numpy draws build others."""
    settings = ClusterSettings(dn_num2=50, n_jobs=1, cofactor=6000.0, center_method=center_method)
    kept, x = _kept_202(settings)
    args = {"center_method": center_method, "dn_num2": 50, "n_jobs": 1}
    _same_nuggets(kept.dn, create_dn(x, **args, seed=RDraws(settings.seed)))
    numpy = create_dn(x, **args, seed=settings.seed)
    assert not np.array_equal(kept.dn.assignments, numpy.assignments)


@pytest.mark.parametrize("center_method", ["mean", "original"])
def test_make_nuggets_with_numpy_draws_equals_the_int_seed(center_method):
    """draws "numpy", which a run recorded before draws existed loads as: create_dn's own draws
    from the int seed, so such a run builds the nuggets it built then."""
    settings = ClusterSettings(
        dn_num2=50, n_jobs=1, cofactor=6000.0, center_method=center_method, draws="numpy"
    )
    kept, x = _kept_202(settings)
    want = create_dn(x, center_method=center_method, dn_num2=50, n_jobs=1, seed=settings.seed)
    _same_nuggets(kept.dn, want)


def _fake_kept(weights, p=2, seed=0):
    """One file's nuggets as cluster_nuggets reads them: centers drawn at random, the weights
    given, a weight of 0 for a nugget no cell joined."""
    rng = np.random.default_rng(seed)
    weights = np.asarray(weights, dtype=float)
    dn = SimpleNamespace(centers=rng.normal(size=(len(weights), p)), weights=weights)
    return [Kept(1, "a.fcs", np.arange(int(weights.sum())), dn)]


def _no_wkmeans(*args, **kwargs):
    pytest.fail("weighted k-means ran")


def test_wkmeans_needs_two_nuggets_per_cluster(monkeypatch):
    """Nine nuggets in use (a tenth has weight 0) can't make k = 5 clusters of two: the run
    stops naming k and the nuggets it needs before Wkmeans, which would draw partitions forever,
    is called, rather than clustering with a smaller k than asked."""
    monkeypatch.setattr(clustering, "wkmeans", _no_wkmeans)
    kept = _fake_kept([3, 1, 4, 1, 5, 9, 2, 6, 5, 0])
    with pytest.raises(FlowError) as e:
        cluster_nuggets(kept, 5)
    message = str(e.value)
    assert "k = 5" in message and "10" in message and "dn_num2" in message
    assert message == (
        "weighted k-means needs two nuggets in use per cluster: k = 5 needs 10, and the kept "
        "cells fill 9; lower k or increase dn_num2"
    )
    assert e.value.param == "dn_num2"
    assert "--dn-num2" in e.value.cli(cli_flag)


def test_the_draw_cap_becomes_a_flow_error_naming_k(monkeypatch):
    """Wkmeans' ValueError when no start within its cap of random partitions fills every
    cluster, where R would draw forever, stops the run naming k: a lower k or the tree always
    helps, where more nuggets help only near 2k and make a large pool's starts fail more."""
    cap = "none of 1,000 random partitions filled all k = 5 clusters, where R would keep drawing"

    def capped(*args, **kwargs):
        raise ValueError(cap)

    monkeypatch.setattr(clustering, "wkmeans", capped)
    with pytest.raises(FlowError) as e:
        cluster_nuggets(_fake_kept(np.arange(1, 13)), 5)
    assert str(e.value) == (
        f"weighted k-means can't make k = 5 clusters of these 12 nuggets ({cap}); lower k or "
        "use method tree"
    )
    assert e.value.param == "k"
    assert e.value.cli(cli_flag).endswith("lower --k or use method tree")


def test_a_seed_r_refuses_is_not_blamed_on_k(monkeypatch):
    """RDraws refuses a seed beyond R's set.seed range with a ValueError of its own. It is built
    before the try that turns wkmeans' start failures into the k error, so a seed that slips past
    ClusterSettings.check (cluster_nuggets is public) isn't reported as k's fault."""
    monkeypatch.setattr(clustering, "wkmeans", _no_wkmeans)
    with pytest.raises(ValueError, match="not a valid integer") as e:
        cluster_nuggets(_fake_kept(np.arange(1, 13)), 5, seed=2**31)
    assert not isinstance(e.value, FlowError)


def test_weighted_k_means_clusters_the_nuggets_in_use_as_wkmeans_does():
    """method "wkmeans": the nuggets in use, with their weights, clustered by wkmeans with
    num_init starts of up to max_iter rounds on R's set.seed(seed) draws, which is WCluster's
    Wkmeans(centers, k, obs.weights = weights, num.init, max.iterations, seed). A nugget of
    weight 0 has no cluster."""
    kept, _ = _kept_202(ClusterSettings(dn_num2=50, n_jobs=1, cofactor=6000.0))
    pool = cluster_nuggets([kept], 4, num_init=3, max_iter=20, seed=11)
    use = kept.dn.weights > 0
    centers, weights = kept.dn.centers[use], kept.dn.weights[use]
    want = wkmeans(centers, 4, w=weights, num_init=3, max_iter=20, seed=RDraws(11))
    assert pool.tree is None and pool.k == 4
    assert np.array_equal(pool.use, use)
    assert np.array_equal(pool.cl[use], want.labels)
    assert (pool.cl[~use] == -1).all()
    assert pool.wwcss == float(want.total_wwcss)


@pytest.mark.parametrize("method", ["wkmeans", "tree"])
def test_weight_0_nuggets_sit_out_between_the_ones_in_use(method):
    """Nuggets of weight 0 among the ones in use: the clustering sees only the nuggets in use, in
    their order and with their weights, each label goes back to its own nugget, and a weight-0
    nugget gets -1. The test on file 202 can't show this, since all its nuggets have cells."""
    weights = np.array([3, 0, 2, 4, 0, 5, 1, 2, 0, 6, 2, 3], dtype=float)
    kept = _fake_kept(weights)
    pool = cluster_nuggets(kept, 3, method=method, seed=11)
    use = weights > 0
    centers = kept[0].dn.centers[use]
    if method == "wkmeans":
        found = wkmeans(centers, 3, w=weights[use], num_init=10, max_iter=100, seed=RDraws(11))
        _, want = np.unique(found.labels, return_inverse=True)
    else:
        want = cut_tree(whclust(centers, weights[use]), k=3)
    assert (~use).sum() == 3 and len(set(want.tolist())) == 3
    assert np.array_equal(pool.use, use)
    assert np.array_equal(pool.cl[use], want)
    assert (pool.cl[~use] == -1).all()


def test_an_emptied_cluster_is_renumbered_without_gaps(monkeypatch):
    """A cluster weighted k-means leaves empty drops out: the others keep R's order, numbered
    from 0 without a gap, and k is the number left."""
    found = SimpleNamespace(labels=np.array([0, 0, 2, 2, 3, 3, 0, 2]), total_wwcss=np.float64(1.5))
    monkeypatch.setattr(clustering, "wkmeans", lambda *args, **kwargs: found)
    pool = cluster_nuggets(_fake_kept(np.arange(1, 9)), 4)
    assert pool.cl.tolist() == [0, 0, 1, 1, 2, 2, 0, 1]
    assert (pool.k, pool.wwcss) == (3, 1.5)


@pytest.mark.parametrize("method", ["wkmeans", "tree"])
def test_pool_wwcss_is_the_clusters_wwcss(method):
    """Pool.wwcss is the total weighted within-cluster sum of squares of the clustered centers
    in use under their clusters, with their weights, for either method."""
    kept, _ = _kept_202(ClusterSettings(dn_num2=50, n_jobs=1, cofactor=6000.0))
    pool = cluster_nuggets([kept], 3, method=method)
    use = pool.use
    want = wwcss(pool.centers[use], pool.cl[use], pool.weights[use])
    assert isinstance(pool.wwcss, float)
    assert pool.wwcss == pytest.approx(float(want), rel=1e-12)
    assert (pool.tree is None) == (method == "wkmeans")


def test_cluster_nuggets_refuses_an_unknown_method():
    with pytest.raises(ValueError, match="unknown method 'ward'"):
        cluster_nuggets(_fake_kept(np.arange(1, 9)), 2, method="ward")


@pytest.mark.parametrize("change", ["rows", "channels"])
def test_make_nuggets_refuses_a_file_that_changed(change):
    samples, read, _ = _files([20])

    def changed(path):
        events, pnn, pns = read(path)
        return (events[:-1], pnn, pns) if change == "rows" else (events, pnn[::-1], pns)

    with pytest.raises(FlowError, match="a.fcs isn't the file that was gated"):
        make_nuggets(samples, [[1]], PNN[2:], ClusterSettings(cofactor=6000.0), read=changed)


def test_population_table_keeps_the_cli_format():
    fsc, ssc = np.array([100.0, 300.0, 5e5, 7e5]), np.array([10.0, 30.0, 2e5, 4e5])
    masks = np.array([[1, 0], [1, 0], [0, 0], [0, 0]], dtype=bool)  # Pop 2 is empty
    stats = population_stats(fsc, ssc, masks, np.array([[3, 4], [5, 6]]))
    assert stats == [
        PopStats(1, 2, 50.0, 200.0, 20.0, (3, 4)),
        PopStats(2, 0, 0.0, 0.0, 0.0, (5, 6)),
    ]
    rows = [PopStats(1, 12345, 24.69, 412345.6, 98765.4, (3, 4)), stats[1]]
    assert population_table(rows, "FSC-A", "SSC-A") == [
        "  Pop 1:    12,345 events (24.7%), median FSC-A   412,346, SSC-A    98,765",
        "  Pop 2:         0 events ( 0.0%), median FSC-A         0, SSC-A         0",
    ]


def test_selection_choices_gives_one_for_all_or_one_per_file():
    """The rule on how many choices --pops gives, which the CLI checks before any file is read
    and parse_selection once the populations are counted."""
    assert selection_choices("1,2", 3) == ["1,2"]
    assert selection_choices("1;none;1,2", 3) == ["1", "none", "1,2"]
    with pytest.raises(FlowError) as e:
        selection_choices("1;2", 3)
    assert e.value.param == "pops"
    assert e.value.cli(cli_flag) == (
        "--pops gives 2 choices for 3 files; give one for all of them or one per file, "
        "separated by ;"
    )


def test_parse_selection_one_for_all_or_one_per_file():
    assert parse_selection("1,2", [3, 3, 3]) == [[1, 2]] * 3
    assert parse_selection("1;none;1,2", [2, 2, 2]) == [[1], [], [1, 2]]
    with pytest.raises(FlowError, match="pops gives 2 choices for 3 files"):
        parse_selection("1;2", [2, 2, 2])
    with pytest.raises(FlowError) as e:
        parse_selection("5", [4])
    assert str(e.value) == "pops: there is no Pop 5; this file has Pop 1 to Pop 4"


def test_pops_spec_round_trips():
    chosen = [[1, 2], [], [1]]
    assert pops_spec(chosen) == "1,2;none;1"
    assert parse_selection(pops_spec(chosen), [2, 2, 2]) == chosen


def test_resolve_channels_default_rule_and_errors():
    pnn = ["FSC-A", "SSC-A", "FSC-H", "CD3-A", "CD4-A", "Time"]
    a = {"path": Path("a.fcs"), "pnn": pnn, "pns": ["", "", "", "CD3", "", ""]}
    b = {"path": Path("b.fcs"), "pnn": pnn[:4], "pns": [""] * 4}
    assert resolve_channels([a], ClusterSettings()) == (
        ["CD3-A", "CD4-A"],
        ["CD3 (CD3-A)", "CD4-A"],
    )
    with pytest.raises(FlowError) as e:
        resolve_channels([a, b], ClusterSettings())
    assert str(e.value) == "b.fcs has no channel CD4-A; its channels: FSC-A, SSC-A, FSC-H, CD3-A"
    # check_channels' rule is tested on given lists through ClusterSettings.check; the list the
    # default rule gives is known only here
    one = {"path": Path("one.fcs"), "pnn": ["FSC-A", "SSC-A", "CD3-A"], "pns": [""] * 3}
    with pytest.raises(FlowError, match="at least two distinct fluorescence channels") as e:
        resolve_channels([one], ClusterSettings())
    assert e.value.param == "channels"


def test_resolve_channels_excludes_and_refuses_unknown_names():
    pnn = ["FSC-A", "SSC-A", "CD3-A", "CD4-A", "Live-A"]
    a = {"path": Path("a.fcs"), "pnn": pnn, "pns": [""] * 5}
    assert resolve_channels([a], ClusterSettings(exclude_channels=("Live-A",)))[0] == pnn[2:4]
    with pytest.raises(FlowError) as e:
        resolve_channels([a], ClusterSettings(exclude_channels=("CD9-A",)))
    assert e.value.param == "exclude_channels"
    assert e.value.cli(cli_flag) == (
        "--exclude-channels names CD9-A, which a.fcs doesn't have; its channels: "
        "FSC-A, SSC-A, CD3-A, CD4-A, Live-A"
    )
    with pytest.raises(FlowError, match="at least two distinct"):
        resolve_channels([a], ClusterSettings(exclude_channels=("Live-A", "CD4-A")))


@pytest.mark.parametrize(
    ("names", "settings", "param", "message"),
    [
        (
            ["a.fcs", "b.fcs", "c.fcs"],
            GateSettings(t11=(22, 20)),
            "t11",
            "t11 gives 2 values for 3 files; give one, or one per file",
        ),
        (
            ["a.fcs"],
            GateSettings(t11=(-5,)),
            "t11",
            "t11 is -5; it takes a positive distance in grid cells",
        ),
        (
            ["a.fcs"],
            GateSettings(disc="bogus"),
            "disc",
            "disc is 'bogus'; it takes reference or peak",
        ),
        ([], GateSettings(), None, "no files to gate"),
    ],
)
def test_gate_stage_checks_its_settings_and_files_before_any_read(
    tmp_path, names, settings, param, message
):
    """A backend calls the stages without the CLI's checks, so a bad setting or no files at all
    stops gate_files, and gate_stage through it, with a FlowError before a file is read."""
    seen = []

    def read(path):
        seen.append(path.name)
        return read_202(path)

    paths = [Path(name) for name in names]
    for stage in (
        lambda: gate_files(paths, settings, read=read),
        lambda: gate_stage(paths, tmp_path, settings, read=read),
    ):
        with pytest.raises(FlowError) as e:
            stage()
        assert (e.value.param, str(e.value)) == (param, message)
    assert seen == []
    assert list(tmp_path.iterdir()) == []


def test_gate_files_gates_on_the_scatter_channels_it_is_given():
    """--fsc and --ssc choose the channels the finder gates on and the table names: the same events
    under other names give the same masks and the same lines, with those names in them."""
    (want,) = _gated_202()
    settings = GateSettings(fsc="FSC-H", ssc="SSC-H")
    (got,) = gate_files([Path("202.fcs")], settings, read=_read_202_by_height)
    assert np.array_equal(got["masks"], want["masks"])
    named = [line.replace("FSC-A", "FSC-H").replace("SSC-A", "SSC-H") for line in want["table"]]
    assert got["table"] == named
    assert all("median FSC-H" in line and ", SSC-H " in line for line in got["table"])


@pytest.mark.parametrize(
    ("settings", "param", "channel"),
    [(GateSettings(), "fsc", "FSC-A"), (GateSettings(fsc="FSC-H"), "ssc", "SSC-A")],
)
def test_gate_files_refuses_a_file_without_a_scatter_channel(settings, param, channel):
    pnn = _read_202_by_height(None)[1]
    with pytest.raises(FlowError) as e:
        gate_files([Path("202.fcs")], settings, read=_read_202_by_height)
    assert e.value.param == param
    assert str(e.value) == f"202.fcs has no channel {channel}; its channels: {', '.join(pnn)}"


@pytest.mark.parametrize(
    ("kept", "chosen", "settings", "param", "message"),
    [
        ([20], [[1]], ClusterSettings(k=0), "k", "k is 0; it takes 1 or more clusters"),
        ([], [], ClusterSettings(), None, "no gated files to cluster"),
        (
            [20, 20, 20],
            [[1], [1]],
            ClusterSettings(),
            "pops",
            "pops gives 2 choices for 3 files; give one per file",
        ),
    ],
)
def test_cluster_stage_checks_its_settings_and_choices_before_any_read(
    tmp_path, kept, chosen, settings, param, message
):
    """A bad setting, no samples, or a choice list that doesn't give one choice per sample (which
    the tables would zip short) stops cluster_stage before it reads a file or writes one."""
    samples, read, seen = _files(kept)
    with pytest.raises(FlowError) as e:
        cluster_stage(samples, chosen, tmp_path, settings, read=read)
    assert (e.value.param, str(e.value)) == (param, message)
    assert seen == []
    assert list(tmp_path.iterdir()) == []


def test_library_stages_never_print_or_prompt(tmp_path, monkeypatch, capsys):
    import matplotlib.pyplot as plt

    monkeypatch.setattr(builtins, "input", lambda *args: pytest.fail("the library asked"))
    plt.close("all")
    settings = ClusterSettings(dn_num2=50, k=3, n_jobs=1)
    cluster_stage(_gated_202(), [[6]], tmp_path, settings, read=read_202)
    assert capsys.readouterr() == ("", "")
    assert plt.get_fignums() == []


def test_cluster_stage_alone_writes_the_one_shot_tables(tmp_path):
    # standardize off and cofactor 6000: the tables pinned before the Scale stage and the auto
    # cofactors
    settings = ClusterSettings(dn_num2=50, k=3, n_jobs=1, standardize=False, cofactor=6000.0)
    run = cluster_stage(_gated_202(), [[1]], tmp_path, settings, read=read_202)
    assert {name: digest(tmp_path / name) for name in COLUMNS} == DIGESTS
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == sorted([*COLUMNS, *VIEWER, *RESULT_FIGURES])
    assert sorted(p.name for p in run.files) == written
    assert run.labels == LABELS
    assert run.tsne.shape == (run.pool.use.sum(), 2)


def test_stage_events_carry_the_cli_lines(tmp_path):
    """The gate event's lines are the ones the CLI printed before the steps moved here, from the
    same f-string; the clustering's events follow in the order the CLI printed them."""
    events = []
    samples = gate_files([Path("202.fcs")], GateSettings(), read=read_202, on_event=events.append)
    case = load_case("202")
    # the masks the gate made, not the reference's: an event on a hull's edge falls either way by
    # platform (one does on macOS arm64), and test_flow_gate holds the masks to the reference
    table = [
        f"  Pop {j + 1}: {m.sum():>9,} events ({100 * m.mean():4.1f}%), median FSC-A "
        f"{np.median(case.fsc[m]) if m.any() else 0:>9,.0f}, SSC-A "
        f"{np.median(case.ssc[m]) if m.any() else 0:>9,.0f}"
        for j, m in enumerate(samples[0]["masks"].T)
    ]
    fp = finder_peaks(case.fsc, case.ssc)
    (gate,) = events
    assert gate[:3] == ("gate", 1, 1)
    assert gate.message == "\n".join(
        [
            "\nFile 1, 202.fcs: 50,000 events",
            *table,
            f"  {len(fp.candidates)} local maxima, {len(fp.peaks)} kept as peaks",
        ]
    )
    assert gate.data["events"] == 50_000
    assert gate.data["populations"] == samples[0]["stats"]
    settings = ClusterSettings(dn_num2=50, k=3, n_jobs=1, tsne=False, cofactor=6000.0)
    run = cluster_stage(samples, [[6]], tmp_path, settings, read=read_202, on_event=events.append)
    assert [(e.stage, e.file) for e in events] == [
        ("gate", 1),
        ("select", None),
        ("transform", None),
        ("scale", 1),
        ("scale", None),
        ("nuggets", 1),
        ("cluster", None),
    ]
    assert events[1].message == "\n" + run.selection.to_string(index=False)
    assert events[2].message == (
        "\nTransform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set"
    )
    assert (events[3].message, events[3].data) == ("", {"cells": 2_292})
    assert events[4].message.startswith(
        "Scale: every channel to mean 0 and SD 1, pooled over 1 files' 2,292 cells\n"
    )
    assert events[5].message == f"File 1, 202.fcs: 2,292 cells, {run.kept[0].dn.n_nuggets} nuggets"
    assert events[6].message.startswith(
        "\nPercent of each file's kept cells in each cluster:\n"
        "(columns are file numbers; selection.csv names the files)\nfile_number"
    )


def test_cluster_stage_without_tsne_never_imports_sklearn(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.manifold", None)
    settings = ClusterSettings(dn_num2=50, k=3, n_jobs=1, tsne=False)
    run = cluster_stage(_gated_202(), [[6]], tmp_path, settings, read=read_202)
    assert run.tsne is None
    assert "clusters_tsne.png" not in {p.name for p in tmp_path.iterdir()}


def test_tsne_gets_the_pinned_arguments_and_repeats_for_a_seed(monkeypatch):
    """The arguments that shape the picture are TSNE_ARGS'; perplexity and the seed are the
    settings', the perplexity capped at (n - 1) / 3 for n nuggets."""
    from sklearn.manifold import TSNE

    seen, init = [], TSNE.__init__

    @functools.wraps(init)  # scikit-learn reads the parameters from __init__'s signature
    def spy(self, *args, **kwargs):
        seen.append(kwargs)
        init(self, *args, **kwargs)

    monkeypatch.setattr(TSNE, "__init__", spy)
    x = np.random.default_rng(0).normal(size=(40, 3))
    capped = ClusterSettings(tsne_perplexity=50.0, tsne_seed=7)
    first, again = tsne_embedding(x, capped), tsne_embedding(x, capped)
    tsne_embedding(x, ClusterSettings(tsne_perplexity=5.0))
    assert seen == [
        {**TSNE_ARGS, "perplexity": 13.0, "random_state": 7},
        {**TSNE_ARGS, "perplexity": 13.0, "random_state": 7},
        {**TSNE_ARGS, "perplexity": 5.0, "random_state": 0},
    ]
    assert first.shape == (40, 2)
    assert np.array_equal(first, again)


def test_result_figures_leave_no_pyplot_figures(tmp_path, close_figures):
    import matplotlib.pyplot as plt
    import pandas as pd
    from matplotlib.figure import Figure

    from datanuggets_flow.figures import (
        gates_figure,
        local_maxima_figure,
        result_figures,
        save_figures,
    )

    case = load_case("202")
    sample = {
        "path": Path("202.fcs"),
        "fsc": case.fsc,
        "ssc": case.ssc,
        "masks": case.his_masks,
        "peaks": finder_peaks(case.fsc, case.ssc),
    }
    pool = _pool()
    use = pool.use
    centers = pd.DataFrame(
        wmean(pool.centers[use], pool.cl[use], pool.weights[use]), columns=LABELS
    )
    xy = np.random.default_rng(1).normal(size=(use.sum(), 2))
    plt.close("all")
    figs = {
        "local_maxima.png": local_maxima_figure([sample] * 3),  # two rows, the fourth panel hidden
        "gates.png": gates_figure([sample]),
        **result_figures(pool, centers, LABELS, 6000.0, xy),
    }
    assert plt.get_fignums() == []
    assert all(isinstance(fig, Figure) for fig in figs.values())
    assert list(figs) == [
        "local_maxima.png",
        "gates.png",
        "dendrogram.png",
        "clusters_pca.png",
        "clusters_tsne.png",
        "cluster_centers.png",
    ]
    assert sum(not ax.get_visible() for ax in figs["local_maxima.png"].axes) == 1
    no_tsne = result_figures(pool, centers, LABELS, 0, None)
    assert list(no_tsne) == ["dendrogram.png", "clusters_pca.png", "cluster_centers.png"]
    saved = save_figures({"gates.png": figs["gates.png"]}, tmp_path, 110)
    assert saved == [tmp_path / "gates.png"]
    assert saved[0].read_bytes().startswith(b"\x89PNG")
    assert plt.get_fignums() == []
