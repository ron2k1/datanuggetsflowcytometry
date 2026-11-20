"""The tables a datanuggets-flow run writes for a viewer, after the run's own tables and before
its figures: each cluster's colour, the cluster markers, the weighted PCA the clusters figure
draws, the t-SNE, a sample of each file's cells placed in that PCA, and the group comparison.
pandas loads when they are made."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, NamedTuple

import numpy as np
from datanuggets.colors import block_parents, cluster_colors, tree_parents
from datanuggets.projection import PcaView, pca_view, project

from datanuggets_flow._defaults import PCA_VIEW_COMPONENTS
from datanuggets_flow.compare import cluster_markers, group_markers, group_summary

if TYPE_CHECKING:
    import pandas as pd

    from datanuggets_flow._pipeline.records import Kept, Pool
    from datanuggets_flow.settings import ClusterSettings


class CellSample(NamedTuple):
    """Some of a kept file's cells for cells.csv: their places in Kept.rows, sorted, and their
    channels in the Transform stage's units, before the Scale stage."""

    at: np.ndarray
    values: np.ndarray


def sample_cells(x: np.ndarray, number: int, settings: ClusterSettings) -> CellSample | None:
    """min(settings.cells_per_file, len(x)) of a file's kept cells x, drawn uniformly without
    replacement by default_rng([settings.seed, number]) and sorted; None for cells_per_file 0."""
    if not settings.cells_per_file:
        return None
    m = min(settings.cells_per_file, len(x))
    rng = np.random.default_rng([settings.seed, number])
    at = np.sort(rng.choice(len(x), size=m, replace=False))
    return CellSample(at, x[at])


def pool_parents(pool: Pool) -> list[int]:
    """Each of the pool's k clusters' colour family: the cluster of the same tree cut into
    colors.PARENT_K that it falls in, or, for weighted k-means, which has no tree, its block of
    neighbouring cluster numbers (colors.block_parents)."""
    if pool.tree is None:
        return block_parents(pool.k)
    return tree_parents(pool.tree, pool.k)


def pool_colors(pool: Pool) -> list[str]:
    """Each of the pool's k clusters' colour, its family from pool_parents."""
    return cluster_colors(pool.k, pool_parents(pool))


def pool_view(pool: Pool) -> PcaView:
    """The weighted PCA of the nuggets in use that clusters_pca.png draws, its signs fixed: of
    the nuggets as they were clustered, on the Scale stage's scale when it ran."""
    use = pool.use
    return pca_view(pool.centers[use], pool.weights[use], fix_signs=True)


def _pooled(kept: Sequence[Kept]) -> tuple[np.ndarray, np.ndarray]:
    """Each pooled nugget's file number and its row in that file's nuggets_N.csv."""
    files = np.concatenate([np.full(kp.dn.n_nuggets, kp.number) for kp in kept])
    rows = np.concatenate([np.arange(kp.dn.n_nuggets) for kp in kept])
    return files, rows


def _components(q: int) -> list[str]:
    return [f"PC{i + 1}" for i in range(q)]


def pca_tables(
    view: PcaView, kept: Sequence[Kept], pool: Pool, channels: Sequence[str], labels: Sequence[str]
) -> dict[str, pd.DataFrame]:
    """pca_scores.csv, pca_loadings.csv, pca_variance.csv and pca_center.csv of view.
    pca_center.csv's center is in the Transform stage's units; with the Scale stage it gains
    scale, each channel's pooled SD, so a row x in those units scores ((x - center) / scale) @
    rotation, as R's prcomp center and scale do."""
    import pandas as pd

    files, rows = _pooled(kept)
    pcs = _components(view.rotation.shape[1])
    scores = pd.DataFrame(view.scores, columns=pcs)
    scores.insert(0, "nugget0", rows[pool.use])
    scores.insert(0, "file_number", files[pool.use])
    loadings = pd.DataFrame(view.rotation, columns=pcs)
    loadings.insert(0, "label", list(labels))
    loadings.insert(0, "channel", list(channels))
    variance = pd.DataFrame(
        {"component": pcs, "sdev": view.sdev, "variance_ratio": view.variance_ratio}
    )
    center = pd.DataFrame(
        {"channel": list(channels), "label": list(labels), "center": pool.values(view.center)}
    )
    if pool.scaling is not None:
        center["scale"] = pool.scaling.sd
    return {
        "pca_scores.csv": scores,
        "pca_loadings.csv": loadings,
        "pca_variance.csv": variance,
        "pca_center.csv": center,
    }


def cells_table(
    kept: Sequence[Kept],
    pool: Pool,
    cells: Mapping[int, CellSample],
    view: PcaView,
    labels: Sequence[str],
) -> pd.DataFrame:
    """cells.csv: each kept file's sampled cells, by file then event0, with the nugget and
    cluster each joined, their place on the view's first min(PCA_VIEW_COMPONENTS, q) components,
    found from their values scaled by the pool's Scale stage as the nuggets were, and their
    channels in the Transform stage's units."""
    import pandas as pd

    m = min(PCA_VIEW_COMPONENTS, view.rotation.shape[1])
    pcs, labels = _components(m), list(labels)
    parts, start = [], 0
    for kp in kept:
        part = pool.cl[start : start + kp.dn.n_nuggets]
        start += kp.dn.n_nuggets
        sample = cells.get(kp.number)
        if sample is None:
            continue
        nugget0 = kp.dn.assignments[sample.at]
        frame = pd.DataFrame(
            {
                "file_number": kp.number,
                "event0": kp.rows[sample.at],
                "nugget0": nugget0,
                "cluster": part[nugget0] + 1,
            }
        )
        placed = sample.values if pool.scaling is None else pool.scaling.apply(sample.values)
        frame[pcs] = project(placed, view, m)
        frame[labels] = sample.values
        parts.append(frame)
    columns = ["file_number", "event0", "nugget0", "cluster", *pcs, *labels]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns)


def groups_table(
    samples: Sequence[Mapping], kept: Sequence[Kept], groups: Sequence[str]
) -> pd.DataFrame:
    """groups.csv: every gated file's number, name, group, and whether it was clustered."""
    import pandas as pd

    clustered = {kp.number for kp in kept}
    return pd.DataFrame(
        {
            "file_number": range(1, len(samples) + 1),
            "file": [s["path"].name for s in samples],
            "group": list(groups),
            "kept": ["true" if i + 1 in clustered else "false" for i in range(len(samples))],
        }
    )


def viewer_tables(
    samples: Sequence[Mapping],
    kept: Sequence[Kept],
    pool: Pool,
    summary: pd.DataFrame,
    channels: Sequence[str],
    labels: Sequence[str],
    settings: ClusterSettings,
    tsne_xy: np.ndarray | None,
    cells: Mapping[int, CellSample],
    *,
    tsne_xyz: np.ndarray | None = None,
) -> dict[str, pd.DataFrame]:
    """The tables by file name, in the order a run writes them: cluster_colors.csv,
    cluster_markers.csv, the four pca_*.csv, tsne.csv and tsne3d.csv (with a 2-D and a 3-D
    t-SNE), cells.csv (unless cells_per_file is 0), and with groups, groups.csv,
    group_summary.csv and group_markers.csv. summary is cluster_summary.csv's table."""
    import pandas as pd

    parents = pool_parents(pool)
    tables = {
        "cluster_colors.csv": pd.DataFrame(
            {
                "cluster": np.arange(1, pool.k + 1),
                "parent": np.asarray(parents) + 1,
                "color": cluster_colors(pool.k, parents),
            }
        )
    }
    markers = cluster_markers(kept, pool, labels)
    tables["cluster_markers.csv"] = markers
    view = pool_view(pool)
    tables |= pca_tables(view, kept, pool, channels, labels)
    files, rows = _pooled(kept)
    for name, fit in (("tsne.csv", tsne_xy), ("tsne3d.csv", tsne_xyz)):
        if fit is not None:
            table = {"file_number": files[pool.use], "nugget0": rows[pool.use]}
            for i in range(fit.shape[1]):
                table[f"tsne{i + 1}"] = np.asarray(fit[:, i], dtype=float)
            tables[name] = pd.DataFrame(table)
    if settings.cells_per_file:
        tables["cells.csv"] = cells_table(kept, pool, cells, view, labels)
    if settings.groups is not None:
        by_file = dict(enumerate(settings.groups, start=1))
        tables["groups.csv"] = groups_table(samples, kept, settings.groups)
        tables["group_summary.csv"] = group_summary(summary, by_file)
        tables["group_markers.csv"] = group_markers(markers, by_file, channels, labels)
    return tables
