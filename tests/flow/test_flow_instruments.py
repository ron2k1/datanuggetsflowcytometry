"""Files from instruments other than the PBMC demo's: channels named without -A, panels whose
files name a channel's stain differently, and a channel that takes one value. Each is run on 202's
recorded events with the names, stains or values changed."""

import warnings
from pathlib import Path

import numpy as np
import pytest
from datanuggets import DataNuggetWarning

from datanuggets_flow import pick
from datanuggets_flow._defaults import FLOW_OFFSCALE_MAX
from datanuggets_flow._pipeline import clustering
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.figures import gates_figure
from datanuggets_flow.livecells import kept_values
from datanuggets_flow.pipeline import (
    default_channels,
    gate_channels,
    gate_files,
    make_nuggets,
    on_scale,
    resolve_channels,
)
from datanuggets_flow.settings import ClusterSettings, GateSettings
from flowcases import load_case, read_202

BV510 = "FJComp-BV510-A"  # 202's second fluorescence channel
LONG_S = "\N{LATIN SMALL LETTER LONG S}SC-A"  # which Python's IGNORECASE alone takes for SSC-A


@pytest.mark.parametrize(
    ("pnn", "want"),
    [
        # a FACSCalibur's FCS 2.0 heights, with one area channel: too few to cluster on their own
        (
            ["FSC-H", "SSC-H", "FL1-H", "FL2-H", "FL3-H", "FL2-A", "FL4-H", "Time"],
            ["FL1-H", "FL2-H", "FL3-H", "FL2-A", "FL4-H"],
        ),
        # a mass cytometer's channels, named by isotope, with no scatter
        (["Time", "Ce140Di", "Nd142Di", "Ir191Di"], ["Ce140Di", "Nd142Di", "Ir191Di"]),
        # Time matched in ASCII, as the app's page matches it: a µ ends the word, a dotless i
        # is no i
        (["FL1-H", "FL2-H", "Timeµs", "Tıme"], ["FL1-H", "FL2-H", "Tıme"]),
    ],
)
def test_without_area_channels_the_default_is_every_marker_channel(pnn, want):
    """A file with fewer than two -A channels gives every channel but scatter and Time, so files
    from instruments that record no areas cluster without --channels. default_channels is the
    rule alone, which the app keys its datasets on."""
    a = {"path": Path("a.fcs"), "pnn": pnn, "pns": [""] * len(pnn)}
    assert default_channels(pnn) == want
    assert resolve_channels([a], ClusterSettings())[0] == want
    assert resolve_channels([a], ClusterSettings(exclude_channels=(want[0],)))[0] == want[1:]


@pytest.mark.parametrize(
    ("pnn", "scatter", "markers"),
    [
        # names in lower case, as some exports write them
        (["fsc-a", "ssc-a", "cd3-a", "cd4-a"], ("fsc-a", "ssc-a"), ["cd3-a", "cd4-a"]),
        # a marker named from SS, SSEA-4, is no side scatter
        (["FSC-A", "SSC-A", "SSEA4-A", "CD3-A"], ("FSC-A", "SSC-A"), ["SSEA4-A", "CD3-A"]),
        # a Navios's FS INT and SS INT, and a spectral cytometer's violet SSC-B-A
        (["FS INT", "SS INT", "FL1 INT", "FL2 INT"], ("FS INT", "SS INT"), ["FL1 INT", "FL2 INT"]),
        (["FSC-A", "SSC-A", "SSC-B-A", "V1-A", "B1-A"], ("FSC-A", "SSC-A"), ["V1-A", "B1-A"]),
        # matched in ASCII, as the app's page matches: a long s is no s, so no scatter here
        ([LONG_S, "CD3-A"], (LONG_S, "CD3-A"), [LONG_S, "CD3-A"]),
    ],
)
def test_scatter_is_fs_or_ss_before_c_a_space_a_dash_or_nothing(pnn, scatter, markers):
    """Scatter is named FS or SS followed by C, a space, a dash, an underscore or nothing, in any
    case: the gate takes it and the default channels leave it out."""
    assert gate_channels(pnn) == scatter
    assert default_channels(pnn) == markers


def test_stain_differences_name_each_channel_its_stains_and_files():
    """A channel's label takes the first file's stain ($PnS), so a channel two files stain
    differently is named in a warning. A file without a stain for it never differs."""
    pnn = ["FSC-A", "SSC-A", "FL1-A", "FL2-A", "FL3-A"]
    a = {"path": Path("a.fcs"), "pnn": pnn, "pns": ["", "", "CD3", "CD4", "CD19"]}
    b = {"path": Path("b.fcs"), "pnn": pnn, "pns": ["", "", "CD3", "CD8", "CD19"]}
    c = {"path": Path("c.fcs"), "pnn": pnn, "pns": ["", "", "", "CD8", "CD20"]}
    with pytest.warns(DataNuggetWarning) as w:
        clustering.warn_stain_differences([a, b, c], pnn[2:])
    assert [str(x.message) for x in w] == [
        (
            "Stains differ between files: FL2-A is CD4 (a.fcs) or CD8 (b.fcs, c.fcs); FL3-A is "
            "CD19 (a.fcs, b.fcs) or CD20 (c.fcs). The run labels each channel with a.fcs's "
            "stain; check that the files name the same markers"
        )
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # one file, or files that agree: no warning
        clustering.warn_stain_differences([a], pnn[2:])
        clustering.warn_stain_differences([a, b], ["FL1-A", "FL3-A"])


def _flat(columns):
    """A reader of 202.fcs with columns set to 0 in every event."""

    def read(path):
        x, names, stains = read_202(path)
        x[:, columns] = 0.0
        return x, names, stains

    return read


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        (
            [3],
            (
                f"{BV510} takes one value in every clustered cell, so it adds nothing to the "
                "clusters; leave it out of the channels to cluster"
            ),
        ),
        (
            [3, 4],
            (
                f"{BV510}, FJComp-Spark Blue-A each take one value in every clustered cell, so "
                "they add nothing to the clusters; leave them out of the channels to cluster"
            ),
        ),
    ],
)
def test_make_nuggets_warns_of_a_channel_with_one_value(columns, message):
    """202's Pop 6 with channels set to 0: they add nothing to the clusters, and the run says
    which. 202's own channels all vary, and give no warning, nor does a channel that takes one
    value in each file but a different one in another."""
    events, pnn, _ = read_202(None)
    masks = load_case("202").his_masks
    sample = {"path": Path("202.fcs"), "n_events": len(events), "pnn": pnn, "masks": masks}
    settings = ClusterSettings(dn_num1=2000, dn_num2=20, n_jobs=1, cofactor=6000.0)
    with pytest.warns(DataNuggetWarning) as w:
        make_nuggets([sample], [[6]], pnn[2:], settings, read=_flat(columns))
    assert [str(x.message) for x in w] == [message]

    def per_file(path):  # BV510 is 0 in a.fcs and 600 in b.fcs
        x, names, stains = read_202(path)
        x[:, 3] = 600.0 if Path(path).name == "b.fcs" else 0.0
        return x, names, stains

    two = [{**sample, "path": Path(name)} for name in ("a.fcs", "b.fcs")]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        make_nuggets([sample], [[6]], pnn[2:], settings, read=read_202)
        make_nuggets(two, [[6], [6]], pnn[2:], settings, read=per_file)


def test_a_channel_holding_values_that_are_not_numbers_is_named():
    """A processed file can hold NaN in a column, such as a label column left empty for the cells
    nobody labelled. Every pass over the kept cells reads them through one step, which names the
    channel and the file, so a clustering pass stops with a message rather than the library's
    traceback. Live cells reads the same cells and counts NaN instead."""
    events, pnn, pns = read_202(None)
    masks = load_case("202").his_masks
    sample = {
        "path": Path("202.fcs"),
        "n_events": len(events),
        "pnn": pnn,
        "pns": pns,
        "masks": masks,
    }
    settings = ClusterSettings(dn_num1=2000, dn_num2=20, n_jobs=1, cofactor=6000.0)

    def holed(path):
        x, names, stains = read_202(path)
        x[::7, 3] = float("nan")
        x[::11, 4] = float("inf")
        return x, names, stains

    want = (
        f"202.fcs holds values that aren't numbers (NaN or infinite) in {BV510}, FJComp-Spark "
        "Blue-A among the cells kept; leave them out of the channels to cluster"
    )
    for step in (make_nuggets, clustering.pooled_scaling, clustering.negative_tally):
        with pytest.raises(FlowError) as e:
            step([sample], [[6]], pnn[2:], settings, read=holed)
        assert str(e.value) == want
    # Live cells reads the same cells and counts NaN in each histogram instead of stopping
    (got,) = kept_values([sample], [[6]], pnn[2:], read=holed).files
    assert np.isnan(got.values[:, 1]).any() and np.isinf(got.values[:, 2]).any()


def _nan_in(*columns):
    """A reader of 202.fcs with NaN in every 7th event of columns, as a label column holds it."""

    def read(path):
        x, names, stains = read_202(path)
        x[::7, list(columns)] = float("nan")
        return x, names, stains

    return read


def test_the_default_channels_leave_out_one_holding_values_that_are_not_numbers():
    """The run chose the default channels, so it leaves out one holding NaN or an infinite value
    among the cells kept, as a processed file's label column can, with a warning, and clusters the
    rest; a channel the run was given by name is refused instead (above). One pass over the files
    finds them, whatever the cofactor. With fewer than two left, the run says to name them."""
    events, pnn, pns = read_202(None)
    masks = load_case("202").his_masks
    sample = {"path": Path("202.fcs"), "n_events": len(events), "pnn": pnn, "pns": pns}
    sample["masks"] = masks
    channels, labels = pnn[2:], [f"label of {c}" for c in pnn[2:]]

    def finite(read, cofactor: str | float = "auto"):
        settings = ClusterSettings(cofactor=cofactor)
        return clustering.finite_channels([sample], [[6]], channels, labels, settings, read=read)

    with pytest.warns(DataNuggetWarning) as w:
        got = finite(_nan_in(3))
    assert got == ([channels[0], channels[2]], [labels[0], labels[2]])
    assert [str(x.message) for x in w] == [
        (
            f"{BV510} holds values that aren't numbers (NaN or infinite) among the cells kept, so "
            "it is left out of the default channels"
        )
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert finite(read_202) == (channels, labels)
        assert finite(read_202, 6000.0) == (channels, labels)
    with pytest.raises(FlowError) as e:
        finite(_nan_in(3, 4))
    assert str(e.value) == (
        f"{BV510}, FJComp-Spark Blue-A hold values that aren't numbers (NaN or infinite) among the "
        "cells kept, which leaves fewer than two default channels; name the channels to cluster "
        "with channels"
    )


def test_the_cli_clusters_the_default_channels_that_are_numbers(
    tmp_path, monkeypatch, capsys, close_figures
):
    """202.fcs with NaN in BV510: the command prints the warning, clusters the other two default
    channels, and still refuses BV510 when --channels names it."""
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.fcs").write_bytes(b"")
    monkeypatch.setattr(pick, "read_fcs", _nan_in(3))
    argv = [str(folder), "--pops", "6", "--no-show", "--dn-num2", "20", "--dn-num1", "2000"]
    argv += ["--k", "2", "--no-tsne"]
    pick.main([*argv, "--out", str(tmp_path / "out")])
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("warning: ")]
    assert lines == [
        (
            f"warning: {BV510} holds values that aren't numbers (NaN or infinite) among the cells "
            "kept, so it is left out of the default channels"
        )
    ]
    columns = (tmp_path / "out" / "cluster_centers.csv").read_text().splitlines()[0]
    assert BV510 not in columns and "FJComp-Spark Blue-A" in columns
    named = ["--channels", f"FJComp-Alexa Fluor 700-A,{BV510}", "--out", str(tmp_path / "out2")]
    with pytest.raises(SystemExit) as e:
        pick.main([*argv, *named])
    assert f"aren't numbers (NaN or infinite) in {BV510} among the cells kept" in str(e.value)


def _past_range(n_far):
    """A reader of 202.fcs with n_far copies of its first event set far past FSC-A's and SSC-A's
    range, as a CytoFLEX writes a few events, and a ranges reader giving both the range."""
    events, pnn, pns = read_202(None)
    top = float(events[:, :2].max())
    far = np.repeat(events[:1], n_far, axis=0)
    far[:, :2] = 100 * top

    def read(path):
        return np.vstack([events, far]), pnn, pns

    def ranges(path):
        return pnn, [top, top, *[None] * (len(pnn) - 2)]

    return read, ranges, len(events)


def test_a_few_events_past_the_range_are_left_out_of_the_grid():
    """Events past a gate channel's range ($PnR) stretch the finder's grid until the others share
    a few of its cells. Up to FLOW_OFFSCALE_MAX of a file's events, they are left out of the grid
    and of every population, and the gate's lines say how many: the rest gate as they would alone.
    More than that, and the range doesn't describe the values, so every event is gated."""
    (want,) = gate_files([Path("202.fcs")], GateSettings(), read=read_202)
    read, ranges, n = _past_range(7)
    lines = []
    (got,) = gate_files(
        [Path("a.fcs")],
        GateSettings(),
        read=read,
        ranges=ranges,
        on_event=lambda e: lines.append(e.message),
    )
    assert got["n_events"] == n + 7 and got["masks"].shape == (n + 7, want["masks"].shape[1])
    assert np.array_equal(got["masks"][:n], want["masks"]) and not got["masks"][n:].any()
    note = "  7 events past the range of FSC-A or SSC-A are left out of every population"
    assert note in lines[0]
    (stretched,) = gate_files([Path("a.fcs")], GateSettings(), read=read, ranges=None)
    assert not np.array_equal(stretched["masks"][:n], want["masks"])

    read, ranges, n = _past_range(2 * int(FLOW_OFFSCALE_MAX * n))
    (many,) = gate_files([Path("a.fcs")], GateSettings(), read=read, ranges=ranges)
    (alone,) = gate_files([Path("a.fcs")], GateSettings(), read=read, ranges=None)
    assert np.array_equal(many["masks"], alone["masks"])


def test_a_channel_named_twice_takes_the_first_ones_range():
    """The gate reads the first channel of a name (pnn.index), so the rule takes that one's
    range: 5 of 1,005 events past 100, though the second FSC-A's range of 200 holds them all."""
    fsc = np.r_[np.full(1000, 50.0), np.full(5, 150.0)]
    ranges = (["FSC-A", "FSC-A", "SSC-A"], [100.0, 200.0, None])
    inside = on_scale([fsc, np.ones_like(fsc)], ("FSC-A", "SSC-A"), ranges)
    assert inside is not None and int((~inside).sum()) == 5


def test_gates_png_is_drawn_on_the_grid_when_events_lie_past_it(close_figures):
    """The events the gate leaves out would stretch gates.png's axes as they stretched the grid,
    so a file with any is drawn on the grid's extent. A file without them is drawn as before."""
    read, ranges, _ = _past_range(7)
    (got,) = gate_files([Path("a.fcs")], GateSettings(), read=read, ranges=ranges)
    ax = gates_figure([got]).axes[0]
    p = got["peaks"]
    axes = ((ax.get_xlim(), p.fsc, got["fsc"]), (ax.get_ylim(), p.ssc, got["ssc"]))
    for (lo, hi), grid, values in axes:
        assert lo < grid.min() and grid.max() < hi < values.max()
    (plain,) = gate_files([Path("202.fcs")], GateSettings(), read=read_202)
    ax = gates_figure([plain]).axes[0]
    assert ax.get_xlim()[1] > plain["fsc"].max() and ax.get_ylim()[1] > plain["ssc"].max()


def test_the_cli_prints_the_runs_warnings_as_lines(tmp_path, monkeypatch, capsys, close_figures):
    """Two copies of 202.fcs: b.fcs stains BV510 another way, and both hold BV510 at 0. The
    command prints each warning once as a line of its output, as it prints the spillover's."""
    folder, out = tmp_path / "in", tmp_path / "out"
    folder.mkdir()
    for name in ("a.fcs", "b.fcs"):
        (folder / name).write_bytes(b"")

    def read(path):
        x, names, stains = _flat([3])(path)
        if Path(path).name == "b.fcs":
            stains = [*stains[:3], "CD99", *stains[4:]]
        return x, names, stains

    monkeypatch.setattr(pick, "read_fcs", read)
    argv = [str(folder), "--pops", "6", "--no-show", "--out", str(out), "--dn-num2", "20"]
    argv += ["--dn-num1", "2000"]  # under Pop 6's 2,292 cells, so create_dn reduces them
    pick.main([*argv, "--k", "2", "--no-tsne", "--cofactor", "6000"])
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("warning: ")]
    stain = read_202(None)[2][3]
    assert lines == [
        (
            f"warning: Stains differ between files: {BV510} is {stain} (a.fcs) or CD99 (b.fcs). "
            "The run labels each channel with a.fcs's stain; check that the files name the same "
            "markers"
        ),
        (
            f"warning: {BV510} takes one value in every clustered cell, so it adds nothing to the "
            "clusters; leave it out of the channels to cluster"
        ),
    ]
    assert (out / "cluster_centers.csv").exists()  # and the run still finishes
