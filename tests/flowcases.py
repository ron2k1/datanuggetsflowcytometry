"""The recorded flow cases (tests/fixtures/flow, from benchmarks/flow/record.py), two
independent statements of the area rule, the gate check of spec criterion 3, and what the
datanuggets-flow tests share: 202's events as read_fcs gives them, the files a run writes, and the
digests its tables are pinned to."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull

FLOW = Path(__file__).parent / "fixtures" / "flow"
# the recorded files, named for their FCS files' numbers; 202_fluor.npz is the CLI test's
NAMES = tuple(sorted(p.stem for p in FLOW.glob("*.npz") if p.stem.isdigit()))
EDGE_TOL = 1e-9  # of the data's range: how near the hull's edge an event gated differently may be
T = ((22, 0.25), (20, 0.5))  # his t11, t21 for the first peak, t12, t22 for the rest


@dataclass(frozen=True)
class FlowCase:
    name: str
    fsc: np.ndarray
    ssc: np.ndarray
    z: np.ndarray
    gx: np.ndarray
    gy: np.ndarray
    zz: np.ndarray
    candidates: np.ndarray
    peaks: np.ndarray
    his_area: np.ndarray
    fixed_area: np.ndarray
    his_masks: np.ndarray
    fixed_masks: np.ndarray

    @staticmethod
    def cells(area: np.ndarray, k: int) -> np.ndarray:
        """Population k's cells (k from 0) in an area table of (row, col, population)."""
        return area[area[:, 2] == k + 1, :2]


@cache
def load_case(name: str) -> FlowCase:
    with np.load(FLOW / f"{name}.npz") as f:
        n = len(f["fsc"])

        def unpack(key: str) -> np.ndarray:
            return np.unpackbits(f[key], axis=0, count=n).astype(bool)

        def ints(key: str) -> np.ndarray:
            return f[key].astype(np.int64)

        return FlowCase(
            name=name,
            fsc=f["fsc"].astype(float),
            ssc=f["ssc"].astype(float),
            z=f["z"],
            gx=f["gx"],
            gy=f["gy"],
            zz=ints("zz"),
            candidates=ints("candidates"),
            peaks=ints("peaks"),
            his_area=ints("his_area"),
            fixed_area=ints("fixed_area"),
            his_masks=unpack("his_masks"),
            fixed_masks=unpack("fixed_masks"),
        )


def _area(x, keep) -> np.ndarray:
    a, b = np.indices(x.shape) + 1
    return np.column_stack((a.T[keep.T], b.T[keep.T]))  # column by column, as his come


def mirrored_area(x, idx, idy, t1, t2) -> np.ndarray:
    """What his find_area keeps, stated directly: each cell's own density, the distance disc
    centred on the mirrored peak (idy, idx). Cells as 1-based (row, col)."""
    a, b = np.indices(x.shape) + 1
    return _area(x, (np.hypot(a - idy, b - idx) < t1) & (x > t2 * x[idx - 1, idy - 1]))


def fixed_area(x, idx, idy, t1, t2) -> np.ndarray:
    """The corrected rule stated directly: the same with the disc on the peak."""
    a, b = np.indices(x.shape) + 1
    return _area(x, (np.hypot(a - idx, b - idy) < t1) & (x > t2 * x[idx - 1, idy - 1]))


def edge_distance(points: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Each row of q's distance to the boundary of the convex hull of points."""
    v = points[ConvexHull(points).vertices]
    d = np.roll(v, -1, axis=0) - v
    rel = q[:, None, :] - v[None]
    t = np.clip((rel * d[None]).sum(-1) / (d * d).sum(-1), 0.0, 1.0)
    return np.sqrt(((rel - t[..., None] * d[None]) ** 2).sum(-1)).min(axis=1)


def assert_gate_close(fsc, ssc, got, want, zz, cells) -> None:
    """Spec criterion 3: the masks are equal, or every event that differs lies within EDGE_TOL of
    the data's range from the edge of the hull of the events whose bin is in the cells' hull."""
    from datanuggets_flow.gate import bin_mask

    if np.array_equal(got, want):
        return
    raw = np.column_stack((fsc, ssc))
    diff = np.flatnonzero(got != want)
    span = max(np.ptp(fsc), np.ptp(ssc))
    far = edge_distance(raw[bin_mask(zz, cells)], raw[diff]).max()
    assert far <= EDGE_TOL * span, (
        f"{len(diff)} events differ, the farthest {far:.3g} from the edge"
    )


LABELS = ["CD8 (FJComp-Alexa Fluor 700-A)", "CD3 (FJComp-BV510-A)", "CD4 (FJComp-Spark Blue-A)"]
COLUMNS = {
    "selection.csv": ["file_number", "file", "populations", "events", "kept", "percent"],
    "nuggets_1.csv": ["nugget0", *LABELS, "weight", "scale", "cluster"],
    "events_1.csv": ["event0", "nugget0", "cluster"],
    "cluster_summary.csv": ["file_number", "file", "cluster", "cells", "percent"],
    "cluster_centers.csv": ["cluster", *LABELS],
}
# the figures a run writes with a t-SNE: weighted k-means, the default, has no tree to draw
FIGURES = (
    "gates.png",
    "local_maxima.png",
    "clusters_pca.png",
    "clusters_tsne.png",
    "cluster_centers.png",
)
TREE_FIGURES = (*FIGURES[:2], "dendrogram.png", *FIGURES[2:])
# the flags that run a case as every run did before weighted k-means became the default: the
# hierarchical tree on mean centers, the nuggets built on numpy's draws
TREE = ["--method", "tree", "--center-method", "mean", "--draws", "numpy"]
# the tables a clustering run writes for a viewer after its own (flow.outputs.viewer_tables),
# with a t-SNE and without groups
VIEWER = (
    "cluster_colors.csv",
    "cluster_markers.csv",
    "pca_scores.csv",
    "pca_loadings.csv",
    "pca_variance.csv",
    "pca_center.csv",
    "tsne.csv",
    "tsne3d.csv",
    "cells.csv",
)
# a run of two channels: its PCA start can't lift two channels to a 3-D t-SNE
VIEWER_2D = tuple(name for name in VIEWER if name != "tsne3d.csv")
# digest of each table, recorded from pick.py before its main() was cut into steps, so under
# TREE; test_the_tree_on_mean_centers_with_numpy_draws_keeps_the_old_digests holds them
TREE_DIGESTS = {
    "selection.csv": "23b2c99d62f2c8dd40ec9f70602aef5ac59c0d001dfe8225c6589a2f302c133e",
    "nuggets_1.csv": "be16c779e8e5c25073b342d48263283546c1351fbf1699490627e1e0f4d8d101",
    "events_1.csv": "0cbebf6054bf803a9a970ee44a811bba3f60bfc5742e6bb2fdbae70efbeea144",
    "cluster_summary.csv": "22649c5a60c1f6d03a9c38374ae777825a76f03b4fc1f5be7a658fe57aa9b514",
    "cluster_centers.csv": "ac066c8d5c4d64447cc4d72ca4ceb7372212cf095369616c02eae28680ddb242",
}
# digest of each table of the three-file run, recorded from pick.py before its main() was cut
# into steps, so under TREE
TREE_DIGESTS_3 = {
    "selection.csv": "0ef31e9c3c4252ed89080acc727502ac0f911580f0bbf297756fee03b164a627",
    "nuggets_1.csv": "128642490cf7274ee9176527b3face34f0339d9f7b3b55a0d93f1afb29459e95",
    "events_1.csv": "15dac77591ea8841683248b2e3d7647d84a6c9be66aaa11fb425e738ac833a5a",
    "nuggets_3.csv": "ee0609722e78ca1fc6b21220ab8f95071a49c4482cde2316686f078301e75d49",
    "events_3.csv": "ce82de3cef82518f7109ea757b7e74c780fb30707e54806fc17e86dccd4065d4",
    "cluster_summary.csv": "ab1c6f6bd1d16b522fbe43373a1dacbc276c48596f65adb0579266bca1e257eb",
    "cluster_centers.csv": "38f71313c81cee4ea83da8029c8626655948c7d78bb2f717f631c27404c90589",
}
# digest of each table of the run on 202's Pop 1 with every gate and clustering flag left out
# (but --dn-num2 50 and --k 3), so scaled and with the auto cofactor picked per channel from its
# cells, CD8's 506 and 150 for CD3 and CD4; recorded when auto went per channel, under TREE
TREE_DIGESTS_AUTO = {
    "selection.csv": "23b2c99d62f2c8dd40ec9f70602aef5ac59c0d001dfe8225c6589a2f302c133e",
    "nuggets_1.csv": "5cfa967aa47750d9e5e3752d1ee50ef56d97f14bc31b50dd09dd310acbd416fe",
    "events_1.csv": "1ef9fec2478c3a0d096e1dda23ae57910d3ae02c5abce3a2f1ca05816c09b1e5",
    "cluster_summary.csv": "d89fdc9900a9a9023f1f2c866ebcb27bcb67777437b360a150f19bfb80b97223",
    "cluster_centers.csv": "967a3695d8baf6c784e61ccddbfa6cd63a1cc12ca1b9b27fd9c48d60b0b38135",
}
# the same three cases run with the defaults: each file's nuggets on original centers from R's
# set.seed draws, then weighted k-means of the pooled Weight > 0 nuggets. Recorded when they
# became the defaults, once R's create.DN and Wkmeans on the inputs each run gave create_dn gave
# the same nuggets, assignments and clusters, bit for bit. selection.csv is the gate's, so it
# keeps its TREE digest.
DIGESTS = {
    "selection.csv": TREE_DIGESTS["selection.csv"],
    "nuggets_1.csv": "fafccc86768f806d790917e4d84e68d8d205ace63a7b9df986ae006a212ad0e5",
    "events_1.csv": "77f0e68876bef22471a88571f0668e8d95fd8d47751e20ac02068e778278d6b7",
    "cluster_summary.csv": "01008c2f9ced2fd35720fbde650ea0eaf2dfa926f8725370739c44f36fd8073c",
    "cluster_centers.csv": "d6eedc97b01f1ccc744de9e9eb8c65e346167c3fd875ba6141ba35d7e504c4a6",
}
DIGESTS_3 = {
    "selection.csv": TREE_DIGESTS_3["selection.csv"],
    "nuggets_1.csv": "746527f643b2ca56955a4f97e6e814b5b1faed1e7dc4d33169400b285f771fc4",
    "events_1.csv": "3dcba76ecd2f31ed31369115f837ebec00043fafbd798ce5e42e73c573c683eb",
    "nuggets_3.csv": "8c6b223b3398c9b85fd4ba50fe5ea2bc5c1323f7e96dfac02ac854004da20923",
    "events_3.csv": "b2941d436b11af0852292ecae94bd856dddd7ef229cf3d3fad778cf3f3d0303e",
    "cluster_summary.csv": "7fc4c88451d698ee06e90e0eb4cf362a7e5457302e38d8759909e1edd9480fc0",
    "cluster_centers.csv": "d24c255735e53cefaa48c7e77b870b7a746fc7824b9b1905ca3f1477efa72dba",
}
DIGESTS_AUTO = {
    "selection.csv": TREE_DIGESTS_AUTO["selection.csv"],
    "nuggets_1.csv": "be2bc7e1337ab9416d55353ddd0501d48bde0982bf110f33ce8f1401999e7163",
    "events_1.csv": "4d17a030b2a7f73e4b6503d4a13ec41fc3278189ba7c354d342f6474a88bee14",
    "cluster_summary.csv": "f3fc68da07650caae31152c45a05d412a00a14c1eaaf4e838b53d533ce84dca2",
    "cluster_centers.csv": "f010651efc3dd03f7cb379cbdd090b76f68b255c8d10438ff43119a4f67f7e54",
}
DIGITS = 7  # significant digits of a number that isn't whole, in digest


def read_202(path):
    """202.fcs as read_fcs returns it, cut to FSC-A, SSC-A and three fluorescence channels."""
    with np.load(FLOW / "202.npz") as g, np.load(FLOW / "202_fluor.npz") as f:
        events = np.column_stack((g["fsc"], g["ssc"], f["fluor"])).astype(float)
        return events, ["FSC-A", "SSC-A", *f["pnn"].tolist()], ["", "", *f["pns"].tolist()]


def _cell(text: str) -> str:
    try:
        int(text)
        return text
    except ValueError:
        pass
    try:
        return format(float(text), f".{DIGITS}g")
    except ValueError:
        return text


def digest(path) -> str:
    """SHA-256 of a CSV with \n line ends and each number that isn't whole to DIGITS significant
    digits. pandas ends a line with os.linesep, and np.arcsinh's last bit differs between
    platforms, which moves a nugget's scale by up to about 1e-12 of itself."""
    with open(path, newline="") as f:
        rows = [[_cell(c) for c in row] for row in csv.reader(f)]
    text = io.StringIO()
    csv.writer(text, lineterminator="\n").writerows(rows)
    return hashlib.sha256(text.getvalue().encode()).hexdigest()
