"""The Transform stage's cofactor, "auto" by default: a run picks one per clustered channel, once,
before any arcsinh, from the raw values of the cells it clusters (the populations kept, after the
row filters, in the files make_nuggets keeps). A channel with at least 1% of those cells below 0
takes the spread of its cells below 0 (the median of |x| over 0.6745), at least 150; any other
takes 150. A number, 0 included, overrides it for every channel and is recorded as set, and a run
given one never tallies. The rule runs here on two stand-in files read by a counting reader, on
202's real events, and on real public files when DATANUGGETS_DEMO_FCS names the folder of the
Aurora demo files (Zenodo 22079206: 190.fcs, 193.fcs, 199.fcs, 223.fcs) and
DATANUGGETS_RANGE_262144_FCS a folder of FACSAria-type files such as FlowCAP's, whose marker
channels all declare $PnR 262144."""

import json
import os
import re
from pathlib import Path

import flowio
import numpy as np
import pytest
from datanuggets.filters import filter_mask, parse_filter

from datanuggets_flow import pick, state
from datanuggets_flow._pipeline.stages import _transform_event
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.livecells import (
    FileValues,
    KeptValues,
    channel_histograms,
    kept_values,
    load_kept_values,
    save_kept_values,
)
from datanuggets_flow.pick import main
from datanuggets_flow.pipeline import (
    Cofactor,
    _kept_cells,
    auto_cofactor,
    cluster_stage,
    decode_ranges,
    gate_stage,
    make_nuggets,
    negative_tally,
    pick_events,
    pooled_scaling,
    read_fcs,
    read_ranges,
    resolve_channels,
    resolve_cofactor,
)
from datanuggets_flow.settings import ClusterSettings, GateSettings
from flowcases import FLOW, read_202

TAKES = "it takes auto, 0 (linear) or a positive number"
BIN = 10 ** (1 / 400) - 1  # the tally's resolution: one bin's width, 0.58%
MAD_Z = 0.6745
HEADER = (
    "\nTransform: arcsinh(x / c) of every clustered channel, c per channel (auto: the SD of the "
    "cells below 0 where at least 1% of the kept cells are below 0, at least 150; else 150)"
)
SET = "\nTransform: arcsinh(x / 6000) of every clustered channel; cofactor 6000 as set"
NONE = "\nTransform: none; the channels are clustered as stored"

# ---- two stand-in files ------------------------------------------------------------------------

NAMES = ["FSC-A", "SSC-A", "CD3-A", "CD8-A", "CD19-A"]
PNS = ["", "", "CD3", "CD8", ""]
CHANNELS = NAMES[2:]
LABELS = ["CD3 (CD3-A)", "CD8 (CD8-A)", "CD19-A"]
N = 4_000


def _events(seed):
    """N events: CD3 with a quarter of its cells below 0 in a cloud of SD 30, CD8 with a fifth
    below 0 in one of SD 500, and CD19 with 0.2% of its cells far below 0, too few for a spread."""
    rng = np.random.default_rng(seed)
    off = rng.random(N)
    cd3 = np.where(off < 0.5, rng.normal(0, 30, N), rng.normal(20_000, 3_000, N))
    cd8 = np.where(off < 0.4, rng.normal(0, 500, N), rng.normal(30_000, 5_000, N))
    cd19 = rng.normal(6_000, 800, N)
    cd19[: N // 500] = -2_000.0
    scatter = rng.uniform(1e4, 2e5, (N, 2))
    return np.column_stack((scatter, cd3, cd8, cd19))


FILES = {"a.fcs": _events(1), "b.fcs": _events(2)}


def _masks(cut):
    """Pop 1, the events before cut, and Pop 2, the rest."""
    masks = np.zeros((N, 2), dtype=bool)
    masks[:cut, 0] = True
    masks[cut:, 1] = True
    return masks


# b.fcs's Pop 2 is its last event alone, too few cells for a file to count
SAMPLES = [
    {"number": i + 1, "path": Path(name), "n_events": N, "pnn": NAMES, "pns": PNS, "masks": m}
    for i, (name, m) in enumerate((("a.fcs", _masks(2_800)), ("b.fcs", _masks(N - 1))))
]
CHOSEN = [[1, 2], [1]]
RUN = {"dn_num2": 40, "k": 3, "n_jobs": 1, "tsne": False}


def _reader():
    """A stand-in for read_fcs over FILES, and the names it was asked for, in order."""
    seen = []

    def read(path):
        seen.append(Path(path).name)
        return FILES[Path(path).name].copy(), list(NAMES), list(PNS)

    return read, seen


def _no_read(path):
    pytest.fail(f"read {path}")


def _no_tally():
    pytest.fail("tallied the cells")


def _raw(chosen, specs=()):
    """Each file's kept cells' raw values on CHANNELS, selected here without the pipeline."""
    filters = [parse_filter(s) for s in specs]
    found = []
    for s, pops in zip(SAMPLES, chosen):
        x = FILES[s["path"].name][np.flatnonzero(pick_events(s["masks"], pops))]
        keep = filter_mask(lambda c, x=x: x[:, NAMES.index(c)], filters, len(x))
        found.append(x[keep][:, 2:])
    return found


def _rule(x):
    """Each column's negative fraction and spread, and its cofactor, exactly. The median is the
    value at rank m / 2 of the m cells below 0, the lower of the two middle ones for an even m, as
    the tally reads it; numpy's averages the two, which a few hundred cells can set apart by more
    than a bin."""
    negative, spread, values = [], [], []
    for col in np.asarray(x).T:
        below = np.sort(-col[col < 0])
        f = len(below) / len(col)
        sd = float(below[(len(below) - 1) // 2]) / MAD_Z if len(below) else None
        negative.append(f)
        spread.append(sd)
        values.append(max(150.0, sd) if sd is not None and f >= 0.01 else 150.0)
    return negative, spread, values


class _Stop(Exception):
    """Raised by an on_event that has seen the transform event, to end the run there."""


def _transform(tmp_path, settings, read=None, events=None):
    """The transform event cluster_stage gives with these settings; the run stops there. events,
    when given, gets every event before it."""
    seen = []

    def stop(event):
        if event.stage == "transform":
            seen.append(event)
            raise _Stop
        if events is not None:
            events.append(event)

    with pytest.raises(_Stop):
        cluster_stage(SAMPLES, CHOSEN, tmp_path, settings, read=read or _reader()[0], on_event=stop)
    return seen[0]


# ---- the clustering stage ----------------------------------------------------------------------


def test_auto_takes_each_channel_from_the_raw_values_the_run_clusters(tmp_path):
    """CD8's cloud below 0 has SD 500, so CD8 takes about 500; CD3's has SD 30 and takes 150;
    CD19's spread is wide but comes from 0.2% of its cells, so it takes 150. Every step after
    applies each channel's own cofactor: the Scale stage pools arcsinh(x / c) column by column."""
    read, _ = _reader()
    run = cluster_stage(SAMPLES, CHOSEN, tmp_path, ClusterSettings(**RUN), read=read)
    x = np.vstack(_raw(CHOSEN))
    negative, spread, values = _rule(x)
    got = run.cofactor
    assert (got.value, got.source, got.range) == (150.0, "auto", None)
    assert got.negative == tuple(negative)
    assert got.spread == pytest.approx(spread, rel=BIN)
    assert got.values == (150.0, got.spread[1], 150.0)
    assert got.values[1] == pytest.approx(values[1], rel=BIN)
    assert got.values[1] == pytest.approx(500, rel=0.1) and spread[2] > 150
    c = np.array(got.values)
    t = np.arcsinh(x / c)
    np.testing.assert_allclose(run.pool.scaling.mean, t.mean(axis=0), rtol=1e-12)
    np.testing.assert_allclose(run.pool.scaling.sd, t.std(axis=0), rtol=1e-12)
    cell, _ = _kept_cells(SAMPLES[0], np.array([0]), CHANNELS, got.applied, read)
    np.testing.assert_array_equal(cell[0], np.arcsinh(FILES["a.fcs"][0, 2:] / c))


@pytest.mark.parametrize(
    ("cofactor", "reads", "tallied"),
    [("auto", 4, True), (6000.0, 3, False), (0, 3, False)],
)
def test_only_auto_reads_the_files_once_more(tmp_path, cofactor, reads, tallied):
    """The tally is one more pass over each file, before the transform event, a "cofactor"
    progress event per file with the cells it counted; a number skips it. The default channels'
    check for values that aren't numbers is a pass of its own, first, a "channels" event per
    file the same way."""
    read, seen = _reader()
    events = []
    settings = ClusterSettings(cofactor=cofactor, **RUN)
    cluster_stage(SAMPLES, CHOSEN, tmp_path, settings, read=read, on_event=events.append)
    assert seen.count("a.fcs") == seen.count("b.fcs") == reads
    tally = [("cofactor", 1), ("cofactor", 2)] if tallied else []
    assert [(e.stage, e.file) for e in events] == [
        ("channels", 1),
        ("channels", 2),
        ("select", None),
        *tally,
        ("transform", None),
        ("scale", 1),
        ("scale", 2),
        ("scale", None),
        ("nuggets", 1),
        ("nuggets", 2),
        ("cluster", None),
        ("figures", None),
    ]
    counted = [(2, "", {"cells": N}), (2, "", {"cells": N - 1})]
    assert [(e.n_files, e.message, e.data) for e in events[:2]] == counted
    if tallied:
        assert [(e.n_files, e.message, e.data) for e in events[3:5]] == counted


def test_the_transform_event_gives_each_channels_cofactor_and_why(tmp_path):
    read, _ = _reader()
    want = auto_cofactor(negative_tally(SAMPLES, CHOSEN, CHANNELS, ClusterSettings(), read=read))
    event = _transform(tmp_path, ClusterSettings())
    (f0, f1, f2), (sd0, sd1, _) = want.negative, want.spread
    assert event.message == "\n".join(
        [
            HEADER,
            f"  CD3 (CD3-A): 150  ({100 * f0:.1f}% below 0, SD {sd0:,.0f})",
            f"  CD8 (CD8-A): {want.values[1]:,.0f}  ({100 * f1:.1f}% below 0, SD {sd1:,.0f})",
            f"  CD19-A: 150  ({100 * f2:.1f}% below 0)",
        ]
    )
    assert event.data == {"transform": want.transform()}


def test_the_transform_lines_read_as_the_spec_writes_them():
    cofactor = Cofactor(150.0, "auto", None, (338.4, 150.0), (0.123, 0.002), (338.4, 500.0))
    event = _transform_event(cofactor, ["CD8 (BV510-A)", "CD3 (FITC-A)"], 2)
    lines = [
        HEADER,
        "  CD8 (BV510-A): 338  (12.3% below 0, SD 338)",
        "  CD3 (FITC-A): 150  (0.2% below 0)",
    ]
    assert event.message == "\n".join(lines)
    assert (event.stage, event.file, event.n_files) == ("transform", None, 2)


@pytest.mark.parametrize(
    ("cofactor", "line", "record"),
    [
        (6000.0, SET, Cofactor(6000.0, "set")),
        (6000, SET, Cofactor(6000.0, "set")),
        (0, NONE, Cofactor(0.0, "set")),
    ],
)
def test_a_number_keeps_its_line_and_record(tmp_path, cofactor, line, record):
    events = []
    event = _transform(tmp_path, ClusterSettings(cofactor=cofactor), events=events)
    assert event.message == line
    assert event.data == {"transform": record.transform()}
    assert [e.stage for e in events] == ["channels", "channels", "select"]  # no tally


def test_row_filters_change_the_tally(tmp_path):
    """Cells a filter takes away don't count: with CD8-A >= 0 no kept cell is below 0 on CD8."""
    specs = ("CD8-A >= 0",)
    events = []
    event = _transform(tmp_path, ClusterSettings(row_filters=specs), events=events)
    record = event.data["transform"]
    kept = _raw(CHOSEN, specs)
    x = np.vstack(kept)
    assert (record["negative_fraction"][1], record["negative_sd"][1]) == (0.0, None)
    assert record["cofactors"][1] == 150.0
    assert record["negative_fraction"][0] == (x[:, 0] < 0).sum() / len(x)
    assert [e.data["cells"] for e in events if e.stage == "cofactor"] == [len(k) for k in kept]
    assert len(x) < sum(len(k) for k in _raw(CHOSEN))


@pytest.mark.parametrize("specs", [(), ("FSC-A > 0",)], ids=["unread", "read"])
def test_a_file_keeping_too_few_cells_counts_for_nothing(specs):
    """b.fcs's Pop 2 is one cell: unread without filters, read and passed over with them, and
    the tally is the one without the file either way."""
    read, _ = _reader()
    settings = ClusterSettings(row_filters=specs)
    events = []
    few = negative_tally(
        SAMPLES, [[1, 2], [2]], CHANNELS, settings, read=read, on_event=events.append
    )
    alone = negative_tally(SAMPLES, [[1, 2], []], CHANNELS, settings, read=read)
    for name in ("cells", "negative", "counts"):
        np.testing.assert_array_equal(getattr(few, name), getattr(alone, name))
    assert few.cells.tolist() == [N] * 3
    assert [(e.stage, e.file, e.data) for e in events] == [
        ("cofactor", 1, {"cells": N}),
        ("cofactor", 2, {"cells": 0}),
    ]


def test_filters_that_keep_nothing_stop_the_tally(tmp_path):
    settings = ClusterSettings(row_filters=("CD8-A > 1e12",))
    with pytest.raises(FlowError, match="row_filters keeps fewer than 2 cells in every file"):
        cluster_stage(SAMPLES, CHOSEN, tmp_path, settings, read=_reader()[0])


def test_the_steps_after_the_resolve_never_take_auto():
    read, _ = _reader()
    for step in (pooled_scaling, make_nuggets):
        with pytest.raises(FlowError, match="resolve_cofactor") as caught:
            step(SAMPLES, CHOSEN, CHANNELS, ClusterSettings(), read=read)
        assert caught.value.param == "cofactor"


def test_a_bad_cofactor_stops_cluster_stage_before_any_file_is_read(tmp_path):
    with pytest.raises(FlowError, match=re.escape(TAKES)):
        cluster_stage(SAMPLES, CHOSEN, tmp_path, ClusterSettings(cofactor="Auto"), read=_no_read)
    assert list(tmp_path.iterdir()) == []


# ---- the records -------------------------------------------------------------------------------


AUTO = Cofactor(150.0, "auto", None, (150.0, 512.5), (0.25, 0.2), (31.0, 512.5))
AUTO_RECORD = {
    "name": "arcsinh",
    "cofactor_from": "auto",
    "cofactors": [150.0, 512.5],
    "negative_fraction": [0.25, 0.2],
    "negative_sd": [31.0, 512.5],
    "floor": 150.0,
    "min_negative_fraction": 0.01,
}
SET_6000 = {"name": "arcsinh", "cofactor": 6000.0, "cofactor_from": "set"}
# the record of a run made under the earlier rule, picked from the files' headers
RANGE_150 = {"name": "arcsinh", "cofactor": 150.0, "cofactor_from": "auto", "range": 262144.0}


@pytest.mark.parametrize("value", [150, 150.0, 6000.0, 0, 0.0, 37.5, np.float64(6000.0)])
def test_a_number_is_honoured_as_set_without_a_tally(value):
    got = resolve_cofactor(value, _no_tally)
    assert got == Cofactor(float(value), "set", None)
    assert type(got.value) is float and got.values is None
    assert got.applied == float(value) and type(got.applied) is float
    np.testing.assert_array_equal(got.per_channel(3), np.full(3, float(value)))


@pytest.mark.parametrize(
    "value",
    ["Auto", "AUTO", " auto", "6000", "", -1.0, float("nan"), float("inf"), True, None, (150.0,)],
)
def test_only_auto_or_a_number_from_0_is_taken(value):
    """A user gives one cofactor for every channel: a list of them isn't taken."""
    with pytest.raises(FlowError) as caught:
        resolve_cofactor(value, _no_tally)
    assert caught.value.param == "cofactor"
    assert str(caught.value) == f"cofactor is {value}; {TAKES}"
    with pytest.raises(FlowError) as caught:
        ClusterSettings(cofactor=value).check()
    assert (caught.value.param, str(caught.value)) == ("cofactor", f"cofactor is {value}; {TAKES}")


def test_the_settings_keep_auto_as_asked():
    settings = ClusterSettings()
    assert settings.cofactor == "auto" and settings.check() is settings
    assert settings.to_dict()["cofactor"] == "auto"
    assert ClusterSettings.from_dict(settings.to_dict()) == settings
    assert ClusterSettings(cofactor=0).check().cofactor == 0


def test_the_transform_record_says_how_the_cofactor_was_chosen():
    assert AUTO.transform() == AUTO_RECORD
    assert "cofactor" not in AUTO_RECORD  # one number would mislead
    assert AUTO.applied == (150.0, 512.5)
    np.testing.assert_array_equal(AUTO.per_channel(2), [150.0, 512.5])
    with pytest.raises(ValueError, match="2 channels"):
        AUTO.per_channel(3)
    assert Cofactor(6000.0, "set").transform() == SET_6000
    assert Cofactor(0.0, "set").transform() == {"name": "none"}
    # records of the earlier header rule keep their shape
    assert Cofactor(150.0, "auto", 262144.0).transform() == RANGE_150
    assert Cofactor(6000.0, "auto", None).transform() == {
        "name": "arcsinh",
        "cofactor": 6000.0,
        "cofactor_from": "auto",
        "range": None,
    }


@pytest.mark.parametrize(
    ("asked", "cofactor", "transform"),
    [
        ("auto", AUTO, AUTO_RECORD),
        ("auto", Cofactor(150.0, "auto", 262144.0), RANGE_150),
        (6000, None, SET_6000),
        (6000.0, Cofactor(6000.0, "set"), SET_6000),
        (0, None, {"name": "none"}),
        (0.0, Cofactor(0.0, "set"), {"name": "none"}),
    ],
)
def test_run_json_records_the_cofactor_used_and_the_one_asked(tmp_path, asked, cofactor, transform):
    settings = ClusterSettings(cofactor=asked, standardize=False)
    channels = ["CD3-A", "CD4-A"]
    path = state.write_run(
        tmp_path, tmp_path / "gates", settings, [[1]], channels, channels, cofactor=cofactor
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["transform"] == transform
    assert record["settings"]["cofactor"] == asked
    assert ClusterSettings.from_dict(record["settings"]) == settings
    assert state.run_transform(record) == transform


@pytest.mark.parametrize(
    ("asked", "cofactor", "channels"),
    [
        ("auto", None, 2),  # auto needs the run's cofactor
        ("auto", Cofactor(6000.0, "set"), 2),
        ("auto", AUTO, 3),  # one cofactor per channel clustered
        (6000.0, Cofactor(150.0, "set"), 2),
        (150.0, Cofactor(150.0, "auto", 262144.0), 2),
        (150.0, AUTO, 2),
        (0, Cofactor(6000.0, "set"), 2),
    ],
)
def test_write_run_refuses_a_cofactor_the_settings_contradict(tmp_path, asked, cofactor, channels):
    settings = ClusterSettings(cofactor=asked, standardize=False)
    names = ["CD3-A", "CD4-A", "CD8-A"][:channels]
    with pytest.raises(ValueError, match="result.cofactor"):
        state.write_run(
            tmp_path, tmp_path / "gates", settings, [[1]], names, names, cofactor=cofactor
        )
    assert not (tmp_path / "run.json").exists()


def test_an_older_run_json_reads_as_set():
    """run.json written before cofactor_from existed held a number set or defaulted; one written
    before the Transform stage was recorded has its settings' cofactor alone."""
    old = {"settings": {"cofactor": 6000.0}, "transform": {"name": "arcsinh", "cofactor": 6000.0}}
    assert state.run_transform(old) == SET_6000
    assert state.run_transform({"settings": {"cofactor": 0}, "transform": {"name": "none"}}) == {
        "name": "none"
    }
    assert state.run_transform({"settings": {"cofactor": 6000.0}}) == SET_6000
    assert state.run_transform({"settings": {"cofactor": 0.0}}) == {"name": "none"}
    assert state.run_transform({"settings": {}}) == SET_6000
    assert ClusterSettings.from_dict({"cofactor": 6000.0, "k": 5}).cofactor == 6000.0


def test_a_per_channel_or_header_rule_record_reads_back_as_written():
    for transform in (AUTO_RECORD, RANGE_150):
        record = {"settings": {"cofactor": "auto"}, "transform": transform}
        assert state.run_transform(json.loads(json.dumps(record))) == transform


def test_a_record_asking_auto_with_no_transform_says_the_cofactor_is_unknown():
    """write_run never writes one, but a record cut short or made by hand is refused by name, not
    with float's own error."""
    with pytest.raises(ValueError, match="cofactor 'auto' but no transform"):
        state.run_transform({"settings": {"cofactor": "auto"}})


# ---- the command -------------------------------------------------------------------------------


def test_the_flag_takes_auto_or_a_number():
    parser = pick._parser()
    assert parser.parse_args([]).cofactor is None  # the settings' default, auto
    assert parser.parse_args(["--cofactor", "auto"]).cofactor == "auto"
    assert parser.parse_args(["--cofactor", "150"]).cofactor == 150.0
    assert parser.parse_args(["--cofactor", "0"]).cofactor == 0.0
    shown = " ".join(parser.format_help().split())
    assert (
        "auto (the default) picks one per channel from the spread of its cells below 0, at least "
        "150; a number applies to every channel; 0 keeps the channels linear" in shown
    )


@pytest.mark.parametrize(("value", "shown"), [("Auto", "Auto"), ("x", "x"), ("-1", "-1.0")])
def test_the_flag_refuses_anything_else_before_any_file_is_read(tmp_path, value, shown):
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as e:
        main([str(tmp_path / "missing"), "--cofactor", value, "--no-show", "--out", str(out)])
    assert e.value.code == f"--cofactor is {shown}; {TAKES}"
    assert not out.exists()


def test_from_gates_records_the_auto_cofactor_and_a_number_overrides_it(
    tmp_path, monkeypatch, close_figures, capsys
):
    """On 202's real events: run.json records each channel's cofactor, picked from the raw values
    of the Pop 6 cells it clusters."""
    monkeypatch.setattr(pick, "read_fcs", read_202)
    folder, gates = tmp_path / "in", tmp_path / "gates"
    folder.mkdir()
    (folder / "202.fcs").write_bytes(b"")
    main([str(folder), "--gates-only", "--no-show", "--out", str(gates)])
    argv = ["--from-gates", str(gates), "--pops", "6", "--no-show", "--no-tsne"]
    argv += ["--dn-num2", "40", "--k", "3"]
    capsys.readouterr()
    main([*argv, "--out", str(tmp_path / "auto")])
    assert HEADER in capsys.readouterr().out
    run = json.loads((tmp_path / "auto" / "run.json").read_text(encoding="utf-8"))
    events, _, _ = read_202(None)
    masks = state.load_gates(gates).samples[0]["masks"]
    negative, spread, values = _rule(events[np.flatnonzero(masks[:, 5])][:, 2:])
    transform = run["transform"]
    assert run["settings"]["cofactor"] == "auto"
    assert list(transform) == list(AUTO_RECORD)
    assert transform["negative_fraction"] == negative
    assert transform["negative_sd"] == pytest.approx(spread, rel=BIN)
    assert transform["cofactors"] == pytest.approx(values, rel=BIN)
    main([*argv, "--out", str(tmp_path / "set"), "--cofactor", "6000"])
    assert SET in capsys.readouterr().out
    run = json.loads((tmp_path / "set" / "run.json").read_text(encoding="utf-8"))
    assert (run["settings"]["cofactor"], run["transform"]) == (6000.0, SET_6000)


# ---- decoding the TEXT keywords -------------------------------------------------------------
# read_ranges no longer picks the cofactor, but the app's upload step still reads it


def _text(*channels, **more):
    """TEXT keywords as an FCS file writes them, $ and upper case, for channels given as dicts
    of N, R, E and G."""
    text = {"$PAR": str(len(channels))} | {k.upper(): v for k, v in more.items()}
    for k, channel in enumerate(channels, 1):
        text |= {f"$P{k}{key}": value for key, value in channel.items()}
    return text


def test_decode_takes_pnr_as_stored_for_a_linear_channel():
    text = _text(
        {"N": "FSC-A", "R": "262144", "E": "0,0"},
        {"N": "CD3-A", "R": " 1024 ", "E": "0,0", "G": "1.0"},
        {"N": "CD4-A", "R": "4194304"},  # no $PnE and no $PnG: linear, gain 1, as flowio reads it
    )
    assert decode_ranges(text) == (["FSC-A", "CD3-A", "CD4-A"], [262144.0, 1024.0, 4194304.0])
    # flowio's own keys, lower case without $, read the same
    lower = {k.lower().lstrip("$"): v for k, v in text.items()}
    assert decode_ranges(lower) == decode_ranges(text)


def test_decode_takes_a_log_channel_to_its_top_value():
    """$PnE f1,f2 stores 10 ** (f1 * x / $PnR) * f2, so the top of the range is 10 ** f1 * f2,
    with f2 taken as 1 when it is 0."""
    text = _text(
        {"N": "CD3-A", "R": "1024", "E": "4,1"},
        {"N": "CD4-A", "R": "1024", "E": "4,0"},
        {"N": "CD8-A", "R": "262144", "E": "4.5,2"},
    )
    _, got = decode_ranges(text)
    assert got == pytest.approx([1e4, 1e4, 2 * 10**4.5], rel=1e-12)


def test_decode_divides_by_the_gain_as_flowio_does():
    """$PnG divides the values unless it is 1 or 0; a Time channel's gain is taken as 1, and its
    values are scaled by $TIMESTEP."""
    text = _text(
        {"N": "CD3-A", "R": "262144", "G": "2"},
        {"N": "CD4-A", "R": "262144", "G": "0"},
        {"N": "CD8-A", "R": "1024", "E": "4,1", "G": "0.5"},
        {"N": "Time", "R": "262144", "G": "0.01"},
        TIMESTEP="0.01",
    )
    assert decode_ranges(text)[1] == pytest.approx([131072.0, 262144.0, 2e4, 2621.44], rel=1e-12)
    no_step = _text({"N": "Time", "R": "262144", "G": "0.01"})
    assert decode_ranges(no_step)[1] == [262144.0]


@pytest.mark.parametrize(
    "channel",
    [
        {"N": "CD3-A"},  # no $PnR
        {"N": "CD3-A", "R": "lots"},
        {"N": "CD3-A", "R": "0"},
        {"N": "CD3-A", "R": "-262144"},
        {"N": "CD3-A", "R": "nan"},
        {"N": "CD3-A", "R": "inf"},
        {"N": "CD3-A", "R": "262144", "E": "4"},
        {"N": "CD3-A", "R": "262144", "E": "log"},
        {"N": "CD3-A", "R": "262144", "G": "x"},
        {"N": "CD3-A", "R": "262144", "G": "-1"},
        {"N": "CD3-A", "R": "262144", "E": "400,1"},  # past a float
    ],
)
def test_decode_gives_none_where_there_is_no_usable_range(channel):
    text = _text({"N": "FSC-A", "R": "262144"}, channel)
    assert decode_ranges(text) == (["FSC-A", "CD3-A"], [262144.0, None])


def test_read_ranges_names_the_channels_as_read_fcs_does(tmp_path):
    """flowio.create_fcs writes $PnR 262144 and $PnE 0,0 for every channel."""
    path = tmp_path / "a.fcs"
    with path.open("wb") as handle:
        flowio.create_fcs(handle, np.arange(30.0), ["FSC-A", "Time", "CD3-A"])
    names, ranges = read_ranges(path)
    assert names == read_fcs(path)[1] == ["FSC-A", "Time", "CD3-A"]
    assert ranges == [262144.0] * 3


# ---- live cells ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    """202.fcs's recorded channels written as an FCS file by flowio.create_fcs, gated and loaded
    back."""
    from datanuggets_flow.state import load_gates

    tmp = tmp_path_factory.mktemp("cofactor")
    with np.load(FLOW / "202.npz") as g, np.load(FLOW / "202_fluor.npz") as f:
        events = np.column_stack((g["fsc"], g["ssc"], f["fluor"]))
        names = ["FSC-A", "SSC-A", *f["pnn"].tolist()]
    path = tmp / "a.fcs"
    with path.open("wb") as handle:
        flowio.create_fcs(handle, events.ravel(), names)
    folder = tmp / "gates"
    folder.mkdir()
    gate_stage([path], folder, GateSettings())
    return {"samples": load_gates(folder).samples, "channels": names[2:], "tmp": tmp}


def _older(path, out, cofactor):
    """The values at path saved again at out with cofactor as their record's, or with none when
    it is ..., as values saved before it was recorded were."""
    with np.load(path) as arrays:
        older = dict(arrays)
    record = json.loads(str(older["record"]))
    if cofactor is ...:
        del record["cofactor"]
    else:
        record["cofactor"] = cofactor
    older["record"] = np.array(json.dumps(record))
    np.savez(out, **older)
    return out


def test_live_cells_take_the_cofactor_a_run_on_the_same_cells_would_pick(written):
    samples, channels = written["samples"], written["channels"]
    kept = kept_values(samples, [[1]], channels)
    run = negative_tally(samples, [[1]], channels, ClusterSettings(), read=read_fcs)
    assert kept.cofactor == auto_cofactor(run)
    negative, spread, values = _rule(kept.files[0].values)
    assert kept.cofactor.negative == tuple(negative)
    assert kept.cofactor.spread == pytest.approx(spread, rel=BIN)
    assert kept.cofactor.values == pytest.approx(values, rel=BIN)


def test_histograms_take_each_channels_own_cofactor():
    """CD8's values here are drawn on arcsinh(x / 900), the other channel's on arcsinh(x / 150);
    the keys of a set cofactor's histograms keep their order, the new ones after them."""
    rng = np.random.default_rng(5)
    x = np.column_stack((rng.normal(4000, 900, 3000), rng.normal(0, 900, 3000)))
    picked = Cofactor(150.0, "auto", None, (150.0, 900.0), (0.0, 0.5), (None, 900.0))
    files = (FileValues(1, "a.fcs", 5000, (1,), x),)
    kept = KeptValues(("CD3-A", "CD8-A"), ("CD3-A", "CD8 (CD8-A)"), files, picked)
    hist = channel_histograms(kept)
    assert list(hist) == [
        "bins",
        "kept",
        "files",
        "channels",
        "cofactor_from",
        "cofactors",
        "negative_fraction",
        "negative_sd",
    ]
    assert (hist["cofactor_from"], hist["cofactors"]) == ("auto", [150.0, 900.0])
    assert (hist["negative_fraction"], hist["negative_sd"]) == ([0.0, 0.5], [None, 900.0])
    for j, ch in enumerate(hist["channels"]):
        t = np.arcsinh(x[:, j] / picked.values[j])
        edges = np.asarray(ch["edges"])
        assert edges[0] >= t.min() and edges[-1] <= t.max()
        inside = t[(t >= ch["lo"]) & (t <= ch["hi"])]
        want = np.bincount(np.digitize(inside, edges[1:-1]), minlength=len(edges) - 1)
        assert ch["counts"] == want.tolist()
        assert sum(ch["counts"]) + ch["below"] + ch["above"] + ch["nan"] == len(x)
    assert channel_histograms(kept, cofactor="auto") == hist
    for value, cofactor in ((6000, 6000.0), (0, 0.0)):
        hist = channel_histograms(kept, cofactor=value)
        assert list(hist) == ["cofactor", "bins", "kept", "files", "channels", "cofactor_from"]
        assert (hist["cofactor"], hist["cofactor_from"]) == (cofactor, "set")
    for bad in ("Auto", "6000", -1, (150.0, 900.0)):
        with pytest.raises(FlowError, match=re.escape(TAKES)) as caught:
            channel_histograms(kept, cofactor=bad)
        assert caught.value.param == "cofactor"


def test_live_cells_read_nothing_before_their_checks(written):
    with pytest.raises(FlowError) as caught:
        kept_values(written["samples"], [[99]], written["channels"], read=_no_read)
    assert caught.value.param == "pops"


def test_saved_values_keep_the_cofactor_and_older_ones_still_draw(written):
    """Values saved with a per-channel cofactor load it back; ones saved under the header rule
    draw on its one number, and ones saved before a cofactor was recorded on 6000, the default
    they were drawn on."""
    kept = kept_values(written["samples"], [[1]], written["channels"][:1])
    path = save_kept_values(kept, written["tmp"] / "values.npz")
    assert load_kept_values(path).cofactor == kept.cofactor
    assert channel_histograms(load_kept_values(path)) == channel_histograms(kept)
    header = Cofactor(150.0, "auto", 262144.0)
    back = load_kept_values(_older(path, written["tmp"] / "header.npz", header._asdict()))
    assert back.cofactor == header
    hist = channel_histograms(back)
    assert list(hist) == ["cofactor", "bins", "kept", "files", "channels", "cofactor_from"]
    assert (hist["cofactor"], hist["cofactor_from"]) == (150.0, "auto")
    back = load_kept_values(_older(path, written["tmp"] / "older.npz", ...))
    assert back.cofactor is None
    hist = channel_histograms(back)
    assert (hist["cofactor"], hist["cofactor_from"]) == (6000.0, "auto")
    assert channel_histograms(back, cofactor=150)["cofactor"] == 150.0


# ---- real public files ---------------------------------------------------------------------------


# The channels whose cofactor rises above 150 on the whole files, by marker, and their spread: the
# median of |x| over the cells below 0, over 0.6745, measured on the same files with numpy's exact
# median. Every other channel takes 150: FlowCAP's because their spread is 16 to 36, and the
# Aurora files' because it is under 150 or comes from fewer than 1% of the cells.
RAISED = {
    "DATANUGGETS_DEMO_FCS": {
        "CD8": 337.81,
        "ACE2": 210.35,
        "CCR4": 174.85,
        "CD123": 198.57,
        "CD19": 203.83,
        "CD14": 349.97,
    },
    "DATANUGGETS_RANGE_262144_FCS": {},
}


def _whole_files(folder):
    """Every FCS file in folder as a sample whose one population is every event."""
    samples = []
    for path in sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".fcs"):
        events, pnn, pns = read_fcs(path)
        masks = np.ones((len(events), 1), dtype=bool)
        samples.append(
            {"path": path, "n_events": len(events), "pnn": pnn, "pns": pns, "masks": masks}
        )
    return samples


@pytest.mark.parametrize("env", sorted(RAISED))
def test_whole_public_files_give_the_measured_cofactors(env):
    folder = os.environ.get(env)
    if not folder:
        pytest.skip(f"{env} doesn't name a folder of FCS files")
    samples = _whole_files(folder)
    assert samples, folder
    settings = ClusterSettings()
    channels, labels = resolve_channels(samples, settings)
    got = auto_cofactor(negative_tally(samples, [[1]] * len(samples), channels, settings))
    raised = {}
    for label, c in zip(labels, got.values):
        marker = [
            m for m in RAISED[env] if re.search(rf"(?<![A-Za-z0-9]){m}(?![A-Za-z0-9])", label)
        ]
        if marker:
            raised[marker[0]] = c
            # within one bin of the exact median, so a read one bin off fails here too
            assert c == pytest.approx(RAISED[env][marker[0]], rel=BIN), label
        else:
            assert c == 150.0, label
    assert sorted(raised) == sorted(RAISED[env])
