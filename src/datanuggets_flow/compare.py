"""What a datanuggets-flow run compares across its files: each kept file's mean marker levels in
each cluster (cluster_markers.csv), and, when the files are put in groups, each group's cluster
percents (group_summary.csv) and marker means (group_markers.csv) against a reference group, the
group of the lowest-numbered kept file. The comparison is descriptive: means, spreads and
differences, with no test of whether a difference is real. pandas loads only when a table is
made."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

import numpy as np

from datanuggets_flow._defaults import FLOW_LOG2FC_CELLS

if TYPE_CHECKING:
    import pandas as pd

    from datanuggets_flow._pipeline.records import Kept, Pool


def cluster_markers(kept: Sequence[Kept], pool: Pool, labels: Sequence[str]) -> pd.DataFrame:
    """cluster_markers.csv: for every kept file and cluster 1..k, its cells in the cluster and the
    mean of each channel over them, in the Transform stage's units (arcsinh, or as stored), as
    the weight-weighted mean of the file's nugget cell means in the cluster, taken back from the
    Scale stage's units when it ran. A nugget's weight is its cells' count, so this is the cells'
    own mean, rounding aside, whatever the nugget centers are. Means are NaN (an empty CSV cell)
    where the file has no cells in the cluster."""
    import pandas as pd

    labels = list(labels)
    rows, start = [], 0
    cell_means = pool.cell_means()
    for kp in kept:
        n = kp.dn.n_nuggets
        part, weights = pool.cl[start : start + n], pool.weights[start : start + n]
        centers = cell_means[start : start + n]
        start += n
        cells = np.bincount(part[kp.dn.assignments], minlength=pool.k)
        for c in range(pool.k):
            row = {"file_number": kp.number, "file": kp.name, "cluster": c + 1}
            row["cells"] = int(cells[c])
            at = (part == c) & (weights > 0)
            if cells[c] > 0:
                w = weights[at]
                means = pool.values((w[:, None] * centers[at]).sum(axis=0) / w.sum())
            else:
                means = np.full(len(labels), np.nan)
            rows.append(row | dict(zip(labels, means.tolist())))
    return pd.DataFrame(rows, columns=["file_number", "file", "cluster", "cells", *labels])


def _groups_of(files: Sequence[int], groups: Mapping[int, str]) -> tuple[list[str], str]:
    """Every group in groups, in first appearance by file number, and the reference group: the
    group of the first of files, the kept files. A kept file without a group is refused."""
    missing = [f for f in files if f not in groups]
    if missing:
        raise ValueError(f"groups gives no group for file {missing[0]}")
    if not files:
        raise ValueError("there are no kept files to compare")
    order = list(dict.fromkeys(groups[f] for f in sorted(groups)))
    return order, groups[min(files)]


def _pseudocount(summary: pd.DataFrame) -> float:
    """The pseudocount, in percentage points, of group_summary's log2 fold change: a file's
    percents count FLOW_LOG2FC_CELLS (half a cell) as 100 * FLOW_LOG2FC_CELLS / N_f points, N_f
    its kept cells (its cells summed over the clusters, the count its percents are shares of), and
    the pseudocount is the mean of that over the kept files in cluster_summary.csv's table."""
    cells = summary.groupby("file_number")["cells"].sum().to_numpy(dtype=float)
    return float(np.mean(100 * FLOW_LOG2FC_CELLS / cells))


def group_summary(summary: pd.DataFrame, groups: Mapping[int, str]) -> pd.DataFrame:
    """group_summary.csv from cluster_summary.csv's table and each file's group (by file
    number): for each group, in first-appearance order, and cluster, the kept files in the group
    (samples) and the mean, sd (ddof 1; NaN under 2 samples), min and max of their percents, the
    reference group's mean, and the difference and log2 fold change from it, log2((mean + pc) /
    (reference + pc)) with pc = _pseudocount(summary), the same on every row and written in
    log2fc_pseudocount. The reference group is the group of the lowest-numbered kept file; its
    own difference and fold change are 0. A group with no kept file has NaNs. Descriptive: no
    test of a difference is made."""
    import pandas as pd

    files = sorted(int(f) for f in summary["file_number"].unique())
    order, ref = _groups_of(files, groups)
    pc = _pseudocount(summary)
    clusters = sorted(int(c) for c in summary["cluster"].unique())
    percent = summary.pivot(index="file_number", columns="cluster", values="percent")
    stats = {}
    for g in order:
        members = [f for f in files if groups[f] == g]
        for c in clusters:
            v = percent.loc[members, c].to_numpy(dtype=float) if members else np.empty(0)
            n = len(v)
            stats[g, c] = (
                n,
                float(v.mean()) if n else math.nan,
                float(v.std(ddof=1)) if n > 1 else math.nan,
                float(v.min()) if n else math.nan,
                float(v.max()) if n else math.nan,
            )
    rows = []
    for g in order:
        for c in clusters:
            n, mean, sd, lo, hi = stats[g, c]
            reference = stats[ref, c][1]
            if g == ref:
                diff = log2fc = 0.0
            else:
                diff = mean - reference
                log2fc = math.log2((mean + pc) / (reference + pc)) if n else math.nan
            rows.append(
                {
                    "group": g,
                    "cluster": c,
                    "samples": n,
                    "mean_percent": mean,
                    "sd_percent": sd,
                    "min_percent": lo,
                    "max_percent": hi,
                    "reference": reference,
                    "diff_vs_ref": diff,
                    "log2fc_vs_ref": log2fc,
                    "log2fc_pseudocount": pc,
                }
            )
    return pd.DataFrame(rows)


def group_markers(
    markers: pd.DataFrame,
    groups: Mapping[int, str],
    channels: Sequence[str],
    labels: Sequence[str],
) -> pd.DataFrame:
    """group_markers.csv from cluster_markers.csv's table and each file's group (by file number):
    for each group, in first-appearance order, cluster and channel, the files in the group with
    cells in the cluster (samples), the unweighted mean of their means, the reference group's mean
    and the difference from it. mean is NaN with no samples, and the difference NaN when either
    side is; the reference group's own difference is 0 where it has a mean."""
    import pandas as pd

    labels = list(labels)
    files = sorted(int(f) for f in markers["file_number"].unique())
    order, ref = _groups_of(files, groups)
    clusters = sorted(int(c) for c in markers["cluster"].unique())
    present = markers[markers["cells"] > 0]
    means = {}
    for g in order:
        members = [f for f in files if groups[f] == g]
        mine = present[present["file_number"].isin(members)]
        for c in clusters:
            block = mine[mine["cluster"] == c]
            n = len(block)
            for label in labels:
                v = block[label].to_numpy(dtype=float)
                means[g, c, label] = (n, float(v.sum() / n) if n else math.nan)
    rows = []
    for g in order:
        for c in clusters:
            for channel, label in zip(channels, labels):
                n, mean = means[g, c, label]
                reference = means[ref, c, label][1]
                if math.isnan(mean) or math.isnan(reference):
                    diff = math.nan
                else:
                    diff = 0.0 if g == ref else mean - reference
                rows.append(
                    {
                        "group": g,
                        "cluster": c,
                        "channel": channel,
                        "label": label,
                        "samples": n,
                        "mean": mean,
                        "reference": reference,
                        "diff_vs_ref": diff,
                    }
                )
    return pd.DataFrame(rows)
