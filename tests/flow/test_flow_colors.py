"""The 202 halves of the library's cluster colour tests and the colours plot.gates draws each
population in: on the pooled nuggets of 202.fcs's real events at k = 100, siblings and clusters stay
apart and every colour reads on a light and a dark background.

Distances are CIEDE2000, computed here independently of both packages and checked against the
published test data of Sharma, Wu and Dalal."""

import math
from pathlib import Path

import numpy as np
import pytest
from datanuggets import create_dn, whclust
from datanuggets.colors import TAB10, cluster_colors, tree_parents

from datanuggets_flow.colors import population_colors
from flowcases import read_202

# the app's plot backgrounds, light and dark (app/web/shared/styles/tokens.css --plot-bg)
BACKGROUNDS = ("#ffffff", "#111318")
MIN_CONTRAST = 2.5  # WCAG contrast ratio every colour keeps against both; tab10's orange is 2.53
SIBLING_DE00 = 5.0  # the least CIEDE2000 between two clusters of one family at k = 100
ANY_DE00 = 3.0  # and between any two clusters

# Sharma, G., Wu, W. and Dalal, E. N. (2005). The CIEDE2000 color-difference formula:
# implementation notes, supplementary test data, and mathematical observations. Color Research
# & Application 30(1), 21-30, Table 1: L1 a1 b1, L2 a2 b2 and their CIEDE2000, as published in
# ciede2000testdata.txt on the authors' page (www.ece.rochester.edu/~gsharma/ciede2000/).
SHARMA = (
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -1.1848, -84.8006, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, -0.9009, -85.5211, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, -1.0000, 2.0000, 50.0000, 0.0000, 0.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0010, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0012, 7.2195),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0009, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0010, -2.4900, 4.8045),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0011, -2.4900, 4.7461),
    (50.0000, 2.5000, 0.0000, 50.0000, 0.0000, -2.5000, 4.3065),
    (50.0000, 2.5000, 0.0000, 73.0000, 25.0000, -18.0000, 27.1492),
    (50.0000, 2.5000, 0.0000, 61.0000, -5.0000, 29.0000, 22.8977),
    (50.0000, 2.5000, 0.0000, 56.0000, -27.0000, -3.0000, 31.9030),
    (50.0000, 2.5000, 0.0000, 58.0000, 24.0000, 15.0000, 19.4535),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.1736, 0.5854, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2972, 0.0000, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 1.8634, 0.5757, 1.0000),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2592, 0.3350, 1.0000),
    (60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
    (63.0109, -31.0961, -5.8663, 62.8187, -29.7946, -4.0864, 1.2630),
    (61.2901, 3.7196, -5.3901, 61.4292, 2.2480, -4.9620, 1.8731),
    (35.0831, -44.1164, 3.7933, 35.0232, -40.0716, 1.5901, 1.8645),
    (22.7233, 20.0904, -46.6940, 23.0331, 14.9730, -42.5619, 2.0373),
    (36.4612, 47.8580, 18.3852, 36.2715, 50.5065, 21.2231, 1.4146),
    (90.8027, -2.0831, 1.4410, 91.1528, -1.6435, 0.0447, 1.4441),
    (90.9257, -0.5406, -0.9208, 88.6381, -0.8985, -0.7239, 1.5381),
    (6.7747, -0.2908, -2.4247, 5.8714, -0.0985, -2.2286, 0.6377),
    (2.0776, 0.0795, -1.1350, 0.9033, -0.0636, -0.5514, 0.9082),
)


def _de00(lab1, lab2) -> float:
    """CIEDE2000 of two CIELAB colours, kL = kC = kH = 1, as Sharma, Wu and Dalal state it."""
    (l1, a1, b1), (l2, a2, b2) = lab1, lab2
    c_ab = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(c_ab**7 / (c_ab**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    d_l, d_c = l2 - l1, c2p - c1p
    d_h = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    l_bar, c_bar = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        h_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        h_bar = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        h_bar = (h1p + h2p + 360) / 2
    else:
        h_bar = (h1p + h2p - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(h_bar - 30))
        + 0.24 * math.cos(math.radians(2 * h_bar))
        + 0.32 * math.cos(math.radians(3 * h_bar + 6))
        - 0.20 * math.cos(math.radians(4 * h_bar - 63))
    )
    d_theta = 30 * math.exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * math.sqrt(c_bar**7 / (c_bar**7 + 25**7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / math.sqrt(20 + (l_bar - 50) ** 2)
    s_c = 1 + 0.045 * c_bar
    s_h = 1 + 0.015 * c_bar * t
    r_t = -math.sin(math.radians(2 * d_theta)) * r_c
    return math.sqrt(
        (d_l / s_l) ** 2 + (d_c / s_c) ** 2 + (d_h / s_h) ** 2 + r_t * (d_c / s_c) * (d_h / s_h)
    )


def _linear(color: str) -> list[float]:
    """An sRGB hex colour's channels, linear light (IEC 61966-2-1)."""
    out = []
    for i in (1, 3, 5):
        v = int(color[i : i + 2], 16) / 255
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return out


def _lab(color: str) -> tuple[float, float, float]:
    """CIELAB (D65) of an sRGB hex colour."""
    r, g, b = _linear(color)
    xyz = (
        (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047,
        0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
        (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883,
    )
    f = [v ** (1 / 3) if v > (6 / 29) ** 3 else v / (3 * (6 / 29) ** 2) + 4 / 29 for v in xyz]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def _contrast(color: str, background: str) -> float:
    """The WCAG 2 contrast ratio of two sRGB hex colours."""
    y1, y2 = (
        sum(w * v for w, v in zip((0.2126, 0.7152, 0.0722), _linear(c)))
        for c in (color, background)
    )
    return (max(y1, y2) + 0.05) / (min(y1, y2) + 0.05)


def _closest(colors, parents) -> tuple[float, float]:
    """The least CIEDE2000 between two of colors, and between two that share a parent."""
    labs = [_lab(c) for c in colors]
    least = sibling = math.inf
    for i in range(len(labs)):
        for j in range(i + 1, len(labs)):
            d = _de00(labs[i], labs[j])
            least = min(least, d)
            if parents[i] == parents[j]:
                sibling = min(sibling, d)
    return least, sibling


@pytest.fixture(scope="module")
def tree():
    """Whclust of the nuggets of 202.fcs's real events, its three fluorescence channels as the
    flow run clusters them, with enough nuggets in use to cut 250 clusters."""
    events, _, _ = read_202(Path("202.fcs"))
    x = np.arcsinh(events[:, 2:] / 6000.0)
    dn = create_dn(x, dn_num1=2000, dn_num2=400, seed=291102, n_jobs=1)
    use = dn.weights > 0
    assert use.sum() >= 250
    return whclust(dn.centers[use], dn.weights[use].astype(float))


def test_ciede2000_reproduces_the_published_test_data():
    for row in SHARMA:
        one, two, want = row[:3], row[3:6], row[6]
        assert round(_de00(one, two), 4) == want
        assert round(_de00(two, one), 4) == want


def _stay_apart(name, parents, colors):
    """No two clusters of one family closer than SIBLING_DE00 and no two clusters at all closer
    than ANY_DE00 (CIEDE2000)."""
    least, sibling = _closest(colors, parents)
    assert sibling >= SIBLING_DE00, f"{name}: closest siblings {sibling:.2f}"
    assert least >= ANY_DE00, f"{name}: closest clusters {least:.2f}"


def _read_on_both_backgrounds(name, colors):
    for background in BACKGROUNDS:
        worst = min(colors, key=lambda c: _contrast(c, background))
        ratio = _contrast(worst, background)
        assert ratio >= MIN_CONTRAST, f"{name}: {worst} on {background} is {ratio:.2f}:1"


def test_at_100_clusters_the_202_trees_clusters_stay_apart(tree):
    parents = tree_parents(tree, 100)
    _stay_apart("202", parents, cluster_colors(100, parents))


def test_every_202_colour_reads_on_the_light_and_the_dark_background(tree):
    _read_on_both_backgrounds("202 k=100", cluster_colors(100, tree_parents(tree, 100)))


def test_population_colors_cycle_over_the_populations_drawn():
    assert population_colors([5, 0, 3]) == [TAB10[0], None, TAB10[1]]
    got = population_colors([1] * 12)
    assert got[:10] == list(TAB10) and got[10:] == list(TAB10[:2])
    assert population_colors([]) == []
