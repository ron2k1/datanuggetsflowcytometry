"""Contract 2.1, the colour rule. Each cluster's family and colour come from datanuggets.colors,
the package's own formula, so rebuilt fixtures follow it when it changes; this part only shapes
them into the payload's clusters list."""

from __future__ import annotations

from datanuggets.colors import cluster_colors


def clusters_block(k: int, parents: list[int]) -> list[dict]:
    """The payload's clusters: number and parent family (both from 1) and colour, for each of k."""
    colors = cluster_colors(k, parents)
    if len(set(colors)) != k:
        raise SystemExit(f"cluster_colors({k}) is not {k} distinct colours")
    return [{"cluster": c + 1, "parent": parents[c] + 1, "color": colors[c]} for c in range(k)]
