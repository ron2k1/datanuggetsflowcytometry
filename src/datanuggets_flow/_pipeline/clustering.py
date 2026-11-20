"""The clustering steps: the channels to cluster, the auto cofactor's tally of their raw values,
the Scale stage's pooled mean and SD, each file's kept cells as data nuggets, the clustering of
every file's nuggets together (weighted k-means, or the hierarchical tree), and the t-SNE of
them."""

from __future__ import annotations

import re
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
from datanuggets import DataNuggetWarning, RDraws, create_dn, cut_tree, whclust, wkmeans, wwcss

from datanuggets_flow._defaults import (
    FLOW_CHANNEL_SUFFIX,
    FLOW_MAX_ITER,
    FLOW_METHOD,
    FLOW_NUM_INIT,
    FLOW_SCATTER_PATTERNS,
    FLOW_TIME_PATTERN,
    SEED,
)
from datanuggets_flow._pipeline.cofactor import NegativeTally
from datanuggets_flow._pipeline.fcs import read_fcs
from datanuggets_flow._pipeline.records import (
    Kept,
    OnEvent,
    Pool,
    Reader,
    Scaling,
    StageEvent,
)
from datanuggets_flow._pipeline.selection import pick_events
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.settings import check_channels

if TYPE_CHECKING:
    from datanuggets.filters import RowFilter

    from datanuggets_flow.outputs import CellSample
    from datanuggets_flow.settings import ClusterSettings

MIN_KEPT_EVENTS = 2  # create_dn needs two rows; a file keeping fewer is left out
MIN_OCCUPIED_NUGGETS = 3  # the fewest nuggets in use that the clustering is run on
# forward and side scatter's names, matched as the app's page matches them
SCATTER = tuple(re.compile(p, re.IGNORECASE | re.ASCII) for p in FLOW_SCATTER_PATTERNS)


def default_channels(pnn: Sequence[str]) -> list[str]:
    """The channels clustered when none are named, in pnn's order: every -A channel but forward
    and side scatter (SCATTER), or every channel but those and Time when there are fewer than two,
    as on instruments that record no areas."""
    markers = [c for c in pnn if not any(s.match(c) for s in SCATTER)]
    channels = [c for c in markers if c.endswith(FLOW_CHANNEL_SUFFIX)]
    if len(set(channels)) < 2:
        time = re.compile(FLOW_TIME_PATTERN, re.IGNORECASE | re.ASCII)  # as the app's page
        channels = [c for c in markers if not time.match(c)]
    return channels


def resolve_channels(
    samples: Sequence[Mapping], settings: ClusterSettings
) -> tuple[list[str], list[str]]:
    """The fluorescence channels to cluster, the same ones in every file, and their labels:
    settings.channels, or the first file's default_channels, less settings.exclude_channels,
    refused by check_channels when they aren't two or more distinct ones. A label is the first
    file's $PnS with the $PnN, or the $PnN alone."""
    first = samples[0]
    pnn, pns = first["pnn"], first["pns"]
    for c in settings.exclude_channels:
        if c not in pnn:
            raise FlowError(
                f"{{param}} names {c}, which {first['path'].name} doesn't have; its channels: "
                f"{', '.join(pnn)}",
                "exclude_channels",
            )
    channels = default_channels(pnn) if settings.channels is None else list(settings.channels)
    channels = [c for c in channels if c not in settings.exclude_channels]
    check_channels(channels)
    for s in samples:
        missing = [c for c in channels if c not in s["pnn"]]
        if missing:
            raise FlowError(
                f"{s['path'].name} has no channel {missing[0]}; its channels: {', '.join(s['pnn'])}",
                "channels",
            )
    return channels, [f"{pns[pnn.index(c)]} ({c})" if pns[pnn.index(c)] else c for c in channels]


def warn_stain_differences(samples: Sequence[Mapping], channels: Sequence[str]) -> None:
    """A DataNuggetWarning naming each of channels whose stain ($PnS) differs between the files,
    with each stain and the files that give it, since resolve_channels labels a channel with the
    first file's stain alone. A file without a stain for the channel never differs."""
    parts = []
    for c in channels:
        files: dict[str, list[str]] = {}
        for s in samples:
            stain = s["pns"][s["pnn"].index(c)].strip()
            if stain:
                files.setdefault(stain, []).append(s["path"].name)
        if len(files) > 1:
            parts.append(
                f"{c} is " + " or ".join(f"{k} ({', '.join(v)})" for k, v in files.items())
            )
    if parts:
        warnings.warn(
            f"Stains differ between files: {'; '.join(parts)}. The run labels each channel with "
            f"{samples[0]['path'].name}'s stain; check that the files name the same markers",
            DataNuggetWarning,
            stacklevel=2,
        )


def _warn_constant(channels: Sequence[str], constant: np.ndarray) -> None:
    """A DataNuggetWarning naming the channels that take one value in every clustered cell."""
    names = [c for c, k in zip(channels, constant) if k]
    if names:
        one = len(names) == 1
        warnings.warn(
            f"{', '.join(names)} {'takes' if one else 'each take'} one value in every clustered "
            f"cell, so {'it adds' if one else 'they add'} nothing to the clusters; leave "
            f"{'it' if one else 'them'} out of the channels to cluster",
            DataNuggetWarning,
            stacklevel=3,
        )


def _each_file(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    channels: Sequence[str],
    settings: ClusterSettings,
    read: Reader,
    *,
    refuse: bool = True,
) -> Iterator[tuple[int, Mapping, np.ndarray | None, np.ndarray]]:
    """Each file's kept cells after the Transform stage, one file read at a time: its index, its
    sample, the cells' channels as arcsinh(x / cofactor) (as stored with cofactor 0), and their
    rows. settings.row_filters, on the raw events, AND with the populations chosen. A file whose
    populations alone keep too few cells isn't read, and comes with None for its cells; a file
    keeping fewer than MIN_KEPT_EVENTS once filtered is for the caller to leave out. The cofactor
    must be a number, or a tuple of one per channel: "auto" is refused, as cluster_stage resolves
    it before this runs. A channel holding NaN or an infinite value is refused unless refuse is
    off, for finite_channels to find."""
    filters = settings.filters()
    keeps = [pick_events(s["masks"], pops) for s, pops in zip(samples, chosen)]
    if not any(keep.sum() >= MIN_KEPT_EVENTS for keep in keeps):
        raise FlowError("no file has cells kept, so there is nothing to cluster")
    for s, keep in zip(samples, keeps):
        missing = [f.column for f in filters if f.column not in s["pnn"]]
        if keep.any() and missing:
            raise FlowError(
                f"{{param}} names {missing[0]}, which {s['path'].name} doesn't have; its "
                f"channels: {', '.join(s['pnn'])}",
                "row_filters",
            )
    if isinstance(settings.cofactor, str):
        raise FlowError(
            "{param} is auto, which cluster_stage resolves from the cells it clusters; give this "
            "step the cofactors resolve_cofactor picks",
            "cofactor",
        )
    least = 1 if filters else MIN_KEPT_EVENTS  # filters can only take cells away
    for i, (s, keep) in enumerate(zip(samples, keeps)):
        rows, x = np.flatnonzero(keep), None
        if len(rows) >= least:
            x, rows = _kept_cells(s, rows, channels, settings.cofactor, read, filters)
            if refuse:
                _refuse_non_finite(s["path"].name, channels, x)
        yield i, s, x, rows


def _refuse_non_finite(name: str, channels: Sequence[str], x: np.ndarray) -> None:
    """A channel holding NaN or an infinite value among the cells to cluster, as a processed
    file's label column can, refused by name, so every clustering pass stops the same way. Live
    cells reads the same cells and counts NaN instead."""
    bad = [c for c, ok in zip(channels, np.isfinite(x).all(axis=0)) if not ok]
    if bad:
        raise FlowError(
            f"{name} holds values that aren't numbers (NaN or infinite) in {', '.join(bad)} among "
            f"the cells kept; leave {'it' if len(bad) == 1 else 'them'} out of the channels to "
            "cluster"
        )


def finite_channels(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    channels: Sequence[str],
    labels: Sequence[str],
    settings: ClusterSettings,
    *,
    read: Reader = read_fcs,
    on_event: OnEvent | None = None,
) -> tuple[list[str], list[str]]:
    """The default channels and their labels less those holding NaN or an infinite value among
    the cells kept in any file, as a processed file's label column can, with a DataNuggetWarning
    naming them: the run chose them, so it leaves out what it can't cluster, where a channel it was
    given by name is refused. One pass over the files' raw values, a "channels" event per file as
    negative_tally's "cofactor" ones. Refused when fewer than two are left."""
    raw = replace(settings, cofactor=0.0)  # NaN and infinity are so before any arcsinh
    bad = np.zeros(len(channels), dtype=bool)
    for i, _, x, rows in _each_file(samples, chosen, channels, raw, read, refuse=False):
        if x is not None:
            bad |= ~np.isfinite(x).all(axis=0)
        if on_event:
            nb = len(rows) if len(rows) >= MIN_KEPT_EVENTS else 0
            on_event(StageEvent("channels", i + 1, len(samples), "", {"cells": nb}))
    if not bad.any():
        return list(channels), list(labels)
    names = [c for c, b in zip(channels, bad) if b]
    kept = [(c, label) for c, label, b in zip(channels, labels, bad) if not b]
    one = len(names) == 1
    what = (
        f"{', '.join(names)} {'holds' if one else 'hold'} values that aren't numbers (NaN or "
        "infinite) among the cells kept"
    )
    if len({c for c, _ in kept}) < 2:
        raise FlowError(
            f"{what}, which leaves fewer than two default channels; name the channels to cluster "
            "with {param}",
            "channels",
        )
    warnings.warn(
        f"{what}, so {'it is' if one else 'they are'} left out of the default channels",
        DataNuggetWarning,
        stacklevel=2,
    )
    return [c for c, _ in kept], [label for _, label in kept]


def _nothing_kept() -> FlowError:
    return FlowError(
        f"{{param}} keeps fewer than {MIN_KEPT_EVENTS} cells in every file, so there is nothing to "
        "cluster",
        "row_filters",
    )


def negative_tally(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    channels: Sequence[str],
    settings: ClusterSettings,
    *,
    read: Reader = read_fcs,
    on_event: OnEvent | None = None,
) -> NegativeTally:
    """The auto cofactor's NegativeTally: each channel's raw values, before any arcsinh, over the
    cells make_nuggets clusters, every clustered file's kept cells after the populations and the
    row filters, pooled. A file make_nuggets leaves out counts for nothing. Files are read one at
    a time, the same pass pooled_scaling makes, and settings.cofactor isn't used, so "auto" is
    taken here. A "cofactor" event per file, its message empty and its data the cells it counted,
    lets a backend move its bar and stop the run between files."""
    tally = NegativeTally(len(channels))
    raw = replace(settings, cofactor=0.0)
    for i, _, x, rows in _each_file(samples, chosen, channels, raw, read):
        nb = len(rows) if len(rows) >= MIN_KEPT_EVENTS else 0
        if nb:
            tally.add(x)
        if on_event:
            on_event(StageEvent("cofactor", i + 1, len(samples), "", {"cells": nb}))
    if not tally.cells.any():
        raise _nothing_kept()
    return tally


def pooled_scaling(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    channels: Sequence[str],
    settings: ClusterSettings,
    *,
    read: Reader = read_fcs,
    on_event: OnEvent | None = None,
) -> Scaling:
    """The Scale stage's statistics: each channel's mean, SD (ddof 0) and skewness over the cells
    make_nuggets clusters, every clustered file's kept cells after the populations, the row
    filters and the Transform stage, pooled, not per file. A file make_nuggets leaves out counts
    for nothing. Files are read one at a time and combined by Chan's parallel update of the
    second and third central moments in float64, so one file's events are in memory at once. A
    channel with the same value in every cell has SD 0 and is scaled by 1, as analyze's
    standardize does, and skewness 0. A "scale" event per file, its message empty and its data
    the cells it counted, lets a backend move its bar and stop the run between files."""
    p = len(channels)
    n, mean, m2, m3 = 0, np.zeros(p), np.zeros(p), np.zeros(p)
    low, high = np.full(p, np.inf), np.full(p, -np.inf)
    files = 0
    for i, _, x, rows in _each_file(samples, chosen, channels, settings, read):
        nb = len(rows) if len(rows) >= MIN_KEPT_EVENTS else 0
        if nb:
            x = np.asarray(x, dtype=np.float64)
            mb = x.mean(axis=0)
            d = x - mb
            m2b, m3b = (d**2).sum(axis=0), (d**3).sum(axis=0)
            delta, total = mb - mean, n + nb
            m3 = (
                m3
                + m3b
                + delta**3 * (n * nb * (n - nb) / total**2)
                + 3 * delta * (n * m2b - nb * m2) / total
            )
            mean = mean + delta * (nb / total)
            m2 = m2 + m2b + delta**2 * (n * nb / total)
            n, files = total, files + 1
            low, high = np.minimum(low, x.min(axis=0)), np.maximum(high, x.max(axis=0))
        if on_event:
            on_event(StageEvent("scale", i + 1, len(samples), "", {"cells": nb}))
    if not n:
        raise _nothing_kept()
    sd = np.sqrt(m2 / n)
    constant = low == high
    skew = np.zeros(p)
    skew[~constant] = np.sqrt(n) * m3[~constant] / m2[~constant] ** 1.5
    mean[constant], sd[constant] = low[constant], 1.0
    return Scaling(mean, sd, n, files, skew)


def make_nuggets(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    channels: Sequence[str],
    settings: ClusterSettings,
    *,
    read: Reader = read_fcs,
    on_event: OnEvent | None = None,
    filtered: dict[int, int] | None = None,
    cells: dict[int, CellSample] | None = None,
    scaling: Scaling | None = None,
) -> list[Kept]:
    """Data nuggets of each file's kept cells, one file at a time: the file is read again, so one
    file's events are in memory at once, and its channels go to create_dn as arcsinh(x /
    cofactor), or as stored with cofactor 0, then centred and scaled by scaling (pooled_scaling)
    when it is given. create_dn draws from settings.seed as settings.draws says: "r" passes
    RDraws(seed), R's set.seed(seed) draws, so each file's nuggets are create.DN's on the same
    cells; "numpy" passes the int seed. settings.row_filters, on the raw events, AND with the
    populations chosen. A file keeping fewer than MIN_KEPT_EVENTS once filtered is left out, and
    without being read when its populations alone keep too few. A "nuggets" event per file
    carries its line, and a channel that takes one value in every cell kept gives a
    DataNuggetWarning. filtered, when given, gets each file's kept cells that pass the filters by
    file number, and cells each clustered file's outputs.sample_cells, its values in the
    transform's units."""
    from datanuggets_flow.outputs import sample_cells

    seed = RDraws(settings.seed) if settings.draws == "r" else settings.seed
    kept = []
    low = high = np.full(len(channels), np.nan)
    for i, s, x, rows in _each_file(samples, chosen, channels, settings, read):
        if filtered is not None:
            filtered[i + 1] = len(rows)
        if len(rows) < MIN_KEPT_EVENTS:
            continue  # left out, or too few cells for data nuggets
        low, high = np.fmin(low, x.min(axis=0)), np.fmax(high, x.max(axis=0))
        xs = x if scaling is None else scaling.apply(x)
        dn = create_dn(
            xs,
            center_method=settings.center_method,
            dn_num1=settings.dn_num1,
            dn_num2=min(settings.dn_num2, len(x)),
            seed=seed,
            n_jobs=settings.n_jobs,
        )
        means = None if settings.center_method == "mean" else _nugget_means(xs, dn)
        name = s["path"].name
        kept.append(Kept(i + 1, name, rows, dn, means))
        sample = sample_cells(x, i + 1, settings) if cells is not None else None
        if sample is not None:
            cells[i + 1] = sample
        if on_event:
            line = f"File {i + 1}, {name}: {len(x):,} cells, {dn.n_nuggets:,} nuggets"
            data = {"cells": len(x), "nuggets": dn.n_nuggets}
            on_event(StageEvent("nuggets", i + 1, len(samples), line, data))
    if not kept:
        raise _nothing_kept()
    _warn_constant(channels, low == high)
    return kept


def _kept_cells(
    sample, rows, channels, cofactor, read, filters: Sequence[RowFilter] = ()
) -> tuple[np.ndarray, np.ndarray]:
    """The rows that pass filters, on the raw events, and their channels, read from the file
    again and transformed as make_nuggets clusters them: arcsinh(x / cofactor), cofactor one
    number or one per channel, or as stored with 0. The file must still have the events and
    channels it was gated with, since the masks choose rows by number."""
    from datanuggets.filters import filter_mask

    name = sample["path"].name
    events, pnn, _ = read(sample["path"])
    if len(events) != sample["n_events"]:
        raise FlowError(
            f"{name} isn't the file that was gated: it has {len(events):,} events, where the gated "
            f"file had {sample['n_events']:,}"
        )
    if list(pnn) != list(sample["pnn"]):
        raise FlowError(
            f"{name} isn't the file that was gated: its channels are {', '.join(pnn)}, where the "
            f"gated file's were {', '.join(sample['pnn'])}"
        )
    if filters:
        raw = events[rows]
        try:
            rows = rows[filter_mask(lambda c: raw[:, pnn.index(c)], filters, len(rows))]
        except ValueError as e:
            raise FlowError(f"{{param}} in {name}: {e}", "row_filters") from None
    x = events[np.ix_(rows, [pnn.index(c) for c in channels])]
    c = np.asarray(cofactor, dtype=float)  # a tuple broadcasts over the channels
    return np.ascontiguousarray(np.arcsinh(x / c) if np.any(c) else x), rows


def _nugget_means(x: np.ndarray, dn) -> np.ndarray:
    """Each nugget's mean of the cells assigned to it (x, as create_dn was given them), or its
    center for a nugget no cell joined."""
    n = dn.n_nuggets
    counts = np.bincount(dn.assignments, minlength=n)
    sums = np.column_stack(
        [np.bincount(dn.assignments, weights=x[:, j], minlength=n) for j in range(x.shape[1])]
    )
    out = np.array(dn.centers, dtype=np.float64, copy=True)
    has = counts > 0
    out[has] = sums[has] / counts[has, None]
    return out


def cluster_nuggets(
    kept: Sequence[Kept],
    k: int,
    scaling: Scaling | None = None,
    *,
    method: str = FLOW_METHOD,
    num_init: int = FLOW_NUM_INIT,
    max_iter: int = FLOW_MAX_ITER,
    seed: int = SEED,
    n_jobs: int = 1,
) -> Pool:
    """All the kept files' nuggets clustered together into k clusters, with their weights. A
    nugget no cell joined (weight 0) has no say in the clusters and no cluster. Method "wkmeans"
    is WCluster's weighted k-means (num_init starts of up to max_iter rounds, drawn as R's
    set.seed(seed) draws, so the clusters are Wkmeans on the pooled Weight > 0 nuggets) at
    exactly k: with fewer than two nuggets in use per cluster, which its random start can't
    fill and where R would draw forever, it stops with a FlowError that names k and dn_num2, and
    when wkmeans gives up drawing starts, with one that names k and the tree, rather than
    clustering with a smaller k than asked.
    Its cluster numbers keep R's order, renumbered from 0 without gaps when a cluster empties,
    and k is the number left. Method "tree" is the hierarchical tree, Whclust cut into k, or
    into as many as there are nuggets in use when that's fewer. The pool's wwcss is the total
    WWCSS of the centers in use under their clusters. scaling is the one make_nuggets built the
    nuggets on, kept with the pool so its tables can give values in the transform's units."""
    centers = np.vstack([kp.dn.centers for kp in kept])
    weights = np.concatenate([kp.dn.weights for kp in kept]).astype(float)
    means = None
    if any(kp.means is not None for kp in kept):
        means = np.vstack([kp.cell_means() for kp in kept])
    use = weights > 0  # a nugget no cell joined has no say in the clusters
    used = int(use.sum())
    if used < MIN_OCCUPIED_NUGGETS:
        raise FlowError(
            f"the kept cells make fewer than {MIN_OCCUPIED_NUGGETS} occupied nuggets, too few to "
            "cluster; keep more cells or increase {param}",
            "dn_num2",
        )
    cl = np.full(len(centers), -1)
    tree = None
    if method == "tree":
        k = min(k, used)
        tree = whclust(centers[use], weights[use])
        cl[use] = cut_tree(tree, k=k)
        total = wwcss(centers[use], cl[use], weights[use])
    elif method == "wkmeans":
        if used < 2 * k:
            raise FlowError(
                f"weighted k-means needs two nuggets in use per cluster: k = {k} needs "
                f"{2 * k:,}, and the kept cells fill {used:,}; lower k or increase {{param}}",
                "dn_num2",
            )
        draws = RDraws(seed)  # outside the try: a seed R refuses isn't a k or dn_num2 problem
        try:
            res = wkmeans(
                centers[use],
                k,
                w=weights[use],
                num_init=num_init,
                max_iter=max_iter,
                seed=draws,
                n_jobs=n_jobs,
            )
        except ValueError as e:
            # a lower k or the tree always helps here; more nuggets help only near 2k, and on a
            # large pool they crowd the start's partition means together and fail more often
            raise FlowError(
                f"weighted k-means can't make k = {k} clusters of these {used:,} nuggets ({e}); "
                "lower {param} or use method tree",
                "k",
            ) from None
        _, labels = np.unique(res.labels, return_inverse=True)
        cl[use] = labels
        k = int(labels.max()) + 1
        total = res.total_wwcss
    else:
        raise ValueError(f"unknown method {method!r}")
    return Pool(centers, weights, use, tree, cl, k, scaling, means, float(total))


def tsne_embedding(centers: np.ndarray, settings: ClusterSettings) -> np.ndarray:
    """A 2-D t-SNE of the nugget centers, seeded with settings.tsne_seed so a run repeats, its
    shape set by TSNE_ARGS. The perplexity is capped at (n - 1) / 3 for n nuggets, as scikit-learn
    needs it below n."""
    from datanuggets.projection import tsne_2d

    return tsne_2d(centers, perplexity=settings.tsne_perplexity, seed=settings.tsne_seed)
