"""datanuggets-flow in two stages: --gates-only gates the files into a gate folder and stops, and
--from-gates asks over that folder's figures and clusters. The two give the one-shot run's tables.
The second clusters the saved masks without gating again, checks everything before it asks, makes
its folder only after, and never writes into the gate folder. Each mode refuses the flags it can't
use before anything is read or made. The FCS files are empty stand-ins, read as 202 by a patched
read_fcs."""

import csv
import json
import sys

import numpy as np
import pytest

from datanuggets_flow import gate, pick, pipeline, state
from datanuggets_flow._pick import prompt as pick_prompt
from datanuggets_flow._pipeline import gating
from datanuggets_flow.pick import main
from flowcases import (
    COLUMNS,
    DIGESTS,
    DIGESTS_3,
    FIGURES,
    VIEWER,
    VIEWER_2D,
    digest,
    read_202,
)

# what the command says when a package it draws or tabulates with can't be imported
MISSING = "datanuggets-flow needs matplotlib, pandas and scikit-learn: pip install datanuggets-flow"


@pytest.fixture
def staged(monkeypatch, close_figures):
    """Files read as 202's, and a prompt that fails the test unless a test answers it."""
    monkeypatch.setattr(pick, "read_fcs", read_202)
    monkeypatch.setattr(pick_prompt, "_live_input", lambda *args: pytest.fail("asked"))


def _gates_only(tmp_path, *flags, names=("202.fcs",)):
    """--gates-only on stand-in files in tmp_path / "in"; its gate folder, tmp_path / "gates"."""
    folder, gates = tmp_path / "in", tmp_path / "gates"
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(b"")
    main([str(folder), "--gates-only", "--no-show", "--out", str(gates), *flags])
    return gates


def _snapshot(folder):
    """Each file's bytes and modification time."""
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}


def _asked(monkeypatch, answer):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(pick_prompt, "_live_input", answer)


@pytest.mark.parametrize("asked", [False, True], ids=["pops", "asked"])
def test_staged_run_reproduces_the_one_shot_tables(tmp_path, monkeypatch, staged, asked):
    """The tables are the one-shot run's, the run folder holds its files and run.json, the gate
    figures in it are the gate folder's bytes, and the gate folder is left as it was."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    assert sorted(p.name for p in gates.iterdir()) == sorted(state.GATE_FILES)
    before = _snapshot(gates)
    argv = ["--from-gates", str(gates), "--no-show", "--out", str(out), "--dn-num2", "50"]
    argv.append("--no-standardize")  # the tables pinned before the Scale stage
    argv += ["--cofactor", "6000"]  # and before the cofactor was picked from the headers
    if asked:
        _asked(monkeypatch, lambda prompt, plt, show: "1")
    else:
        argv += ["--pops", "1"]
    main([*argv, "--k", "3"])
    written = sorted(p.name for p in out.iterdir())
    assert written == sorted([*COLUMNS, *VIEWER, *FIGURES, "run.json"])
    assert {name: digest(out / name) for name in COLUMNS} == DIGESTS
    for name in ("local_maxima.png", "gates.png"):
        assert (out / name).read_bytes() == before[name][0], name
    assert _snapshot(gates) == before
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (run["gates"], run["pops"], run["settings"]["k"]) == (str(gates), "1", 3)
    assert run["transform"] == {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
    assert run["standardize"] is False and run["settings"]["standardize"] is False


def test_from_gates_scales_by_default_and_run_json_records_the_stats(tmp_path, staged, capsys):
    """Without --no-standardize the run scales every channel by the pooled stats, prints both
    stages, and run.json records the mean and SD it scaled by; the tables stay in arcsinh units."""
    import pandas as pd

    gates, out = _gates_only(tmp_path, names=("a.fcs", "b.fcs")), tmp_path / "out"
    capsys.readouterr()
    argv = ["--from-gates", str(gates), "--out", str(out), "--pops", "1;6", *CLUSTER[2:]]
    main([*argv, "--cofactor", "6000"])  # the arcsinh(x / 6000) the stats below are made on
    printed = capsys.readouterr().out
    events, _, _ = read_202(None)
    x = np.arcsinh(events[:, 2:] / 6000)
    folder = state.load_gates(gates)
    pooled = np.vstack([x[s["masks"][:, p]] for s, p in zip(folder.samples, (0, 5))])
    pool = f"Scale: every channel to mean 0 and SD 1, pooled over 2 files' {len(pooled):,} cells"
    # the Scale stage's per-file progress events print nothing, not a blank line each
    transform = "Transform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set"
    assert f"\n{transform}\n{pool}\n" in printed
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["transform"] == {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
    assert set(run["standardize"]) == {"mean", "sd", "ddof", "cells", "skew"}
    assert (run["standardize"]["ddof"], run["standardize"]["cells"]) == (0, len(pooled))
    np.testing.assert_allclose(run["standardize"]["mean"], pooled.mean(axis=0), rtol=1e-12)
    np.testing.assert_allclose(run["standardize"]["sd"], pooled.std(axis=0), rtol=1e-12)
    centers = pd.read_csv(out / "cluster_centers.csv")
    assert centers.iloc[:, 1:].to_numpy().min() > pooled.min() - 1e-9


def test_run_json_records_the_clustering(tmp_path, monkeypatch, staged):
    """A default run's run.json says how it clustered: weighted k-means, k as asked and as used,
    the nuggets clustered and those dropped for weight 0 (every pooled nugget is one or the
    other), the total WWCSS, and the R calls that build the same nuggets and clusters."""
    runs, stage = [], pipeline.cluster_stage

    def spy(*args, **kwargs):
        runs.append(stage(*args, **kwargs))
        return runs[-1]

    monkeypatch.setattr(pipeline, "cluster_stage", spy)
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    main(["--from-gates", str(gates), "--out", str(out), "--jobs", "1", *CLUSTER])
    (run,) = runs
    pool = run.pool
    record = json.loads((out / "run.json").read_text(encoding="utf-8"))
    clustering = record["clustering"]
    assert (clustering["method"], clustering["k"], clustering["k_used"]) == ("wkmeans", 3, pool.k)
    assert pool.k == 3
    assert clustering["nuggets_clustered"] == int(pool.use.sum())
    assert clustering["nuggets_clustered"] + clustering["nuggets_dropped"] == len(pool.centers)
    assert clustering["total_wwcss"] == pool.wwcss
    r = clustering["r"]
    for part in ("k = 3", "obs.weights = weights", "num.init = 10", "max.iterations = 100"):
        assert part in r["cluster"], part
    assert r["cluster"].startswith("Wkmeans(centers, ") and "seed = 291102" in r["cluster"]
    assert 'center.method = "original"' in r["create.DN"]
    assert "DN.num2 = 50" in r["create.DN"] and "seed = 291102" in r["create.DN"]
    settings = record["settings"]
    assert (settings["method"], settings["center_method"], settings["draws"]) == (
        "wkmeans",
        "original",
        "r",
    )


def test_staged_three_file_run_reproduces_the_three_file_tables(tmp_path, staged):
    """The three-file one-shot run's gate flags go to --gates-only, its clustering flags to
    --from-gates."""
    gate_flags = ["--t11", "22,20,18", "--t21", "0.25,0.25,0.4", "--disc", "peak"]
    gates = _gates_only(tmp_path, *gate_flags, names=("a.fcs", "b.fcs", "c.fcs"))
    out = tmp_path / "out"
    argv = ["--from-gates", str(gates), "--no-show", "--out", str(out), "--pops", "1;none;1,2"]
    channels = "FJComp-BV510-A, FJComp-Spark Blue-A"
    argv.append("--no-standardize")  # the tables pinned before the Scale stage
    main([*argv, "--cofactor", "0", "--channels", channels, "--dn-num2", "40", "--k", "4"])
    tables = sorted(DIGESTS_3)
    written = sorted(p.name for p in out.iterdir())
    assert written == sorted([*tables, *VIEWER_2D, *FIGURES, "run.json"])
    assert {name: digest(out / name) for name in tables} == DIGESTS_3


# --from-gates on the gate folder's file, with what the tests of the stored masks don't need off
CLUSTER = ["--pops", "1", "--no-show", "--dn-num2", "50", "--k", "3", "--no-tsne"]


def test_from_gates_never_runs_the_finder(tmp_path, monkeypatch, staged):
    """The masks in the gate folder are the gates, so the clustering stage never gates again: a
    finder that changed since would otherwise cluster populations other than the ones chosen."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    monkeypatch.setattr(gate, "f_plot", lambda *args, **kwargs: pytest.fail("gated again"))
    monkeypatch.setattr(gating, "gate_peaks", lambda *args, **kwargs: pytest.fail("gated again"))
    main(["--from-gates", str(gates), "--out", str(out), *CLUSTER])
    assert (out / "run.json").is_file()


def test_from_gates_keeps_the_events_its_saved_masks_choose(tmp_path, staged):
    """The saved masks choose the events by row: with Pop 1 cut to its first 500 events in
    gates.npz, those are the events kept and clustered, where gating again would keep them all."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    (entry,) = json.loads((gates / "gates.json").read_text(encoding="utf-8"))["files"]
    with np.load(gates / "gates.npz") as saved:
        arrays = dict(saved)
    masks = np.unpackbits(arrays["masks_1"], axis=0, count=entry["n_events"]).astype(bool)
    rows = np.flatnonzero(masks[:, 0])[:500]
    assert masks[:, 0].sum() > len(rows) == 500
    masks[:, 0] = False
    masks[rows, 0] = True
    arrays["masks_1"] = np.packbits(masks, axis=0)
    np.savez(gates / "gates.npz", **arrays)
    main(["--from-gates", str(gates), "--out", str(out), *CLUSTER])
    with open(out / "selection.csv", newline="") as f:
        (selected,) = csv.DictReader(f)
    assert (selected["events"], selected["kept"]) == (str(entry["n_events"]), "500")
    with open(out / "events_1.csv", newline="") as f:
        assert [int(row["event0"]) for row in csv.DictReader(f)] == rows.tolist()


def test_from_gates_asks_after_both_figures_and_before_the_run_folder(
    tmp_path, monkeypatch, staged, capsys
):
    """At the prompt the gate folder's figures are there to choose from, and the run folder isn't:
    stopping at the prompt writes nothing."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    before, seen = _snapshot(gates), []

    def cancel(prompt, plt, show):
        seen.append((sorted(p.name for p in gates.iterdir()), out.exists()))
        raise SystemExit("\ncancelled; nothing was clustered")

    _asked(monkeypatch, cancel)
    capsys.readouterr()
    with pytest.raises(SystemExit, match="cancelled"):
        main(["--from-gates", str(gates), "--no-show", "--out", str(out)])
    assert seen == [(sorted(state.GATE_FILES), False)]
    assert not out.exists()
    assert _snapshot(gates) == before
    printed = capsys.readouterr().out
    assert f"drawn in {gates / 'local_maxima.png'}" in printed
    assert f"drawn in {gates / 'gates.png'}" in printed
    assert "note:" not in printed  # gated under the versions installed now


def test_from_gates_notes_other_package_versions_and_goes_on(tmp_path, monkeypatch, staged, capsys):
    """A gate folder made under other package versions is used, not refused, since its masks are
    the gates, but the run names the packages that differ, as they can move the clustering."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    made = state._versions()
    monkeypatch.setattr(state, "_versions", lambda: made | {"numpy": "0.0"})
    capsys.readouterr()
    argv = ["--from-gates", str(gates), "--pops", "1", "--no-show", "--out", str(out)]
    main([*argv, "--dn-num2", "50", "--k", "3"])
    assert capsys.readouterr().out.splitlines()[0] == (
        f"note: {gates} was gated with numpy {made['numpy']} (now 0.0); its masks are used as saved"
    )
    assert (out / "run.json").is_file()
    assert not (out / "INCOMPLETE.txt").exists()


def test_gates_only_writes_no_tables_and_never_asks(tmp_path, monkeypatch, staged, capsys):
    """It ends with the one-shot run's lines for the two gate figures, then where the gates are
    and the command that goes on from them."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    gates = _gates_only(tmp_path)
    assert sorted(p.name for p in gates.iterdir()) == sorted(state.GATE_FILES)
    lines = capsys.readouterr().out.splitlines()
    assert lines[-6:] == [
        "",
        f"The local maxima and each Pop's peak are drawn in {gates / 'local_maxima.png'}",
        f"The populations are drawn in {gates / 'gates.png'}",
        "",
        f"Gates are in {gates.resolve()}",
        f'Choose populations and cluster with: datanuggets-flow --from-gates "{gates.resolve()}"',
    ]


def test_gates_json_records_the_thresholds_as_given(tmp_path, staged):
    """One --t11 for every file is recorded once in settings, as it was given, and each file's
    entry holds the value it was gated with."""
    gates = _gates_only(tmp_path, "--t11", "20", names=("a.fcs", "b.fcs"))
    record = json.loads((gates / "gates.json").read_text(encoding="utf-8"))
    assert (record["settings"]["t11"], record["settings"]["t21"]) == ([20.0], [0.25])
    assert [(f["t11"], f["t21"]) for f in record["files"]] == [(20.0, 0.25), (20.0, 0.25)]


GATES = "{tmp}/gates"  # a gate folder that doesn't exist: no rule may look for it
# each mode rule, a command line that breaks it and what it says
MISPLACED = {
    "no input": ([], "give FCS files or folders, or --from-gates GATES"),
    "paths with --from-gates": (
        ["{tmp}/202.fcs", "--from-gates", GATES],
        "--from-gates reads the FCS files its gate folder records; give no FCS paths",
    ),
    "gate flag with --from-gates": (
        ["--from-gates", GATES, "--t11", "20"],
        (
            f"--t11 sets the gate stage, and --from-gates reuses the gates in {GATES}; run "
            "--gates-only again to change it"
        ),
    ),
    "clustering flag with --gates-only": (
        ["{tmp}/202.fcs", "--gates-only", "--dn-num2", "50"],
        "--dn-num2 sets the clustering stage, which --gates-only stops before",
    ),
    "pops with --gates-only": (
        ["{tmp}/202.fcs", "--gates-only", "--pops", "1"],
        "--pops sets the clustering stage, which --gates-only stops before",
    ),
    "no-tsne with --gates-only": (
        ["{tmp}/202.fcs", "--gates-only", "--no-tsne"],
        "--no-tsne sets the clustering stage, which --gates-only stops before",
    ),
    "no-standardize with --gates-only": (
        ["{tmp}/202.fcs", "--gates-only", "--no-standardize"],
        "--no-standardize sets the clustering stage, which --gates-only stops before",
    ),
    "t-SNE flag with --no-tsne": (
        ["--from-gates", GATES, "--no-tsne", "--tsne-seed", "1"],
        "--tsne-seed has no effect with --no-tsne",
    ),
}


@pytest.mark.parametrize("case", MISPLACED)
def test_misplaced_flags_are_refused_before_anything_happens(tmp_path, monkeypatch, case):
    (tmp_path / "202.fcs").write_bytes(b"")
    monkeypatch.setattr(pick, "read_fcs", lambda path: pytest.fail("read before the mode rules"))
    argv, message = MISPLACED[case]
    argv = [a.format(tmp=tmp_path) for a in argv]
    with pytest.raises(SystemExit) as e:
        main([*argv, "--no-show", "--out", str(tmp_path / "out")])
    assert e.value.code == message.format(tmp=tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["202.fcs"]


@pytest.mark.parametrize("mode", ["one-shot", "from-gates"])
def test_an_empty_pops_asks_in_both_modes(tmp_path, monkeypatch, staged, mode):
    """--pops "", as a script that expands an unset variable gives it, counts as no --pops in
    either mode that clusters, so both ask over the same populations rather than one asking and
    the other refusing it."""
    if mode == "one-shot":
        (tmp_path / "202.fcs").write_bytes(b"")
        argv = [str(tmp_path / "202.fcs")]
    else:
        argv = ["--from-gates", str(_gates_only(tmp_path))]
    seen = []

    def cancel(prompt, plt, show):
        seen.append(prompt)
        raise SystemExit("\ncancelled; nothing was clustered")

    _asked(monkeypatch, cancel)
    with pytest.raises(SystemExit, match="cancelled"):
        main([*argv, "--pops", "", "--no-show", "--out", str(tmp_path / "out")])
    assert len(seen) == 1 and seen[0].startswith("Keep which, Pop 1 to ")


def test_an_empty_pops_is_no_clustering_flag_with_gates_only(tmp_path, staged):
    """For the same reason --gates-only takes --pops "" as no --pops, and saves its gates."""
    gates = _gates_only(tmp_path, "--pops", "")
    assert sorted(p.name for p in gates.iterdir()) == sorted(state.GATE_FILES)


@pytest.mark.parametrize("mode", ["one-shot", "gates-only", "from-gates"])
def test_every_mode_names_the_missing_packages_without_matplotlib(tmp_path, monkeypatch, mode):
    """Without matplotlib each mode stops on the missing-packages message before it reads a file
    or a gate folder, even after the figures module was imported, as other tests import it."""
    for name in [m for m in sys.modules if m.startswith("matplotlib.")] + ["matplotlib"]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.delitem(sys.modules, "datanuggets_flow.figures", raising=False)
    argv = {
        "one-shot": [str(tmp_path / "202.fcs")],
        "gates-only": [str(tmp_path / "202.fcs"), "--gates-only"],
        "from-gates": ["--from-gates", str(tmp_path / "gates")],
    }[mode]
    with pytest.raises(SystemExit) as e:
        main([*argv, "--no-show"])
    assert e.value.code == MISSING


# the packages a run needs only once it clusters, as the modules that block them
CLUSTERING_PACKAGES = {"pandas": ("pandas",), "scikit-learn": ("sklearn", "sklearn.manifold")}


@pytest.mark.parametrize("package", CLUSTERING_PACKAGES)
@pytest.mark.parametrize("mode", ["one-shot", "from-gates"])
def test_a_clustering_mode_names_the_missing_packages_without_pandas_or_sklearn(
    tmp_path, monkeypatch, staged, mode, package
):
    """The tables need pandas and the t-SNE scikit-learn, so a run that clusters without one stops
    on the missing-packages message before it reads a file or makes its folder, rather than once
    the files are gated and the populations chosen, leaving the folder marked incomplete."""
    if mode == "one-shot":
        (tmp_path / "202.fcs").write_bytes(b"")
        argv = [str(tmp_path / "202.fcs")]
    else:
        argv = ["--from-gates", str(_gates_only(tmp_path))]
    for name in CLUSTERING_PACKAGES[package]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(pick, "read_fcs", lambda path: pytest.fail("file read"))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        main([*argv, "--pops", "1", "--no-show", "--out", str(out)])
    assert e.value.code == MISSING
    assert not out.exists()


def test_gates_only_needs_neither_pandas_nor_sklearn(tmp_path, monkeypatch, staged):
    """--gates-only writes no table and draws no t-SNE, so it saves its gates without either."""
    for names in CLUSTERING_PACKAGES.values():
        for name in names:
            monkeypatch.setitem(sys.modules, name, None)
    gates = _gates_only(tmp_path)
    assert sorted(p.name for p in gates.iterdir()) == sorted(state.GATE_FILES)


def test_gates_only_and_from_gates_are_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path), "--gates-only", "--from-gates", str(tmp_path / "gates")])
    assert e.value.code == 2
    assert "--from-gates: not allowed with argument --gates-only" in capsys.readouterr().err


def test_from_gates_refuses_a_changed_fcs_file(tmp_path, monkeypatch, staged):
    """The masks choose events by row, so a file that changed since it was gated is refused before
    the prompt, the run folder never made."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    fcs = tmp_path / "in" / "202.fcs"
    fcs.write_bytes(b"x")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(SystemExit) as e:
        main(["--from-gates", str(gates), "--no-show", "--out", str(out)])
    assert e.value.code.startswith(f"{fcs} isn't the file that was gated: it has 1 bytes")
    assert not out.exists()


def test_from_gates_refuses_an_existing_out_before_the_prompt(tmp_path, monkeypatch, staged):
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    out.mkdir()
    (out / "events_1.csv").write_bytes(b"earlier events")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(SystemExit) as e:
        main(["--from-gates", str(gates), "--no-show", "--out", str(out)])
    assert e.value.code == f"output path already exists: {out}; choose a new --out folder"
    assert [p.name for p in out.iterdir()] == ["events_1.csv"]
    assert (out / "events_1.csv").read_bytes() == b"earlier events"


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--channels", "CD9-A,CD3-A"], "202.fcs has no channel CD9-A; its channels: "),
        (
            ["--exclude-channels", "CD9-A"],
            "--exclude-channels names CD9-A, which 202.fcs doesn't have; its channels: ",
        ),
        (["--channels", "CD9-A,CD3-A", "--pops", "1"], "202.fcs has no channel CD9-A; "),
        (["--pops", "1;1"], "--pops gives 2 choices for 1 files; "),
    ],
    ids=["channels", "exclude-channels", "channels-with-pops", "pops"],
)
def test_from_gates_refuses_a_bad_channel_or_pops_before_the_prompt(
    tmp_path, monkeypatch, staged, flags, message
):
    """A channel the gated files don't have, or a --pops that doesn't fit their count, is refused
    against the gate folder before the populations are asked and before the run folder is made.
    With --pops there is no prompt, so the folder is what shows the channels were checked first:
    checked inside it, they would leave it marked incomplete with the gate figures copied in."""
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    with pytest.raises(SystemExit) as e:
        main(["--from-gates", str(gates), "--no-show", "--out", str(out), *flags])
    assert e.value.code.startswith(message)
    assert not out.exists()


def test_failed_from_gates_run_is_marked_and_leaves_the_gates_alone(
    tmp_path, monkeypatch, staged, capsys
):
    gates, out = _gates_only(tmp_path), tmp_path / "out"
    before = _snapshot(gates)

    def fail(*args, **kwargs):
        raise ValueError("bad nuggets")

    monkeypatch.setattr(pipeline, "cluster_stage", fail)
    with pytest.raises(ValueError, match="bad nuggets"):
        main(["--from-gates", str(gates), "--pops", "1", "--no-show", "--out", str(out)])
    left = sorted(p.name for p in out.iterdir())
    assert left == ["INCOMPLETE.txt", "gates.png", "local_maxima.png"]
    assert "Run incomplete" in capsys.readouterr().err
    assert _snapshot(gates) == before


def test_png_figure_redraws_a_saved_figure_at_its_size(tmp_path, close_figures):
    """--from-gates shows the gate folder's figures from their PNGs, as large as they were drawn,
    on the figure factory it is given."""
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from datanuggets_flow.figures import png_figure, save_figures

    fig = Figure(figsize=(3, 2))
    fig.subplots().plot([0, 1])
    (path,) = save_figures({"a.png": fig}, tmp_path, 110)
    plt.close("all")
    shown = png_figure(path, 110)
    assert tuple(shown.get_size_inches()) == pytest.approx((3, 2))
    assert not shown.axes[0].axison
    assert plt.get_fignums() == []
    png_figure(path, 110, figure=plt.figure)
    assert len(plt.get_fignums()) == 1


def test_from_gates_takes_groups_one_per_gated_file(tmp_path, staged):
    """--groups is counted against the gate folder's files, and run.json's settings carry it."""
    gates = _gates_only(tmp_path, names=("a.fcs", "b.fcs"))
    out, bad = tmp_path / "out", tmp_path / "bad"
    argv = ["--from-gates", str(gates), "--no-show", "--pops", "1", "--dn-num2", "40", "--k", "3"]
    with pytest.raises(SystemExit) as e:
        main([*argv, "--out", str(bad), "--groups", "ctrl"])
    assert e.value.code == "--groups gives 1 names for 2 files; give one per file, separated by ;"
    assert not bad.exists()
    main([*argv, "--out", str(out), "--groups", "ctrl; treated", "--no-tsne"])
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["settings"]["groups"] == ["ctrl", "treated"]
    with open(out / "groups.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["file_number", "file", "group", "kept"],
        ["1", "a.fcs", "ctrl", "true"],
        ["2", "b.fcs", "treated", "true"],
    ]
