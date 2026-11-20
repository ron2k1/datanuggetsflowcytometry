"""Pins of what the flow copies from the library instead of importing it, each checked against the
library's public behaviour, so a library release that moves one fails here:

- SEED and DN_NUM1 against create_dn's defaults, TSNE_PERPLEXITY and TSNE_SEED against tsne_2d's;
- CENTER_METHODS against the center methods create_dn takes and the ones it refuses;
- SEED_MAX against the largest seed RDraws takes;
- figures.py's _palette and _label_colors against the colours plot.clusters draws.

Only public library names are used. The events are 202.fcs's three fluorescence channels."""

import inspect
from pathlib import Path

import numpy as np
import pytest
from datanuggets import DataNuggetWarning, RDraws, create_dn, plot
from datanuggets.projection import tsne_2d
from matplotlib.colors import to_rgba_array
from matplotlib.figure import Figure

from datanuggets_flow import _defaults
from datanuggets_flow.figures import _label_colors, _palette
from flowcases import read_202


@pytest.fixture(scope="module")
def x():
    events, _, _ = read_202(Path("202.fcs"))
    return np.arcsinh(events[:2000, 2:] / 6000.0)


def _small_dn(x, **kwargs):
    return create_dn(x, r=100, dn_num1=200, dn_num2=50, seed=_defaults.SEED, n_jobs=1, **kwargs)


def test_seed_and_dn_num1_are_create_dns_defaults():
    params = inspect.signature(create_dn).parameters
    assert params["seed"].default == _defaults.SEED
    assert params["dn_num1"].default == _defaults.DN_NUM1


def test_tsne_perplexity_and_seed_are_tsne_2ds_defaults():
    params = inspect.signature(tsne_2d).parameters
    assert params["perplexity"].default == _defaults.TSNE_PERPLEXITY
    assert params["seed"].default == _defaults.TSNE_SEED


@pytest.mark.parametrize("method", _defaults.CENTER_METHODS)
def test_create_dn_takes_each_center_method(x, method):
    dn = _small_dn(x, center_method=method)
    assert dn.centers.shape[1] == x.shape[1]


def test_create_dn_refuses_any_other_center_method_and_lists_the_same_ones(x):
    with pytest.raises(ValueError) as e:
        _small_dn(x, center_method="median")
    choices = ", ".join(map(repr, _defaults.CENTER_METHODS))
    assert str(e.value) == f"center_method must be one of {choices}, got 'median'"


def test_seed_max_is_the_largest_seed_rdraws_takes():
    RDraws(_defaults.SEED_MAX)
    with (
        pytest.warns(DataNuggetWarning),
        pytest.raises(ValueError, match="supplied seed is not a valid integer"),
    ):
        RDraws(_defaults.SEED_MAX + 1)


def _three_clusters(x):
    return x[:30, :2], np.arange(30) % 3


@pytest.mark.parametrize("colors", [None, ["#e41a1c", "#377eb8"], ("tab:green", "k", "0.5")])
def test_the_figures_palette_gives_the_colours_plot_clusters_draws(x, colors):
    points, labels = _three_clusters(x)
    ax = Figure().subplots()
    plot.clusters(points, labels, colors=colors, ax=ax)
    (drawn,) = [c for c in ax.collections if c.get_gid() == "points"]
    want = to_rgba_array(_label_colors(labels, _palette(colors)))
    assert np.array_equal(drawn.get_facecolors(), want)


@pytest.mark.parametrize("colors", ["red", [], ["red", "not a colour"]])
def test_the_figures_palette_refuses_what_plot_clusters_refuses(x, colors):
    points, labels = _three_clusters(x)
    with pytest.raises((TypeError, ValueError)) as theirs:
        plot.clusters(points, labels, colors=colors, ax=Figure().subplots())
    with pytest.raises(type(theirs.value)) as mine:
        _palette(colors)
    assert str(mine.value) == str(theirs.value)
