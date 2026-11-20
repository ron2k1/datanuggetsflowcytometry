"""The live-cells step (datanuggets_flow.livecells) on real events: 202.fcs's recorded channels
written as two FCS files with flowio.create_fcs, gated by gate_stage and read back by load_gates,
as a server holds them after a gate job. The channel suggestions run on the real $PnN and $PnS of
two public Zenodo records."""

import os
from pathlib import Path

import flowio
import numpy as np
import pandas as pd
import pytest
from datanuggets.filters import RowFilter, filter_mask, format_filter, parse_filter

from datanuggets_flow import livecells
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.livecells import (
    KeptValues,
    channel_histograms,
    count_kept,
    kept_values,
    load_kept_values,
    save_kept_values,
    suggest_channels,
)
from datanuggets_flow.pipeline import MIN_KEPT_EVENTS, cluster_stage, gate_stage, pick_events
from datanuggets_flow.pipeline import read_fcs as read_events
from datanuggets_flow.settings import ClusterSettings, GateSettings
from datanuggets_flow.state import load_gates
from flowcases import FLOW

# The channels of Zenodo 22079206's 190.fcs, 193.fcs, 199.fcs and 223.fcs, the app's PBMC demo,
# as flowio reads them; all four files carry this list. test_the_lists_are_the_files checks it
# against the files when DATANUGGETS_DEMO_FCS names their folder.
DEMO_PNN = (
    "FSC-A", "FSC-H", "SSC-A", "SSC-B-A", "SSC-B-H", "SSC-H", "FJComp-APC-Cy5.5-A",
    "FJComp-APC-Fire 750-A", "FJComp-Alexa Fluor 647-A", "FJComp-Alexa Fluor 700-A",
    "FJComp-BB630-A", "FJComp-BB660-A", "FJComp-BUV395-A", "FJComp-BUV496-A", "FJComp-BUV563-A",
    "FJComp-BUV615-A", "FJComp-BUV661-A", "FJComp-BUV737-A", "FJComp-BUV805-A", "FJComp-BV421-A",
    "FJComp-BV480-A", "FJComp-BV510-A", "FJComp-BV570-A", "FJComp-BV605-A", "FJComp-BV650-A",
    "FJComp-BV711-A", "FJComp-BV750-A", "FJComp-BV785-A", "FJComp-FITC-A",
    "FJComp-LIVE DEAD Blue-A", "FJComp-PE-Cy5-A", "FJComp-PE-Cy5.5-A", "FJComp-PE-Cy7-A",
    "FJComp-PE-Dazzle594-A", "FJComp-PerCP-A", "FJComp-Qdot 800-A", "FJComp-Spark Blue-A",
    "FJComp-eFluor 450-A", "Time",
)  # fmt: skip
DEMO_PNS = (
    "", "", "", "", "", "", "CD38", "CD123", "IgG", "CD8", "ACE2", "CD1c", "CD45RA", "CD16",
    "CD27", "CCR4", "CD11c", "CD56", "CD86", "PD1", "IgD", "CD3", "HLADR", "CD28", "CXCR3",
    "CCR6", "CXCR5", "CCR7", "CD57", "DEAD", "CD95", "CD19", "CD25", "IgM", "CD45", "CD14", "CD4",
    "CD161", "",
)  # fmt: skip
# The channels of the nine healthy-donor PBMC files of Zenodo 18367404, which all carry this
# list; DATANUGGETS_ZENODO_18367404 names their folder for the same check.
NKG2A_PNN = (
    "Time", "SSC-H", "SSC-A", "FSC-H", "FSC-A", "SSC-B-H", "SSC-B-A", "BUV395-A", "BUV496-A",
    "BUV563-A", "BUV615-A", "BUV661-A", "BUV737-A", "BUV805-A", "BV421-A", "V450-A", "BV480-A",
    "BV510-A", "BV570-A", "BV605-A", "BV650-A", "BV711-A", "BV750-A", "BV786-A", "FITC-A",
    "Alexa Fluor 532-A", "BB700-A", "PerCP-Cy5.5-A", "PE-A", "PE-Dazzle594-A", "PE-Cy7-A",
    "Alexa Fluor 647-A", "Alexa Fluor 700-A", "Zombie NIR-A", "APC-Fire 750-A", "AF-A",
)  # fmt: skip
NKG2A_PNS = (
    "", "", "", "", "", "", "", "CD38", "NKG2C", "CD3", "CD16", "CD161", "CD32", "CD56", "41BB",
    "CD4", "CD64", "KLRG1", "CD45", "HLA-DR", "CD19", "NKp44", "CD69", "TIGIT", "CD57", "CD8",
    "CD14", "CD27", "NKG2A", "CTLA-4", "TRAIL", "PD-1", "CD18", "Z NIR", "CD66b", "",
)  # fmt: skip
RECORDS = {
    "DATANUGGETS_DEMO_FCS": (("190", "193", "199", "223"), DEMO_PNN, DEMO_PNS),
    "DATANUGGETS_ZENODO_18367404": (
        ("2306", "3742", "4212", "4337", "4449", "5143", "6042", "6252", "6840"),
        NKG2A_PNN,
        NKG2A_PNS,
    ),
}


@pytest.fixture(scope="module")
def gated(tmp_path_factory):
    """Two FCS files of real events, 202.fcs's recorded channels: all 50,000 events, and the
    first 30,000 of them as a second sample, gated into a gate folder and loaded back."""
    tmp = tmp_path_factory.mktemp("livecells")
    with np.load(FLOW / "202.npz") as gate, np.load(FLOW / "202_fluor.npz") as fluor:
        events = np.column_stack((gate["fsc"], gate["ssc"], fluor["fluor"]))
        names = ["FSC-A", "SSC-A", *fluor["pnn"].tolist()]
        labels = ["", "", *fluor["pns"].tolist()]
    paths = []
    for name, part in (("a.fcs", events), ("b.fcs", events[:30_000])):
        path = tmp / name
        with path.open("wb") as handle:
            flowio.create_fcs(handle, part.ravel(), names, opt_channel_names=labels)
        paths.append(path)
    folder = tmp / "gates"
    folder.mkdir()
    gate_stage(paths, folder, GateSettings())
    samples = load_gates(folder).samples
    chosen = [[1, 2], list(range(1, np.shape(samples[1]["masks"])[1] + 1))]
    return {"samples": samples, "chosen": chosen, "channels": names[2:], "tmp": tmp}


@pytest.fixture(scope="module")
def values(gated):
    return kept_values(gated["samples"], gated["chosen"], gated["channels"])


def _direct(gated, i, channels):
    """File i's kept cells on channels, read and selected here without livecells."""
    s, pops = gated["samples"][i], gated["chosen"][i]
    events, pnn, _ = read_events(s["path"])
    rows = np.flatnonzero(pick_events(s["masks"], pops))
    return events[np.ix_(rows, [pnn.index(c) for c in channels])]


def _thresholds(hist):
    """A filter per channel at its histogram's middle edge, turned back to a raw value with the
    channel's own cofactor (the one every channel shares, for a set one) and rounded to 4
    significant digits, as the app's line writes it, in canonical spec form: the first channel
    keeping below, the others above."""
    specs = []
    for j, ch in enumerate(hist["channels"]):
        t = ch["edges"][len(ch["edges"]) // 2]
        c = hist["cofactors"][j] if "cofactors" in hist else hist["cofactor"]
        raw = float(f"{c * np.sinh(t):.4g}")
        specs.append(format_filter(RowFilter(ch["channel"], "<" if j == 0 else ">", raw)))
    return specs


# ---- suggest_channels ---------------------------------------------------------------------


def test_suggestions_on_the_demo_files_skip_cd45ra():
    got = suggest_channels(DEMO_PNN, DEMO_PNS)
    assert got == {
        "viability": "FJComp-LIVE DEAD Blue-A",
        "cd45": "FJComp-PerCP-A",
        "candidates": {"viability": ["FJComp-LIVE DEAD Blue-A"], "cd45": ["FJComp-PerCP-A"]},
    }
    assert DEMO_PNS[DEMO_PNN.index("FJComp-BUV395-A")] == "CD45RA"  # in the panel, not taken


def test_suggestions_on_the_zenodo_18367404_files():
    got = suggest_channels(NKG2A_PNN, NKG2A_PNS)
    assert (got["viability"], got["cd45"]) == ("Zombie NIR-A", "BV570-A")
    assert got["candidates"] == {"viability": ["Zombie NIR-A"], "cd45": ["BV570-A"]}


def test_suggestions_read_names_only_and_never_guess():
    # the $PnN alone finds the dye by name; CD45 sits only in $PnS, so it needs the labels
    got = suggest_channels(DEMO_PNN)
    assert (got["viability"], got["cd45"]) == ("FJComp-LIVE DEAD Blue-A", None)
    # two -A channels that both look like a viability dye: no suggestion, both listed
    both = suggest_channels((*DEMO_PNN, "Zombie NIR-A"), (*DEMO_PNS, "Z NIR"))
    assert both["viability"] is None
    assert both["candidates"]["viability"] == ["FJComp-LIVE DEAD Blue-A", "Zombie NIR-A"]
    assert both["cd45"] == "FJComp-PerCP-A"
    # an area and a height channel of one dye: the area channel, which the clustering takes
    height = suggest_channels((*NKG2A_PNN, "Zombie NIR-H"), (*NKG2A_PNS, "Z NIR"))
    assert height["viability"] == "Zombie NIR-A"
    assert height["candidates"]["viability"] == ["Zombie NIR-A", "Zombie NIR-H"]
    with pytest.raises(ValueError, match="pns gives"):
        suggest_channels(DEMO_PNN, DEMO_PNS[:-1])


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("Zombie Aqua-A", "viability"),
        ("LIVE/DEAD Fixable Near-IR", "viability"),
        ("LiveDead", "viability"),
        ("Fixable Viability Dye eFluor 780", "viability"),
        ("FVS780-A", "viability"),
        ("7-AAD-A", "viability"),
        ("DAPI-A", "viability"),
        ("Propidium Iodide", "viability"),
        ("PI-A", "viability"),
        ("CD45", "cd45"),
        ("anti-CD45 PerCP", "cd45"),
        ("CD45RA", None),
        ("CD45RO", None),
        ("CD45R", None),
        ("CD450", None),
        # an isoform written apart from CD45 is still the isoform, not CD45
        ("CD45-RA", None),
        ("CD45 RA", None),
        ("CD45_RO", None),
        ("CD45.RA", None),
        ("CD45/RA", None),
        ("CD45 R", None),
        ("CD45-RB", None),
        ("CD45 RABC", None),
        ("CD45 RO-PE", None),
        # the CD45.1 and CD45.2 allotypes are CD45, and so is CD45 with its fluorochrome
        ("CD45.1", "cd45"),
        ("CD45.2", "cd45"),
        ("CD45 PerCP", "cd45"),
        ("CD45-BV570", "cd45"),
        ("PIK3", None),
        ("Spinal", None),
        ("CD3", None),
    ],
)
def test_names_that_do_and_dont_read_as_a_role(name, role):
    got = suggest_channels(["FSC-A", name])
    assert {r for r in livecells.ROLES if got[r] == name} == ({role} if role else set())


@pytest.mark.parametrize("spelling", ["CD45-RA", "CD45 RA", "CD45_RA", "CD45.RA", "CD45/RA"])
def test_both_public_panels_keep_their_cd45_with_an_isoform_spelled_apart(spelling):
    """The demo panel's own CD45RA label (BUV395-A) and, in the Zenodo 18367404 panel, its CD27
    label (BB700-A) written as an isoform spelled apart: the panel's CD45 channel is still the one
    suggestion and the only candidate."""
    demo = list(DEMO_PNS)
    demo[DEMO_PNN.index("FJComp-BUV395-A")] = spelling
    got = suggest_channels(DEMO_PNN, demo)
    assert (got["cd45"], got["candidates"]["cd45"]) == ("FJComp-PerCP-A", ["FJComp-PerCP-A"])
    nkg2a = list(NKG2A_PNS)
    nkg2a[NKG2A_PNN.index("BB700-A")] = spelling.replace("RA", "RO")
    got = suggest_channels(NKG2A_PNN, nkg2a)
    assert (got["cd45"], got["candidates"]["cd45"]) == ("BV570-A", ["BV570-A"])


def test_the_steps_display_defaults_live_in_defaults():
    from datanuggets_flow import _defaults

    for name in (
        "LIVECELLS_BINS",
        "LIVECELLS_RANGE_QUANTILES",
        "LIVECELLS_RANGE_PAD",
        "LIVECELLS_FLAT_WIDTH",
        "LIVECELLS_SCHEMA",
    ):
        assert getattr(livecells, name) is getattr(_defaults, name), name


@pytest.mark.parametrize("env", sorted(RECORDS))
def test_the_lists_are_the_files(env):
    folder = os.environ.get(env)
    if not folder:
        pytest.skip(f"{env} doesn't name a folder of the record's FCS files")
    stems, pnn, pns = RECORDS[env]
    for stem in stems:
        fd = flowio.FlowData(str(Path(folder) / f"{stem}.fcs"), only_text=True)
        c = fd.channel_count
        assert tuple(fd.text[f"p{k}n"] for k in range(1, c + 1)) == pnn, stem
        assert tuple(fd.text.get(f"p{k}s", "").strip() for k in range(1, c + 1)) == pns, stem


# ---- kept_values --------------------------------------------------------------------------


def test_kept_values_are_the_chosen_populations_raw_cells(gated, values):
    assert values.channels == tuple(gated["channels"])
    assert values.labels == (
        "CD8 (FJComp-Alexa Fluor 700-A)",
        "CD3 (FJComp-BV510-A)",
        "CD4 (FJComp-Spark Blue-A)",
    )
    for i, f in enumerate(values.files):
        s = gated["samples"][i]
        assert (f.number, f.name, f.events) == (i + 1, s["path"].name, s["n_events"])
        assert f.pops == tuple(gated["chosen"][i])
        assert f.values.dtype == np.float64
        np.testing.assert_array_equal(f.values, _direct(gated, i, gated["channels"]))
    assert [f.kept for f in values.files] == [
        int(pick_events(s["masks"], pops).sum())
        for s, pops in zip(gated["samples"], gated["chosen"])
    ]


def test_a_file_left_out_isnt_read(gated):
    seen = []

    def read(path):
        seen.append(Path(path).name)
        return read_events(path)

    kv = kept_values(gated["samples"], [[], [1]], gated["channels"][:1], read=read)
    assert seen == ["b.fcs"]
    assert kv.files[0].values.shape == (0, 1)
    assert kv.files[0].pops == ()
    counted = count_kept(kv, [])
    assert [f["left_out"] for f in counted["files"]] == [True, False]


@pytest.mark.parametrize(
    ("chosen", "channels", "param", "text"),
    [
        (None, [], "channels", "names no channel"),
        (None, ["FJComp-BV510-A", "FJComp-BV510-A"], "channels", "repeats a channel"),
        (None, ["FJComp-PerCP-A"], "channels", "a.fcs doesn't have"),
        ([[1]], None, "pops", "gives 1 choices for 2 files"),
        ([[1], [0]], None, "pops", "there is no Pop 0"),
        ([[1], [99]], None, "pops", "there is no Pop 99"),
        ([[], []], None, "pops", "keeps no cells in any file"),
    ],
)
def test_kept_values_refuses_bad_choices_before_reading(gated, chosen, channels, param, text):
    def read(path):
        raise AssertionError("read a file")

    with pytest.raises(FlowError, match=text) as caught:
        kept_values(
            gated["samples"],
            gated["chosen"] if chosen is None else chosen,
            gated["channels"] if channels is None else channels,
            read=read,
        )
    assert caught.value.param == param


def test_kept_values_refuses_a_file_that_isnt_the_one_gated(gated):
    def read(path):
        events, pnn, pns = read_events(path)
        return events[:-1], pnn, pns

    with pytest.raises(FlowError, match="isn't the file that was gated"):
        kept_values(gated["samples"], gated["chosen"], gated["channels"], read=read)


def test_saved_values_load_back_exactly(gated, values):
    path = save_kept_values(values, gated["tmp"] / "values.cache")
    assert path.name == "values.cache"  # no extension added
    with np.load(path) as arrays:
        # the FCS files store float32, so float32 holds every value read
        assert {arrays[f"values_{f.number}"].dtype.name for f in values.files} == {"float32"}
    back = load_kept_values(path)
    assert (back.channels, back.labels) == (values.channels, values.labels)
    for a, b in zip(back.files, values.files):
        assert a._replace(values=None) == b._replace(values=None)
        assert a.values.dtype == np.float64
        np.testing.assert_array_equal(a.values, b.values)
    # values float32 can't hold stay float64
    scaled = KeptValues(
        values.channels,
        values.labels,
        tuple(f._replace(values=np.arcsinh(f.values / 7)) for f in values.files),
    )
    back = load_kept_values(save_kept_values(scaled, gated["tmp"] / "scaled.npz"))
    for a, b in zip(back.files, scaled.files):
        np.testing.assert_array_equal(a.values, b.values)
    np.savez(gated["tmp"] / "other.npz", record=np.array('{"schema": "something else"}'))
    with pytest.raises(ValueError, match="isn't a datanuggets-livecells/1 file"):
        load_kept_values(gated["tmp"] / "other.npz")


# ---- channel_histograms -------------------------------------------------------------------


@pytest.mark.parametrize(("bins", "cofactor"), [(livecells.LIVECELLS_BINS, 6000.0), (7, 0)])
def test_histograms_count_every_kept_cell_on_shared_edges(values, bins, cofactor):
    hist = channel_histograms(values, bins=bins, cofactor=cofactor)
    assert (hist["bins"], hist["cofactor"]) == (bins, cofactor)
    assert hist["kept"] == sum(f.kept for f in values.files)
    assert [f["kept"] for f in hist["files"]] == [f.kept for f in values.files]
    assert [f["pops"] for f in hist["files"]] == [list(f.pops) for f in values.files]
    for j, ch in enumerate(hist["channels"]):
        assert (ch["channel"], ch["label"]) == (values.channels[j], values.labels[j])
        edges = np.asarray(ch["edges"])
        assert len(edges) == bins + 1 and (edges[0], edges[-1]) == (ch["lo"], ch["hi"])
        assert np.all(np.diff(edges) > 0)
        t_all = [
            np.arcsinh(f.values[:, j] / cofactor) if cofactor else f.values[:, j]
            for f in values.files
        ]
        pooled = np.concatenate(t_all)
        # the range lies inside the data and spans at least its central quantiles
        q_lo, q_hi = np.quantile(pooled, livecells.LIVECELLS_RANGE_QUANTILES)
        assert pooled.min() <= ch["lo"] <= q_lo and q_hi <= ch["hi"] <= pooled.max()
        for f, got, t in zip(values.files, ch["files"], t_all):
            assert got["number"] == f.number
            inside = t[(t >= ch["lo"]) & (t <= ch["hi"])]
            # each cell's bin found here by the edges themselves
            want = np.bincount(np.digitize(inside, edges[1:-1]), minlength=bins)
            assert got["counts"] == want.tolist()
            assert got["below"] == int((t < ch["lo"]).sum())
            assert got["above"] == int((t > ch["hi"]).sum())
            assert sum(got["counts"]) + got["below"] + got["above"] + got["nan"] == f.kept
        assert ch["counts"] == np.sum([g["counts"] for g in ch["files"]], axis=0).tolist()
        for key in ("below", "above", "nan"):
            assert ch[key] == sum(g[key] for g in ch["files"])
    # 202's tails reach past the quantiles, so cells outside the range are counted, not dropped
    assert sum(ch["below"] + ch["above"] for ch in hist["channels"]) > 0


def test_with_cofactor_0_an_edge_is_the_raw_value_a_filter_takes(values):
    """cofactor 0 bins the raw values, so t is the raw value itself, not cofactor * sinh(t), which
    would be 0: a filter at an edge keeps exactly the cells the bins below it hold."""
    hist = channel_histograms(values, bins=16, cofactor=0)
    for ch in hist["channels"]:
        for m in (1, 8, 15):
            edge = ch["edges"][m]
            got = count_kept(values, [RowFilter(ch["channel"], "<", edge)])
            for f, g in zip(got["files"], ch["files"]):
                assert f["passed"] == g["below"] + sum(g["counts"][:m]), (ch["channel"], m)


def test_histograms_refuse_bad_bins_and_cofactors(values):
    for bins in (0, 2.5, True):
        with pytest.raises(FlowError) as caught:
            channel_histograms(values, bins=bins)
        assert caught.value.param == "bins"
    for cofactor in (-1, float("nan"), float("inf")):
        with pytest.raises(FlowError) as caught:
            channel_histograms(values, cofactor=cofactor)
        assert caught.value.param == "cofactor"


# ---- count_kept ---------------------------------------------------------------------------


def test_count_kept_equals_a_direct_filter_mask_count(gated, values):
    two = kept_values(gated["samples"], gated["chosen"], gated["channels"][:2])
    specs = _thresholds(channel_histograms(two))
    got = count_kept(two, specs)
    assert got["row_filters"] == specs
    filters = [parse_filter(s) for s in specs]
    for i, f in enumerate(got["files"]):
        raw = _direct(gated, i, gated["channels"])
        mask = filter_mask(lambda c, x=raw: x[:, gated["channels"].index(c)], filters, len(raw))
        assert (f["kept"], f["passed"]) == (len(raw), int(mask.sum()))
        assert f["left_out"] == (f["passed"] < MIN_KEPT_EVENTS)
        assert 0 < f["passed"] < f["kept"]  # the middle edges keep some cells, not all
    assert got["kept"] == sum(f["kept"] for f in got["files"])
    assert got["passed"] == sum(f["passed"] for f in got["files"])
    # the same counts from the values saved and loaded back, and from RowFilters
    back = load_kept_values(save_kept_values(two, gated["tmp"] / "two.npz"))
    assert count_kept(back, filters) == got
    none = count_kept(two, [])
    assert [f["passed"] for f in none["files"]] == [f.kept for f in two.files]


def test_count_kept_equals_what_the_run_keeps(gated, tmp_path):
    two = kept_values(gated["samples"], gated["chosen"], gated["channels"][:2])
    specs = _thresholds(channel_histograms(two))
    settings = ClusterSettings(
        row_filters=tuple(specs),
        exclude_channels=(gated["channels"][0],),
        dn_num1=500,
        dn_num2=50,
        k=3,
        n_jobs=1,
        tsne=False,
        cells_per_file=0,
    )
    result = cluster_stage(gated["samples"], gated["chosen"], tmp_path, settings)
    assert gated["channels"][0] not in result.channels  # excluded from the clustering
    selection = pd.read_csv(tmp_path / "selection.csv")
    got = count_kept(two, specs)
    assert selection["kept"].tolist() == [f["kept"] for f in got["files"]]
    assert selection["filtered"].tolist() == [f["passed"] for f in got["files"]]
    assert [len(kp.rows) for kp in result.kept] == [
        f["passed"] for f in got["files"] if not f["left_out"]
    ]


def test_count_kept_refuses_filters_it_cant_count(values):
    for specs, text in (
        (["FJComp-PerCP-A > 1"], "which these values don't hold"),
        (["FJComp-BV510-A >"], "has no value"),
        (["FJComp-BV510-A between 2,1"], "lo <= hi"),
    ):
        with pytest.raises(FlowError, match=text) as caught:
            count_kept(values, specs)
        assert caught.value.param == "row_filters"
