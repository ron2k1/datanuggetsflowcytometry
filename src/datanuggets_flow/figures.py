"""The datanuggets-flow figures, each drawn on a figure from figure(figsize=...). The default,
matplotlib's Figure, is held by no pyplot window, so a backend can draw run after run and leave
nothing open; the CLI passes plt.figure, so its figures show. They return the figures unsaved, and
save_figures writes them. Importing this module imports matplotlib."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from datanuggets import plot, wpca
from matplotlib.colors import to_rgba_array
from matplotlib.figure import Figure
from matplotlib.image import imread
from matplotlib.lines import Line2D

from datanuggets_flow import plot as flow_plot
from datanuggets_flow._defaults import FLOW_LEGEND_ROWS


# _palette and _label_colors are the library's plot/points.py helpers word for word, which keeps
# them private: the colours plot.clusters draws, so the t-SNE legend matches its points.
# tests/flow/test_flow_library_pins.py checks them against plot.clusters.
def _palette(colors) -> list:
    """The colors labels index into, the color cycle by default. Checks every one before a view
    draws, so a bad one can't leave a half-drawn plot."""
    if colors is None:
        return plt.rcParams["axes.prop_cycle"].by_key()["color"]
    if isinstance(colors, str):
        raise TypeError("colors must be a sequence of colors, not one string")
    palette = list(colors)
    if not palette:
        raise ValueError("colors must hold at least one color")
    try:
        to_rgba_array(palette)
    except (TypeError, ValueError) as e:
        raise ValueError(f"colors must all be matplotlib colors: {e}") from e
    return palette


def _label_colors(labels, palette) -> list:
    return [palette[int(v) % len(palette)] for v in labels]


def _panels(n: int, size: tuple[float, float], figure) -> tuple[Figure, np.ndarray]:
    """A figure of n panels of size inches, two across, and its axes in reading order, those past
    the n-th hidden."""
    cols = min(n, 2)
    rows = -(-n // cols)
    fig = (figure or Figure)(figsize=(size[0] * cols, size[1] * rows))
    axs = fig.subplots(rows, cols, squeeze=False).ravel()
    for ax in axs[n:]:
        ax.set_visible(False)
    return fig, axs


def local_maxima_figure(
    samples: Sequence[Mapping],
    *,
    channels: tuple[str, str] | None = None,
    figure: Callable | None = None,
) -> Figure:
    """local_maxima.png, the figure the populations are chosen from: one panel per file of its
    density grid, local maxima and the peak each Pop grows from (flow_plot.peaks of its "peaks"),
    its axes named by channels, the two gated on, when given."""
    fig, axs = _panels(len(samples), (6.5, 5.2), figure)
    for i, s in enumerate(samples):
        title = f"File {i + 1}: {s['path'].name}"
        flow_plot.peaks(s["peaks"], title=title, ax=axs[i], channels=channels)
    fig.tight_layout()
    return fig


def gates_figure(
    samples: Sequence[Mapping],
    *,
    channels: tuple[str, str] | None = None,
    figure: Callable | None = None,
) -> Figure:
    """gates.png: one panel per file of its events in gray and each of its populations in color
    (flow_plot.gates of its "fsc", "ssc" and "masks"), its axes named by channels, the two gated
    on, when given. A file whose events lie past the finder's grid, as the few past a channel's
    range that the gate leaves out do, is drawn on the grid's extent, so its populations aren't
    squeezed into a corner."""
    fig, axs = _panels(len(samples), (5.5, 4.8), figure)
    for i, s in enumerate(samples):
        title = f"File {i + 1}: {s['path'].name}"
        flow_plot.gates(s["fsc"], s["ssc"], s["masks"], title=title, ax=axs[i], channels=channels)
        p = s["peaks"]
        if s["fsc"].max() > p.fsc.max() or s["ssc"].max() > p.ssc.max():
            axs[i].set_xlim(_padded(p.fsc))
            axs[i].set_ylim(_padded(p.ssc))
    fig.tight_layout()
    return fig


def _padded(v) -> tuple[float, float]:
    """v's extent with matplotlib's default margin of 5% on each side."""
    lo, hi = float(np.min(v)), float(np.max(v))
    pad = 0.05 * (hi - lo)
    return lo - pad, hi + pad


def result_figures(
    pool,
    centers,
    labels: Sequence[str],
    cofactor: float | Sequence[float],
    tsne_xy,
    *,
    figure: Callable | None = None,
    colors: Sequence | None = None,
) -> dict[str, Figure]:
    """The clustering's figures by file name, in the order a run saves them: dendrogram.png (for
    the hierarchical tree only), clusters_pca.png, clusters_tsne.png (left out when tsne_xy, the
    t-SNE of the nuggets in use, is None) and cluster_centers.png. centers is the cluster_centers
    table, one column per label,
    and cofactor the one its values were transformed with, or one per channel, which its colour
    bar names but doesn't list. colors gives cluster c (from 0) its colour, as
    colors.cluster_colors makes them; None takes matplotlib's colour cycle, which repeats past its
    length. Up to 8 clusters they are the same colours, so the figures are the same."""
    new = figure or Figure
    use, k = pool.use, pool.k
    figs = {}
    if pool.tree is not None:  # weighted k-means has no tree to draw
        fig = new(figsize=(8, 4))
        ax = fig.subplots()
        plot.dendrogram(pool.tree, labels=False, hang=-1, ax=ax)
        ax.set_title(f"Hierarchical tree of {use.sum():,} nuggets")
        figs["dendrogram.png"] = fig
    fig = new(figsize=(6, 6))
    ax = fig.subplots()
    pca = wpca(pool.centers[use], wrow=pool.weights[use])
    plot.scores(pca, w=pool.weights[use], labels=pool.cl[use], colors=colors, ax=ax)
    ax.set_title(f"Nuggets of the kept cells, {k} clusters")
    figs["clusters_pca.png"] = fig
    if tsne_xy is not None:
        fig = new(figsize=(6.5, 6))
        ax = fig.subplots()
        plot.clusters(tsne_xy, pool.cl[use], w=pool.weights[use], size="sqrt", colors=colors, ax=ax)
        drawn = _label_colors(range(k), _palette(colors))  # plot.clusters' own, by construction
        handles = [
            Line2D([], [], ls="none", marker="o", color=color, label=str(c + 1))
            for c, color in enumerate(drawn)
        ]
        ax.legend(
            handles=handles,
            title="cluster",
            loc="center left",
            bbox_to_anchor=(1, 0.5),
            ncols=-(-k // FLOW_LEGEND_ROWS),
        )
        ax.set(xlabel="t-SNE 1", ylabel="t-SNE 2")
        ax.set_title(f"t-SNE of {use.sum():,} nuggets, {k} clusters; area ∝ √weight")
        fig.tight_layout()
        figs["clusters_tsne.png"] = fig
    fig = new(figsize=(8, 8))
    ax = fig.subplots()
    im = ax.imshow(centers[list(labels)].to_numpy().T, aspect="auto", cmap="viridis")
    ax.set_xticks(range(k), [str(c) for c in range(1, k + 1)])
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.set_xlabel("cluster")
    if np.ndim(cofactor):
        label = "arcsinh(x / c), c per channel"
    else:
        label = f"arcsinh(x / {cofactor:g})" if cofactor else "x"
    fig.colorbar(im, ax=ax, label=label)
    fig.tight_layout()
    figs["cluster_centers.png"] = fig
    return figs


def png_figure(path: Path, dpi: int, *, figure: Callable | None = None) -> Figure:
    """A figure saved at dpi, such as a gate folder's local_maxima.png, drawn again at the size it
    was drawn at, its axes off, so a later stage can show it without the data behind it."""
    image = imread(path)
    fig = (figure or Figure)(figsize=(image.shape[1] / dpi, image.shape[0] / dpi))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.imshow(image)
    ax.set_axis_off()
    return fig


def save_figures(figs: Mapping[str, Figure], out: Path, dpi: int) -> list[Path]:
    """Each figure saved in the folder out under its name, at dpi; the paths, in figs' order."""
    paths = []
    for name, fig in figs.items():
        fig.savefig(out / name, dpi=dpi)
        paths.append(out / name)
    return paths
