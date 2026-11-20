"""The auto cofactor's rule, per channel, on NegativeTally: each channel's cells, its cells below
0 and a histogram of how far below 0 they are, in log-spaced bins at 400 a decade from 1e-2 to
1e8 with one bin below that range and one above it. A channel's spread is the median of |x| over
its cells below 0, read from the histogram, over 0.6745: the SD of a zero-centred Gaussian from
its negative half alone. Its cofactor is that spread, at least 150, when at least 1% of its cells
are below 0, and 150 otherwise. The median is checked here against numpy's exact one."""

import json

import numpy as np
import pytest

from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.pipeline import Cofactor, NegativeTally, auto_cofactor, resolve_cofactor

BIN = 10 ** (1 / 400) - 1  # one bin's width, as a share of the value at its lower edge: 0.58%
MAD_Z = 0.6745


def _tally(*blocks):
    tally = NegativeTally(np.shape(blocks[0])[1])
    for block in blocks:
        tally.add(block)
    return tally


def _no_tally():
    pytest.fail("tallied the cells")


def test_the_median_of_the_cells_below_0_is_numpys_within_a_bin():
    """Negatives of a Gaussian of SD 500, of one of SD 30, and of values spread over six
    decades: the spread is the exact median of |x| over 0.6745 to within one bin's width."""
    rng = np.random.default_rng(7)
    n = 200_000
    x = np.column_stack(
        (
            rng.normal(0, 500, n),
            np.where(rng.random(n) < 0.3, rng.normal(0, 30, n), rng.normal(8000, 900, n)),
            -np.exp(rng.normal(8, 3, n)),
        )
    )
    got = auto_cofactor(_tally(x))
    for j in range(x.shape[1]):
        below = -x[x[:, j] < 0, j]
        assert got.negative[j] == len(below) / n
        assert got.spread[j] == pytest.approx(np.median(below) / MAD_Z, rel=BIN)
    assert got.spread[0] == pytest.approx(500, rel=0.02)
    assert got.values == (got.spread[0], 150.0, got.spread[2])


def test_the_order_files_come_in_changes_nothing():
    rng = np.random.default_rng(11)
    files = [rng.normal(-50, 400, size=(n, 3)) for n in (1_000, 5_000, 777)]
    whole = _tally(np.vstack(files))
    for order in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
        tally = _tally(*(files[i] for i in order))
        np.testing.assert_array_equal(tally.counts, whole.counts)
        np.testing.assert_array_equal(tally.negative, whole.negative)
        np.testing.assert_array_equal(tally.cells, whole.cells)
        assert auto_cofactor(tally) == auto_cofactor(whole)
    assert whole.counts.dtype == np.int64 and whole.counts.shape == (3, 4_002)


def test_the_guard_takes_1_percent_of_the_cells_below_0():
    """99 of 10,000 cells below 0 is under 1%, so the channel keeps 150 however wide they are;
    100 of 10,000 is 1%, and the channel takes their spread."""
    x = np.full((10_000, 2), 1000.0)
    x[:99, 0] = -1000.0
    x[:100, 1] = -1000.0
    got = auto_cofactor(_tally(x))
    assert got.negative == (0.0099, 0.01)
    assert got.spread == pytest.approx((1000 / MAD_Z, 1000 / MAD_Z), rel=BIN)
    assert got.values == (150.0, got.spread[1])


def test_a_narrow_spread_takes_the_floor_and_no_cell_below_0_gives_no_spread():
    rng = np.random.default_rng(3)
    x = np.column_stack((rng.normal(0, 30, 50_000), rng.uniform(1, 9, 50_000)))
    got = auto_cofactor(_tally(x))
    assert got.spread[0] == pytest.approx(30, rel=0.03)
    assert got.negative[1] == 0.0 and got.spread[1] is None
    assert got.values == (150.0, 150.0)
    assert (got.value, got.source, got.range) == (150.0, "auto", None)
    empty = auto_cofactor(NegativeTally(2))  # no cells at all
    assert (empty.values, empty.negative, empty.spread) == ((150.0,) * 2, (0.0,) * 2, (None,) * 2)


def test_values_past_the_bins_are_taken_at_their_ends():
    """A median in the bin below 1e-2 reads as 1e-2, and one in the bin above 1e8 as 1e8, -inf
    included. -0.0 and NaN aren't below 0, but they are cells."""
    x = np.array(
        [
            [-1e-3, -1e9, -0.0],
            [-1e-5, -np.inf, np.nan],
            [5.0, 5.0, -2.0],
            [-1e-4, -1e12, 4.0],
        ]
    )
    tally = _tally(x)
    assert tally.cells.tolist() == [4, 4, 4]
    assert tally.negative.tolist() == [3, 3, 1]
    assert tally.counts[0, 0] == 3 and tally.counts[1, -1] == 3
    got = auto_cofactor(tally)
    assert got.spread[:2] == (1e-2 / MAD_Z, 1e8 / MAD_Z)
    assert got.values[:2] == (150.0, 1e8 / MAD_Z)


def test_the_tally_takes_cells_by_channels():
    tally = NegativeTally(3)
    for bad in (np.zeros(3), np.zeros((4, 2))):
        with pytest.raises(ValueError, match="3 channels"):
            tally.add(bad)
    tally.add(np.empty((0, 3)))
    assert tally.cells.tolist() == [0, 0, 0]


def test_resolve_tallies_only_for_auto():
    calls = []

    def tally():
        calls.append(1)
        return _tally(np.array([[-500.0, 1.0], [2.0, 3.0]]))

    assert resolve_cofactor(6000, tally) == Cofactor(6000.0, "set")
    assert resolve_cofactor(0.0, _no_tally) == Cofactor(0.0, "set")
    assert calls == []
    got = resolve_cofactor("auto", tally)
    assert calls == [1] and got == auto_cofactor(tally())
    assert resolve_cofactor("auto", tally()) == got  # a tally made already
    with pytest.raises(ValueError, match="tally"):
        resolve_cofactor("auto")
    with pytest.raises(FlowError) as caught:
        resolve_cofactor("Auto", _no_tally)
    assert caught.value.param == "cofactor"


def test_the_per_channel_record_is_plain_json():
    got = auto_cofactor(_tally(np.array([[-500.0, 1.0], [2.0, 3.0]])))
    record = got.transform()
    assert record == {
        "name": "arcsinh",
        "cofactor_from": "auto",
        "cofactors": [got.values[0], 150.0],
        "negative_fraction": [0.5, 0.0],
        "negative_sd": [got.spread[0], None],
        "floor": 150.0,
        "min_negative_fraction": 0.01,
    }
    assert json.loads(json.dumps(record)) == record
    assert got.applied == got.values and isinstance(got.applied, tuple)
    np.testing.assert_array_equal(got.per_channel(2), np.array(got.values))
    with pytest.raises(ValueError, match="2 channels"):
        got.per_channel(3)
