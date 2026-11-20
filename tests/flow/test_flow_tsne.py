"""The library's tsne_2d is the flow run's t-SNE of the nuggets, on real events (202.fcs's three
fluorescence channels)."""

from pathlib import Path

import numpy as np
import pytest
from datanuggets import create_dn
from datanuggets.projection import tsne_2d

from flowcases import read_202


@pytest.fixture(scope="module")
def nuggets():
    events, _, _ = read_202(Path("202.fcs"))
    x = np.arcsinh(events[:, 2:] / 6000.0)
    dn = create_dn(x, dn_num1=1000, dn_num2=120, seed=291102, n_jobs=1)
    use = dn.weights > 0
    return x, dn.centers[use], dn.weights[use].astype(float)


def test_tsne_2d_is_the_flow_runs_tsne(nuggets):
    pytest.importorskip("sklearn")
    from datanuggets_flow.pipeline import tsne_embedding
    from datanuggets_flow.settings import ClusterSettings

    _, centers, _ = nuggets
    got = tsne_2d(centers, perplexity=20.0, seed=3)
    assert got.shape == (len(centers), 2)
    settings = ClusterSettings(tsne_perplexity=20.0, tsne_seed=3)
    assert np.array_equal(got, tsne_embedding(centers, settings))
    assert np.array_equal(tsne_2d(centers[:10]), tsne_2d(centers[:10], perplexity=30.0, seed=0))
