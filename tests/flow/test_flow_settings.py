"""The flow pipeline's settings. The constants fixed for parity keep the values of Cabrera's
cfc.py, the tunable defaults live once, in _defaults, so a signature can't drift from them, and the
settings classes refuse a bad value with the message the CLI prints, the setting named as its flag
there, a flag every setting has, and by its name in the library."""

import dataclasses
import inspect
import json
import math

import pytest

import datanuggets_flow as flow
from datanuggets_flow import _defaults, gate, grid, peaks, pick
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.settings import ClusterSettings, GateSettings, cli_flag

# each constant fixed for parity with cfc.py, at the value its code has
FIXED = {
    gate: {"MSIZE": 100, "GRID_SCALE": "l", "GRID_ALPHA": 0.1, "MIN_POINTS": 3},
    grid: {"SQRT_SHIFT": 3},
    peaks: {
        "LOCAL_MAX_QUANTILE": 0.85,
        "LOCAL_MAX_EDGES": "reflect",
        "PEAK_QUANTILE": 0.9,
        "ROW_MIN": 10,
        "ROW_MAX": 90,
        "COL_MAX": 90,
        "SEARCH_THRESHOLD": 2,
        "AREA_T1": 35,
        "AREA_T2": 0.85,
    },
}
# the finder's tunable defaults, as cfc.py calls it, and the functions that take each
FINDER = {"n_row": 11, "n_col": 11, "t11": 22, "t21": 0.25, "t12": 20, "t22": 0.5}
TAKES = {
    "lymphmacro_finder": tuple(FINDER),
    "finder_peaks": ("n_row", "n_col"),
    "gate_peaks": tuple(FINDER),
    "local_maxima": ("n_row", "n_col"),
}
# datanuggets-flow's defaults, as it has always run
GATE = FINDER | {"fsc": "FSC-A", "ssc": "SSC-A", "disc": "reference", "t11": (22,), "t21": (0.25,)}
CLUSTER = {
    "channels": None,
    "exclude_channels": (),
    "cofactor": "auto",  # picked from the files' headers when the run starts
    "standardize": True,  # the Scale stage, on by default since it was added
    "dn_num1": 10_000,
    "dn_num2": 1000,
    "center_method": "original",  # Cabrera's group clusters the original points, not the means
    "seed": 291102,
    "draws": "r",  # create.DN's own draws, so the nuggets are R's
    "n_jobs": -1,
    "k": 8,
    "method": "wkmeans",  # WCluster's Wkmeans, the group's clustering of nuggets
    "num_init": 10,  # Beavers et al. (2025) Sec 4, ten initial centers
    "max_iter": 100,
    "tsne": True,
    "tsne_perplexity": 30,
    "tsne_seed": 0,
    "row_filters": (),
    "groups": None,
    "cells_per_file": 2000,
}
# settings with no default left, for the JSON round trip
CHANGED = {
    "gate": GateSettings(
        fsc="FSC-H",
        ssc="SSC-H",
        disc="peak",
        t11=(22.0, 20.0, 18.0),
        t21=(0.25, 0.5, 0.5),
        t12=19.5,
        t22=0.4,
        n_row=9,
        n_col=13,
    ),
    "cluster": ClusterSettings(
        channels=("CD3-A", "CD4-A"),
        cofactor=150.0,
        standardize=False,
        dn_num1=5000,
        dn_num2=500,
        center_method="random",
        seed=7,
        draws="numpy",
        n_jobs=2,
        k=5,
        method="tree",
        num_init=3,
        max_iter=20,
        tsne=False,
        tsne_perplexity=12.5,
        tsne_seed=3,
        row_filters=("[FJComp-BV510-A] between 0,50000", "CD3-A >= 1"),
        groups=("ctrl", "case 2", "case 2"),
        cells_per_file=0,
    ),
    "exclude": ClusterSettings(exclude_channels=("Live-A",)),
}
DISTANCE = "it takes a positive distance in grid cells"
FRACTION = "it takes a fraction of the peak's density, 0 or more"
CELLS = "it takes 1 to 100 grid cells"
COFACTOR = "it takes auto, 0 (linear) or a positive number"
WHOLE = "it takes a whole number from 0"
SEED_RANGE = "it takes a whole number from 0 to 2147483647, R's largest seed"
JOBS = "it takes -1 (every core) or 1 or more"
TWO = "choose at least two distinct fluorescence channels for clustering and PCA"
# each rule check() keeps, as the settings, the setting named and the message; the rule on how
# many values t11 and t21 give is test_gate_settings_spread_per_file_thresholds'
BAD = [
    (GateSettings(disc="hist"), "disc", "disc is 'hist'; it takes reference or peak"),
    (GateSettings(t11=(22, 0)), "t11", f"t11 is 0; {DISTANCE}"),
    (GateSettings(t12=math.nan), "t12", f"t12 is nan; {DISTANCE}"),
    (GateSettings(t21=(-0.5,)), "t21", f"t21 is -0.5; {FRACTION}"),
    (GateSettings(t22=math.inf), "t22", f"t22 is inf; {FRACTION}"),
    (GateSettings(t11=()), "t11", "t11 gives no values; give one, or one per file"),
    (GateSettings(n_row=0), "n_row", f"n_row is 0; {CELLS}"),
    (GateSettings(n_col=101), "n_col", f"n_col is 101; {CELLS}"),
    (GateSettings(n_col=5.5), "n_col", f"n_col is 5.5; {CELLS}"),
    (ClusterSettings(k=0), "k", "k is 0; it takes 1 or more clusters"),
    (ClusterSettings(dn_num1=2), "dn_num1", "dn_num1 is 2; it takes 3 or more nuggets"),
    (ClusterSettings(dn_num2=1), "dn_num2", "dn_num2 is 1; it takes 2 to 9999 nuggets per file"),
    (
        ClusterSettings(dn_num1=5, dn_num2=5),
        "dn_num2",
        "dn_num2 is 5; it takes 2 to 4 nuggets per file",
    ),
    (ClusterSettings(cofactor=-1.0), "cofactor", f"cofactor is -1.0; {COFACTOR}"),
    (ClusterSettings(cofactor=math.nan), "cofactor", f"cofactor is nan; {COFACTOR}"),
    (ClusterSettings(standardize=1), "standardize", "standardize is 1; it takes true or false"),
    (ClusterSettings(seed=-1), "seed", f"seed is -1; {SEED_RANGE}"),
    (ClusterSettings(seed=True), "seed", f"seed is True; {SEED_RANGE}"),
    # weighted k-means always draws RDraws(seed), and R's set.seed takes no larger integer
    (ClusterSettings(seed=2**31), "seed", f"seed is 2147483648; {SEED_RANGE}"),
    (ClusterSettings(tsne_seed=0.5), "tsne_seed", f"tsne_seed is 0.5; {WHOLE}"),
    (ClusterSettings(n_jobs=0), "n_jobs", f"n_jobs is 0; {JOBS}"),
    (ClusterSettings(n_jobs=-2), "n_jobs", f"n_jobs is -2; {JOBS}"),
    (ClusterSettings(channels=("CD3-A", "CD3-A")), "channels", TWO),
    (
        ClusterSettings(channels=("CD3-A", "CD4-A", "CD3-A")),
        "channels",
        "channels repeats a channel; list each channel only once",
    ),
    (
        ClusterSettings(channels=("CD3-A", "CD4-A"), exclude_channels=("Live-A",)),
        "exclude_channels",
        "exclude_channels can't be combined with channels",
    ),
    (
        ClusterSettings(tsne_perplexity=0),
        "tsne_perplexity",
        "tsne_perplexity is 0; it takes a positive number",
    ),
    (
        ClusterSettings(row_filters=("CD3-A>=1",)),
        "row_filters",
        (
            "row_filters: 'CD3-A>=1' has no operator; write COLUMN OP VALUE with one of "
            "< <= > >= == != between in between spaces"
        ),
    ),
    (
        ClusterSettings(row_filters=("CD3-A between 5,1",)),
        "row_filters",
        "row_filters: 'CD3-A between 5,1': between takes lo,hi with lo <= hi; got 5,1",
    ),
    (ClusterSettings(groups=("ctrl", "")), "groups", "groups has an empty name"),
    (
        ClusterSettings(groups=("ctrl", "a/b")),
        "groups",
        (
            "groups has 'a/b'; a name takes 1 to 40 letters, digits, spaces and _ . + -, "
            "starting with a letter or digit"
        ),
    ),
    (
        ClusterSettings(groups=("x" * 41,)),
        "groups",
        (
            f"groups has {'x' * 41!r}; a name takes 1 to 40 letters, digits, spaces and _ . + -, "
            "starting with a letter or digit"
        ),
    ),
    (ClusterSettings(cells_per_file=-1), "cells_per_file", f"cells_per_file is -1; {WHOLE}"),
    (ClusterSettings(cells_per_file=2.5), "cells_per_file", f"cells_per_file is 2.5; {WHOLE}"),
]


def _default(f, name):
    return inspect.signature(f).parameters[name].default


def test_parity_constants_keep_cabreras_values():
    for module, constants in FIXED.items():
        got = {name: getattr(module, name, None) for name in constants}
        assert got == constants, module.__name__
    assert _default(flow.f_plot, "alpha") == gate.GRID_ALPHA
    assert _default(flow.local_maxima, "quantile") == peaks.LOCAL_MAX_QUANTILE
    for f in (flow.search_ind, flow.refine_peaks):
        assert _default(f, "threshold") == peaks.SEARCH_THRESHOLD, f.__name__
    for f in (flow.find_area, flow.mirrored_area):
        assert (_default(f, "t1"), _default(f, "t2")) == (peaks.AREA_T1, peaks.AREA_T2), f.__name__


@pytest.mark.parametrize("name", TAKES)
def test_finder_signature_defaults_are_the_central_defaults(name):
    central = {k: getattr(_defaults, f"FINDER_{k.upper()}", None) for k in FINDER}
    assert central == FINDER
    got = {k: _default(getattr(flow, name), k) for k in TAKES[name]}
    assert got == {k: central[k] for k in TAKES[name]}


def test_settings_defaults_are_the_cli_defaults():
    for s, defaults in ((GateSettings(), GATE), (ClusterSettings(), CLUSTER)):
        assert dataclasses.asdict(s) == defaults
        assert s.check() is s


@pytest.mark.parametrize("name", CHANGED)
def test_settings_round_trip_through_json(name):
    s = CHANGED[name]
    data = s.to_dict()
    assert json.loads(json.dumps(data, allow_nan=False)) == data  # lists, as JSON gives them back
    assert type(s).from_dict(json.loads(json.dumps(data))) == s


def test_records_from_before_filters_and_groups_still_load():
    old = {k: v for k, v in CHANGED["cluster"].to_dict().items()}
    for key in ("row_filters", "groups", "cells_per_file"):
        old.pop(key)
    s = ClusterSettings.from_dict(old)
    assert (s.row_filters, s.groups, s.cells_per_file) == ((), None, 2000)
    assert cli_flag("row_filters") == "--filter"
    assert cli_flag("groups") == "--groups"
    assert cli_flag("cells_per_file") == "--cells-per-file"


def test_a_record_without_draws_loads_numpy():
    """A run.json written after method was recorded but before draws was (the recording server
    ran weighted k-means for a while on numpy's draws) built its nuggets on numpy's draws, so it
    loads as draws "numpy", whatever its method, not as today's default "r"."""
    for method in ("wkmeans", "tree"):
        old = ClusterSettings(method=method).to_dict()
        old.pop("draws")
        s = ClusterSettings.from_dict(json.loads(json.dumps(old)))
        assert (s.method, s.draws) == (method, "numpy")
        assert s.check() is s


def test_a_record_without_method_loads_tree_mean_numpy():
    """One written before method was recorded ran the hierarchical tree on mean centers with
    numpy's draws, and loads so; a center_method it names is kept."""
    old = ClusterSettings(k=5, cofactor=150.0).to_dict()
    for key in ("method", "center_method", "num_init", "max_iter", "draws"):
        old.pop(key)
    s = ClusterSettings.from_dict(json.loads(json.dumps(old)))
    assert (s.method, s.center_method, s.draws) == ("tree", "mean", "numpy")
    assert (s.k, s.cofactor) == (5, 150.0)
    named = ClusterSettings.from_dict({"center_method": "original", "k": 5})
    assert (named.method, named.center_method, named.draws) == ("tree", "original", "numpy")


def test_new_settings_round_trip_with_r_draws():
    s = ClusterSettings()
    back = ClusterSettings.from_dict(json.loads(json.dumps(s.to_dict())))
    assert back == s
    assert back.draws == "r"


def test_check_refuses_unknown_draws():
    for bad in ("R", "mt", None):
        with pytest.raises(FlowError) as e:
            ClusterSettings(draws=bad).check()
        assert e.value.param == "draws"
        assert str(e.value) == f"draws is {bad!r}; it takes r or numpy"
        assert e.value.cli(cli_flag) == f"--draws is {bad!r}; it takes r or numpy"


@pytest.mark.parametrize(
    ("cls", "key", "kind"), [(GateSettings, "t13", "gate"), (ClusterSettings, "disc", "cluster")]
)
def test_from_dict_rejects_unknown_keys(cls, key, kind):
    with pytest.raises(FlowError) as e:
        cls.from_dict(cls().to_dict() | {key: 1})
    assert (e.value.param, str(e.value)) == (key, f"{key} isn't a {kind} setting")


@pytest.mark.parametrize(
    ("s", "param", "message"), BAD, ids=[f"{p}-{i}" for i, (_, p, _) in enumerate(BAD)]
)
def test_check_rejects_bad_values(s, param, message):
    with pytest.raises(FlowError) as e:
        s.check()
    assert (e.value.param, str(e.value)) == (param, message)


def test_flow_error_renders_settings_as_flags():
    with pytest.raises(FlowError) as e:
        ClusterSettings(n_jobs=0).check()
    assert e.value.cli(cli_flag) == "--jobs is 0; it takes -1 (every core) or 1 or more"
    assert str(e.value) == "n_jobs is 0; it takes -1 (every core) or 1 or more"
    assert isinstance(e.value, ValueError)
    # user text is put in before raising, and its braces stay as typed
    typed = FlowError("{param} names {x}, which a.fcs doesn't have", "exclude_channels")
    assert typed.cli(cli_flag) == "--exclude-channels names {x}, which a.fcs doesn't have"
    assert str(FlowError("no file has cells kept")) == "no file has cells kept"
    flags = [cli_flag(n) for n in ("dn_num2", "tsne_seed", "tsne", "from_gates")]
    assert flags == ["--dn-num2", "--tsne-seed", "--no-tsne", "--from-gates"]


def test_every_setting_names_a_real_flag():
    """cli_flag of every setting is a datanuggets-flow flag, so an error the CLI shows names a
    flag that can be typed."""
    flags = pick._parser()._option_string_actions
    names = [f.name for cls in (GateSettings, ClusterSettings) for f in dataclasses.fields(cls)]
    assert [name for name in names if cli_flag(name) not in flags] == []


def test_gate_settings_spread_per_file_thresholds():
    s = GateSettings(t11=(22, 20, 18)).check(3)
    assert s.for_file(1) == {
        "n_row": 11,
        "n_col": 11,
        "t11": 20,
        "t21": 0.25,
        "t12": 20,
        "t22": 0.5,
        "area": flow.mirrored_area,
    }
    inspect.signature(flow.gate_peaks).bind(None, None, **s.for_file(2))  # gate_peaks takes them
    with pytest.raises(FlowError) as e:
        s.check(2)
    assert (e.value.param, str(e.value)) == (
        "t11",
        "t11 gives 3 values for 2 files; give one, or one per file",
    )
    with pytest.raises(FlowError) as e:
        GateSettings(t21=(0.25, 0.5)).check(3)
    assert str(e.value) == "t21 gives 2 values for 3 files; give one, or one per file"
    assert GateSettings(disc="peak").for_file(0)["area"] is flow.find_area


def test_his_is_read_as_reference():
    """The reference rule was called his. The old name, from the library or a gate folder's
    record, gives the same rule, and the settings write it under its new name."""
    for s in (GateSettings(disc="his"), GateSettings.from_dict({**GATE, "disc": "his"})):
        assert s.disc == "reference"
        assert s.check().for_file(0)["area"] is flow.mirrored_area
        assert s.to_dict()["disc"] == "reference"
