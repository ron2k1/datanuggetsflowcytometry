import csv
import dataclasses
import sys
from pathlib import Path

import numpy as np
import pytest
from datanuggets import RDraws

from datanuggets_flow import pick
from datanuggets_flow._pick import prompt as pick_prompt
from datanuggets_flow._pipeline import clustering, gating, stages
from datanuggets_flow.pick import _fcs_paths, main, parse_pops, per_file, pick_events
from datanuggets_flow.settings import ClusterSettings, GateSettings
from flowcases import (
    COLUMNS,
    DIGESTS,
    DIGESTS_3,
    DIGESTS_AUTO,
    FIGURES,
    TREE,
    TREE_DIGESTS,
    TREE_DIGESTS_3,
    TREE_DIGESTS_AUTO,
    TREE_FIGURES,
    VIEWER,
    VIEWER_2D,
    digest,
    read_202,
)


class _Stop(Exception):
    """Raised by a spy that has seen what it was waiting for, to end the run there."""


@pytest.mark.parametrize("asked", [False, True], ids=["pops", "asked"])
def test_main_clusters_real_events_end_to_end(tmp_path, monkeypatch, close_figures, asked):
    folder, out = tmp_path / "in", tmp_path / "out"
    folder.mkdir()
    (folder / "202.fcs").write_bytes(b"")  # for _fcs_paths to find; read_202 reads it
    monkeypatch.setattr(pick, "read_fcs", read_202)
    argv = [str(folder), "--no-show", "--out", str(out), "--dn-num2", "50", "--k", "3"]
    argv.append("--no-standardize")  # the tables pinned before the Scale stage
    argv += ["--cofactor", "6000"]  # and before the cofactor was picked from the headers
    if asked:  # Pop 1 typed at the prompt instead
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(pick_prompt, "_live_input", lambda prompt, plt, show: "1")
    else:
        argv[1:1] = ["--pops", "1"]
    main(argv)
    assert sorted(p.name for p in out.iterdir()) == sorted([*COLUMNS, *VIEWER, *FIGURES])
    for name, columns in COLUMNS.items():
        with open(out / name, newline="") as f:
            assert next(csv.reader(f)) == columns, name
    for name in FIGURES:
        assert (out / name).read_bytes().startswith(b"\x89PNG"), name
    assert {name: digest(out / name) for name in COLUMNS} == DIGESTS


def test_populations_are_chosen_from_the_local_maxima_before_gates_are_drawn(
    tmp_path, monkeypatch, close_figures
):
    folder, out = tmp_path / "in", tmp_path / "out"
    folder.mkdir()
    (folder / "202.fcs").write_bytes(b"")
    monkeypatch.setattr(pick, "read_fcs", read_202)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen = []

    def answer(prompt, plt, show):
        seen.append(sorted(p.name for p in out.iterdir()))
        raise SystemExit("\ncancelled; nothing was clustered")

    monkeypatch.setattr(pick_prompt, "_live_input", answer)
    with pytest.raises(SystemExit, match="cancelled"):
        main([str(folder), "--no-show", "--out", str(out)])
    assert seen == [["INCOMPLETE.txt", "local_maxima.png"]]
    assert not (out / "gates.png").exists()


def test_main_numbers_each_file_and_clusters_its_own_nuggets(tmp_path, monkeypatch, close_figures):
    """Three copies of 202.fcs, each with its own t11, the second left out: the other two keep
    their numbers, and the third file's slice of the pooled clusters is its own. With the peak's
    disc, the events as stored and two of the channels."""
    folder, out = tmp_path / "in", tmp_path / "out"
    folder.mkdir()
    for name in ("a.fcs", "b.fcs", "c.fcs"):
        (folder / name).write_bytes(b"")
    monkeypatch.setattr(pick, "read_fcs", read_202)
    main(
        [
            str(folder),
            "--no-show",
            "--out",
            str(out),
            "--pops",
            "1;none;1,2",
            "--t11",
            "22,20,18",
            "--t21",
            "0.25,0.25,0.4",
            "--disc",
            "peak",
            "--cofactor",
            "0",
            "--channels",
            "FJComp-BV510-A, FJComp-Spark Blue-A",
            "--dn-num2",
            "40",
            "--k",
            "4",
            "--no-standardize",  # the tables pinned before the Scale stage
        ]
    )
    tables = [
        "selection.csv",
        "nuggets_1.csv",
        "events_1.csv",
        "nuggets_3.csv",
        "events_3.csv",
        "cluster_summary.csv",
        "cluster_centers.csv",
    ]
    assert sorted(p.name for p in out.iterdir()) == sorted([*tables, *VIEWER_2D, *FIGURES])
    assert {name: digest(out / name) for name in tables} == DIGESTS_3


def _sample(name, n):
    return {"path": Path(name), "masks": np.zeros((5, n), dtype=bool), "table": [f"  {name}"]}


def test_ask_takes_each_files_pops_and_enter_repeats_the_last(monkeypatch, capsys):
    answers = iter(["", "7", "1,2", "", "none", ""])
    prompts = []

    def typed(prompt, plt, show):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(pick_prompt, "_live_input", typed)
    names = [("a.fcs", 3), ("b.fcs", 3), ("c.fcs", 0), ("d.fcs", 2), ("e.fcs", 2)]
    got = pick._ask([_sample(*s) for s in names], None, False)
    assert got == [[1, 2], [1, 2], [], [], []]
    assert prompts[3] == "Keep which, Pop 1 to 3 [1,2]: "
    assert prompts[5] == "Keep which, Pop 1 to 2 [none]: "
    out = capsys.readouterr().out
    assert "no population given" in out and "there is no Pop 7" in out
    assert "File 3, c.fcs:\n  c.fcs\n  no populations found" in out


def test_ask_without_a_terminal_says_to_pass_pops(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(SystemExit, match="pass --pops"):
        pick._ask([_sample("a.fcs", 2)], None, False)


def test_live_input_without_a_window_reads_a_line(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda: "1,2")
    assert pick._live_input("Keep which: ", None, False) == "1,2"
    assert capsys.readouterr().out == "Keep which: "

    def closed():
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    with pytest.raises(SystemExit, match="nothing was clustered"):
        pick._live_input("Keep which: ", None, False)


def test_per_file_reads_one_value_or_one_per_file():
    """Parsing only: GateSettings.check counts the values against the files."""
    assert per_file("22", "--t11") == (22.0,)
    assert per_file("22,20,18", "--t11") == (22.0, 20.0, 18.0)
    assert per_file(None, "--t11") is None
    with pytest.raises(SystemExit, match="takes numbers"):
        per_file("x", "--t11")


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("1", [1]),
        ("1,2", [1, 2]),
        (" 2 1 ", [1, 2]),
        ("1-3", [1, 2, 3]),
        ("3-1", [1, 2, 3]),
        ("2,2", [2]),
        ("ALL", [1, 2, 3, 4]),
        ("none", []),
    ],
)
def test_parse_pops_reads_numbers_ranges_all_and_none(text, want):
    assert parse_pops(text, 4) == want


@pytest.mark.parametrize("text", ["5", "0", "1,x", "1-", "", "  ", "-2"])
def test_parse_pops_rejects_what_names_no_population(text):
    with pytest.raises(ValueError):
        parse_pops(text, 4)


def test_pick_events_is_the_union_counting_an_event_once():
    masks = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]], dtype=bool)
    assert pick_events(masks, [1, 2]).tolist() == [True, True, True, False, False]
    assert pick_events(masks, [3]).tolist() == [False, False, False, True, False]
    assert not pick_events(masks, []).any()


def test_fcs_paths_skips_dotfiles_and_other_files(tmp_path):
    for name in ("b.fcs", "a.FCS", "._a.fcs", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in _fcs_paths([tmp_path])] == ["a.FCS", "b.fcs"]


def test_fcs_paths_stops_on_an_empty_folder(tmp_path):
    with pytest.raises(SystemExit, match="no .fcs files"):
        _fcs_paths([tmp_path])


def test_pops_must_give_one_choice_or_one_per_file(tmp_path, monkeypatch):
    """pipeline.selection_choices counts the --pops entries against the files before any is
    read."""
    for name in ("a.fcs", "b.fcs", "c.fcs"):
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setattr(pick, "read_fcs", lambda path: pytest.fail("read before the count"))
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path), "--pops", "1;2", "--no-show", "--out", str(tmp_path / "out")])
    assert e.value.code == (
        "--pops gives 2 choices for 3 files; give one for all of them or one per file, "
        "separated by ;"
    )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(("flag", "value"), [("--t11", "22,20"), ("--t21", "0.25,0.5")])
def test_thresholds_must_give_one_value_or_one_per_file(tmp_path, monkeypatch, flag, value):
    """GateSettings.check counts --t11 and --t21 against the files before any is read."""
    for name in ("a.fcs", "b.fcs", "c.fcs"):
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setattr(pick, "read_fcs", lambda path: pytest.fail("read before the count"))
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path), flag, value, "--pops", "1", "--no-show", "--out", str(out)])
    assert e.value.code == f"{flag} gives 2 values for 3 files; give one, or one per file"
    assert not out.exists()


@pytest.mark.parametrize("existing", ["directory", "empty-directory", "file"])
def test_existing_output_is_preserved_before_reading_input(tmp_path, monkeypatch, existing):
    source, out = tmp_path / "202.fcs", tmp_path / "out"
    source.touch()
    if existing == "file":
        out.write_bytes(b"keep this file")
        before = out.read_bytes()
    else:
        out.mkdir()
        if existing == "directory":
            for name in (*COLUMNS, *FIGURES, "nuggets_9.csv"):
                (out / name).write_bytes(b"earlier results")
        before = {p.name: p.read_bytes() for p in out.iterdir()}
    monkeypatch.setattr(pick, "read_fcs", lambda path: pytest.fail("read before output check"))
    with pytest.raises(SystemExit, match="output path already exists"):
        main([str(source), "--pops", "1", "--no-show", "--out", str(out)])
    after = out.read_bytes() if out.is_file() else {p.name: p.read_bytes() for p in out.iterdir()}
    assert after == before


@pytest.mark.parametrize(
    "failure", [ValueError("bad FCS"), SystemExit("cancelled"), KeyboardInterrupt()]
)
def test_failed_run_is_marked_and_does_not_touch_previous_results(
    tmp_path, monkeypatch, capsys, failure
):
    source, old, out = tmp_path / "202.fcs", tmp_path / "previous", tmp_path / "new"
    source.touch()
    old.mkdir()
    (old / "events_1.csv").write_bytes(b"earlier events")

    def fail(*args):
        (out / "gates.png").write_bytes(b"partial figure")
        raise failure

    monkeypatch.setattr(pick, "_gate_files", fail)
    with pytest.raises(type(failure)):
        main([str(source), "--pops", "1", "--no-show", "--out", str(out)])
    assert (old / "events_1.csv").read_bytes() == b"earlier events"
    assert (out / "INCOMPLETE.txt").is_file()
    assert "Run incomplete" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="output path already exists"):
        main([str(source), "--pops", "1", "--no-show", "--out", str(out)])


def test_default_runs_have_separate_folders_under_outputs(tmp_path, monkeypatch):
    source = tmp_path / "202.fcs"
    source.touch()
    monkeypatch.chdir(tmp_path)

    def cancel(*args):
        raise SystemExit("cancelled")

    monkeypatch.setattr(pick, "_gate_files", cancel)
    for _ in range(2):
        with pytest.raises(SystemExit, match="cancelled"):
            main([str(source), "--no-show"])
    runs = list((tmp_path / "outputs").iterdir())
    assert len(runs) == 2
    assert all((run / "INCOMPLETE.txt").is_file() for run in runs)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["202.fcs", "outputs"]


@pytest.mark.parametrize("names", [None, "CD3-A", "CD3-A,CD3-A"])
def test_too_few_distinct_channels_stop_before_clustering(names):
    samples = [{"path": Path("one.fcs"), "pnn": ["FSC-A", "SSC-A", "CD3-A"], "pns": ["", "", ""]}]
    with pytest.raises(SystemExit, match="at least two distinct fluorescence channels"):
        pick._choose_channels(samples, names)


@pytest.mark.parametrize(
    ("flag", "value", "match"), [("--k", "0", "--k is 0"), ("--dn-num2", "10000", "2 to 9999")]
)
def test_bad_k_or_dn_num2_stops_before_any_file_is_read(tmp_path, flag, value, match):
    with pytest.raises(SystemExit, match=match):
        main([str(tmp_path / "missing"), flag, value, "--no-show"])


def test_parser_defaults_are_all_resolved_from_settings():
    """A flag that sets a setting defaults to None, so a run without it takes the settings class's
    default, the one place that value is kept."""
    names = {f.name for cls in (GateSettings, ClusterSettings) for f in dataclasses.fields(cls)}
    defaults = {a.dest: a.default for a in pick._parser()._actions if a.dest in names}
    assert defaults == dict.fromkeys(names)


def test_disc_takes_reference_peak_and_the_old_name_his(capsys):
    """--disc his, the reference rule's old name, still works and is read as reference; the
    usage offers only the two current names."""
    parser = pick._parser()
    assert [parser.parse_args(["--disc", d]).disc for d in ("reference", "peak", "his")] == [
        "reference",
        "peak",
        "reference",
    ]
    assert "{reference,peak}" in parser.format_usage()
    with pytest.raises(SystemExit) as e:
        parser.parse_args(["--disc", "mirror"])
    assert e.value.code == 2
    assert "--disc" in capsys.readouterr().err


def test_explicit_defaults_give_the_same_tables(tmp_path, monkeypatch, close_figures):
    """Every gate and clustering flag spelled at the value it takes when left out: the tables
    are the ones the run writes without them. --cofactor auto picks each channel's cofactor from
    the cells, as the run without it does, so the two runs are compared with each other, and the
    run without them is pinned on its own, so a change that moves both runs alike still shows."""
    source = tmp_path / "202.fcs"
    source.touch()
    monkeypatch.setattr(pick, "read_fcs", read_202)
    defaults = {
        "--fsc": "FSC-A",
        "--ssc": "SSC-A",
        "--disc": "reference",
        "--t11": "22",
        "--t21": "0.25",
        "--t12": "20",
        "--t22": "0.5",
        "--n-row": "11",
        "--n-col": "11",
        "--channels": ",".join(read_202(source)[1][2:]),  # the default rule's, in file order
        "--cofactor": "auto",
        "--dn-num1": "10000",
        "--center-method": "original",
        "--seed": "291102",
        "--draws": "r",
        "--method": "wkmeans",
        "--num-init": "10",
        "--max-iter": "100",
        "--tsne-perplexity": "30",
        "--tsne-seed": "0",
    }
    argv = [str(source), "--no-show", "--jobs", "1", "--pops", "1", "--dn-num2", "50", "--k", "3"]
    main([*argv, "--out", str(tmp_path / "left_out")])
    main([*argv, "--out", str(tmp_path / "spelled"), *(t for kv in defaults.items() for t in kv)])
    left_out = {name: digest(tmp_path / "left_out" / name) for name in COLUMNS}
    assert left_out == DIGESTS_AUTO
    assert {name: digest(tmp_path / "spelled" / name) for name in COLUMNS} == left_out


def test_new_flags_reach_the_finder_create_dn_and_tsne(tmp_path, monkeypatch, close_figures):
    """The finder gets --t12, --t22, --n-row and --n-col, create_dn --dn-num1, --seed and --jobs,
    with the channels --exclude-channels leaves, and the t-SNE --tsne-perplexity and --tsne-seed.
    The run stops there, before the figures."""
    source = tmp_path / "202.fcs"
    source.touch()
    monkeypatch.setattr(pick, "read_fcs", read_202)
    # each stand-in is set where the step that calls it looks it up
    finder, nuggets, seen = gating.gate_peaks, clustering.create_dn, {}

    def gate_peaks(fsc, ssc, **kwargs):
        seen["finder"] = kwargs
        return finder(fsc, ssc, **kwargs)

    def create_dn(x, **kwargs):
        seen["create_dn"] = kwargs
        seen["channels"] = x.shape[1]
        return nuggets(x, **kwargs)

    def tsne_embedding(centers, settings):
        seen["tsne"] = (settings.tsne_perplexity, settings.tsne_seed)
        raise _Stop

    monkeypatch.setattr(gating, "gate_peaks", gate_peaks)
    monkeypatch.setattr(clustering, "create_dn", create_dn)
    monkeypatch.setattr(stages, "tsne_embedding", tsne_embedding)
    flags = {
        "--t12": "19",
        "--t22": "0.4",
        "--n-row": "9",
        "--n-col": "13",
        "--dn-num1": "5000",
        "--dn-num2": "50",
        "--seed": "7",
        "--jobs": "1",
        "--exclude-channels": "FJComp-BV510-A",
        "--tsne-perplexity": "12.5",
        "--tsne-seed": "3",
    }
    argv = [str(source), "--pops", "1", "--no-show", "--out", str(tmp_path / "out")]
    with pytest.raises(_Stop):
        main([*argv, *(t for item in flags.items() for t in item)])
    finder_flags = {k: seen["finder"][k] for k in ("t12", "t22", "n_row", "n_col")}
    assert finder_flags == {"t12": 19.0, "t22": 0.4, "n_row": 9, "n_col": 13}
    seed = seen["create_dn"].pop("seed")  # R's set.seed(7) draws, the default draws "r"
    assert isinstance(seed, RDraws)
    assert np.array_equal(seed.random_seed(), RDraws(7).random_seed())
    assert seen["create_dn"] == {
        "center_method": "original",
        "dn_num1": 5000,
        "dn_num2": 50,
        "n_jobs": 1,
    }
    assert seen["channels"] == 2
    assert seen["tsne"] == (12.5, 3)


def test_cli_sets_the_clustering_flags():
    """--method, --center-method, --num-init, --max-iter and --draws set the clustering's
    settings; left out, each takes the settings' default. Their help names the defaults, and no
    flag's help or the description names Ward."""
    parser = pick._parser()

    def clustering(*flags):
        s = pick._settings(parser.parse_args(["x.fcs", *flags]))
        return s.method, s.center_method, s.num_init, s.max_iter, s.draws

    assert clustering() == ("wkmeans", "original", 10, 100, "r")
    given = ["--center-method", "random", "--num-init", "3", "--max-iter", "20", "--draws", "numpy"]
    assert clustering("--method", "wkmeans", *given) == ("wkmeans", "random", 3, 20, "numpy")
    assert clustering("--method", "tree", "--center-method", "mean")[:2] == ("tree", "mean")
    for flag, value in (("--method", "ward"), ("--center-method", "median"), ("--draws", "R")):
        with pytest.raises(SystemExit) as e:
            parser.parse_args(["x.fcs", flag, value])
        assert e.value.code == 2, flag
    usage = parser.format_usage()
    for choices in ("{wkmeans,tree}", "{mean,random,original}", "{r,numpy}"):
        assert choices in usage
    with pytest.raises(SystemExit, match="--num-init is 0; it takes a whole number from 1"):
        main(["x.fcs", "--num-init", "0", "--no-show"])
    helps = {a.option_strings[0]: a.help for a in parser._actions if a.option_strings}
    assert helps["--k"] == "clusters (default: 8)"
    assert "create_dn" in helps["--seed"] and "weighted k-means" in helps["--seed"]
    assert "Ward" not in parser.description + "".join(map(str, helps.values()))


@pytest.mark.parametrize("flag", ["--num-init", "--max-iter"])
def test_num_init_with_the_tree_is_refused(tmp_path, flag):
    """The tree has no starts or rounds, so either flag with --method tree stops the run before a
    file is read, rather than being ignored."""
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path / "missing"), "--method", "tree", flag, "5", "--no-show"])
    assert (
        str(e.value) == "--num-init and --max-iter set weighted k-means, not the hierarchical tree"
    )


def test_the_tree_on_mean_centers_with_numpy_draws_keeps_the_old_digests(
    tmp_path, monkeypatch, close_figures
):
    """The one-file, three-file and auto-cofactor cases, run under TREE (the hierarchical tree on
    mean centers, the nuggets on numpy's draws), give the tables every run gave before weighted
    k-means became the default, digest for digest: an old run replays."""
    monkeypatch.setattr(pick, "read_fcs", read_202)
    one, three = tmp_path / "one", tmp_path / "three"
    one.mkdir()
    three.mkdir()
    (one / "202.fcs").write_bytes(b"")
    for name in ("a.fcs", "b.fcs", "c.fcs"):
        (three / name).write_bytes(b"")
    out = tmp_path / "out_one"
    fixed = ["--no-standardize", "--cofactor", "6000"]  # as the one-file case was pinned
    main(
        [str(one), "--pops", "1", "--no-show", "--out", str(out), "--dn-num2", "50", "--k", "3"]
        + fixed
        + TREE
    )
    assert sorted(p.name for p in out.iterdir()) == sorted([*COLUMNS, *VIEWER, *TREE_FIGURES])
    assert {name: digest(out / name) for name in COLUMNS} == TREE_DIGESTS
    out = tmp_path / "out_three"
    channels = "FJComp-BV510-A, FJComp-Spark Blue-A"
    gate_flags = ["--t11", "22,20,18", "--t21", "0.25,0.25,0.4", "--disc", "peak"]
    main(
        [str(three), "--no-show", "--out", str(out), "--pops", "1;none;1,2", *gate_flags]
        + ["--cofactor", "0", "--channels", channels, "--dn-num2", "40", "--k", "4"]
        + ["--no-standardize", "--no-tsne", *TREE]
    )
    assert {name: digest(out / name) for name in TREE_DIGESTS_3} == TREE_DIGESTS_3
    out = tmp_path / "out_auto"
    argv = [str(one / "202.fcs"), "--no-show", "--jobs", "1", "--pops", "1"]
    main([*argv, "--dn-num2", "50", "--k", "3", "--no-tsne", "--out", str(out), *TREE])
    assert {name: digest(out / name) for name in COLUMNS} == TREE_DIGESTS_AUTO


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--dn-num1", "2", "--dn-num1 is 2; it takes 3 or more nuggets"),
        ("--cofactor", "-1", "--cofactor is -1.0; it takes auto, 0 (linear) or a positive number"),
        ("--cofactor", "nan", "--cofactor is nan; it takes auto, 0 (linear) or a positive number"),
        ("--jobs", "0", "--jobs is 0; it takes -1 (every core) or 1 or more"),
        (
            "--seed",
            "-1",
            "--seed is -1; it takes a whole number from 0 to 2147483647, R's largest seed",
        ),
        ("--n-row", "0", "--n-row is 0; it takes 1 to 100 grid cells"),
        ("--t12", "0", "--t12 is 0.0; it takes a positive distance in grid cells"),
        ("--t22", "nan", "--t22 is nan; it takes a fraction of the peak's density, 0 or more"),
        ("--tsne-perplexity", "0", "--tsne-perplexity is 0.0; it takes a positive number"),
        ("--tsne-seed", "-1", "--tsne-seed is -1; it takes a whole number from 0"),
        (
            "--seed",
            "2147483648",
            "--seed is 2147483648; it takes a whole number from 0 to 2147483647, R's largest seed",
        ),
    ],
)
def test_bad_settings_stop_before_any_file_is_read(tmp_path, flag, value, message):
    """The path doesn't exist, so a check made after the files are found would say that first."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path / "missing"), flag, value, "--no-show", "--out", str(out)])
    assert e.value.code == message
    assert not out.exists()


def test_exclude_channels_and_channels_are_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path), "--channels", "CD3-A,CD4-A", "--exclude-channels", "Live-A"])
    assert e.value.code == 2
    assert "--exclude-channels: not allowed with argument --channels" in capsys.readouterr().err


def test_no_tsne_keeps_the_tables_and_drops_its_figure(tmp_path, monkeypatch, close_figures):
    """Without the t-SNE the tables are the same, clusters_tsne.png isn't drawn, and scikit-learn
    is never needed."""
    monkeypatch.setitem(sys.modules, "sklearn", None)
    monkeypatch.setitem(sys.modules, "sklearn.manifold", None)
    source, out = tmp_path / "202.fcs", tmp_path / "out"
    source.touch()
    monkeypatch.setattr(pick, "read_fcs", read_202)
    argv = [str(source), "--no-tsne", "--pops", "1", "--no-show", "--out", str(out)]
    main([*argv, "--dn-num2", "50", "--k", "3", "--no-standardize", "--cofactor", "6000"])
    figures = set(FIGURES) - {"clusters_tsne.png"}
    viewer = set(VIEWER) - {"tsne.csv", "tsne3d.csv"}
    assert sorted(p.name for p in out.iterdir()) == sorted([*COLUMNS, *viewer, *figures])
    assert {name: digest(out / name) for name in COLUMNS} == DIGESTS


@pytest.mark.parametrize(("flag", "value"), [("--tsne-perplexity", "10"), ("--tsne-seed", "1")])
def test_tsne_flags_are_refused_with_no_tsne(tmp_path, flag, value):
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path / "missing"), "--no-tsne", flag, value, "--no-show", "--out", str(out)])
    assert e.value.code == f"{flag} has no effect with --no-tsne"
    assert not out.exists()


def test_asked_run_prints_the_pops_that_repeat_it(monkeypatch, capsys):
    """The answers, Enter's among them, end with the --pops that makes the same choice without
    the prompt. A choice --pops gave has no such line."""
    answers = iter(["1,2", "none", ""])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(pick_prompt, "_live_input", lambda prompt, plt, show: next(answers))
    samples = [_sample(name, 3) for name in ("a.fcs", "b.fcs", "c.fcs")]
    assert pick._choose_pops(samples, None, None, False) == [[1, 2], [], []]
    assert capsys.readouterr().out.endswith('\nTo repeat this choice: --pops "1,2;none;none"\n')
    assert pick._choose_pops(samples, "1", None, False) == [[1]] * 3
    assert capsys.readouterr().out == ""


def test_filter_groups_and_cells_flags_reach_the_run(tmp_path, monkeypatch, close_figures):
    """--filter, --groups and --cells-per-file on a real file: the filtered cells are clustered,
    selection.csv counts them, and the group tables and cells.csv are written."""
    import pandas as pd

    source, out = tmp_path / "202.fcs", tmp_path / "out"
    source.touch()
    monkeypatch.setattr(pick, "read_fcs", read_202)
    argv = [str(source), "--pops", "1", "--no-show", "--no-tsne", "--out", str(out)]
    flags = ["--filter", "FJComp-BV510-A > 10000", "--filter", "[FJComp-Spark Blue-A] <= 40000"]
    main(
        [*argv, "--dn-num2", "50", "--k", "3", *flags, "--groups", "ctrl", "--cells-per-file", "7"]
    )
    names = {p.name for p in out.iterdir()}
    assert {"groups.csv", "group_summary.csv", "group_markers.csv", "cells.csv"} <= names
    selection = pd.read_csv(out / "selection.csv")
    events = pd.read_csv(out / "events_1.csv")
    assert selection.loc[0, "filtered"] == len(events) < selection.loc[0, "kept"]
    assert len(pd.read_csv(out / "cells.csv")) == 7
    assert pd.read_csv(out / "group_summary.csv")["group"].unique().tolist() == ["ctrl"]


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--filter", "CD3-A>=1"], "--filter: 'CD3-A>=1' has no operator"),
        (["--groups", "ctrl;b/c"], "--groups has 'b/c'"),
        (["--groups", ";ctrl"], "--groups has an empty name"),
        (["--cells-per-file", "-1"], "--cells-per-file is -1; it takes a whole number from 0"),
    ],
)
def test_bad_filter_groups_or_cells_stop_before_any_file_is_read(tmp_path, flags, message):
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path / "missing"), *flags, "--no-show", "--out", str(out)])
    assert e.value.code.startswith(message)
    assert not out.exists()


def test_groups_are_counted_against_the_files_before_any_is_read(tmp_path, monkeypatch):
    source, out = tmp_path / "202.fcs", tmp_path / "out"
    source.touch()
    monkeypatch.setattr(pick, "read_fcs", lambda path: pytest.fail("read before groups check"))
    with pytest.raises(SystemExit) as e:
        main([str(source), "--pops", "1", "--groups", "a;b", "--no-show", "--out", str(out)])
    assert e.value.code == "--groups gives 2 names for 1 files; give one per file, separated by ;"
    assert not out.exists()


def test_gates_only_refuses_groups(tmp_path):
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path), "--gates-only", "--groups", "a", "--no-show"])
    assert e.value.code == "--groups sets the clustering stage, which --gates-only stops before"
