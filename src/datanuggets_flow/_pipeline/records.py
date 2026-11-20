"""The records the steps pass along and give back: a step's StageEvent, a gated file's Sample
and its populations' PopStats, the Transform stage's Cofactor, the Scale stage's Scaling, a file's
Kept nuggets, their Pool and clusters, the run's Tables and cluster_stage's RunResult, and the
types of a reader, of a reader of the files' channel ranges and of an event callback."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, TypedDict

import numpy as np

from datanuggets_flow._defaults import FLOW_COFACTOR_MIN_NEGATIVE

if TYPE_CHECKING:
    import pandas as pd
    from datanuggets import DataNuggets, WhclustResult

    from datanuggets_flow.gate import FinderPeaks


class StageEvent(NamedTuple):
    """What a step reports as it goes: its stage ("gate", "select", "cofactor", "transform",
    "scale", "nuggets" or "cluster"), the file it is about (numbered from 1; None for the whole
    run) of n_files, message, the lines the CLI prints for it ("" for a progress event with
    nothing to print), and data, the same facts as values."""

    stage: str
    file: int | None
    n_files: int
    message: str
    data: Mapping[str, object]


Reader = Callable[[Path], tuple[np.ndarray, list[str], list[str]]]  # read_fcs, or a stand-in
# read_ranges, or a stand-in: each channel's $PnN and its range, None where there is none
RangesReader = Callable[[Path], tuple[list[str], list[float | None]]]
OnEvent = Callable[[StageEvent], None]


class Cofactor(NamedTuple):
    """The Transform stage's cofactor for a run, as resolve_cofactor gives it. source is "set"
    when it was given as a number, value, used for every channel (0 keeping them linear), and
    "auto" when it was picked per channel from the cells the run clusters: values holds each
    clustered channel's cofactor in channel order, negative the share of its cells below 0 and
    spread the SD of those cells (None for a channel with none), and value is the floor. range is
    only on a record of the earlier rule, which picked one auto number from the files' headers:
    the widest marker channel range they gave (None when one gave none), with no values."""

    value: float
    source: str
    range: float | None = None
    values: tuple[float, ...] | None = None
    negative: tuple[float, ...] | None = None
    spread: tuple[float | None, ...] | None = None

    @property
    def applied(self) -> float | tuple[float, ...]:
        """What the steps after the resolve take as settings.cofactor: each channel's cofactor
        as a tuple, or the one number."""
        return tuple(self.values) if self.values is not None else float(self.value)

    def per_channel(self, p: int) -> np.ndarray:
        """Each of p channels' cofactor: values, which must give p, or value for every one."""
        if self.values is None:
            return np.full(p, float(self.value))
        if len(self.values) != p:
            raise ValueError(f"the cofactor gives {len(self.values)} channels' values, not {p}")
        return np.asarray(self.values, dtype=float)

    def transform(self) -> dict[str, object]:
        """The Transform stage as run.json and the transform event record it: arcsinh with each
        channel's cofactor, its share of cells below 0 and their SD (null for none), and the rule's
        floor and guard; arcsinh with the one cofactor used and how it was chosen (a record of the
        earlier rule keeping its range); or none for a set cofactor of 0. The per-channel record
        has no single cofactor, as one number would mislead."""
        if self.values is not None:
            return {
                "name": "arcsinh",
                "cofactor_from": self.source,
                "cofactors": [float(c) for c in self.values],
                "negative_fraction": _listed(self.negative),
                "negative_sd": _listed(self.spread),
                "floor": float(self.value),
                "min_negative_fraction": FLOW_COFACTOR_MIN_NEGATIVE,
            }
        if not self.value:
            return {"name": "none"}
        record = {"name": "arcsinh", "cofactor": float(self.value), "cofactor_from": self.source}
        return record | {"range": self.range} if self.source == "auto" else record


def _listed(values) -> list[float | None] | None:
    return None if values is None else [None if v is None else float(v) for v in values]


class PopStats(NamedTuple):
    """A population's size and place: its events, as a percent of the file's, the median of each
    scatter channel over them (0 for an empty population), and its peak's grid cell."""

    pop: int  # numbered from 1
    events: int
    percent: float
    median_fsc: float
    median_ssc: float
    peak: tuple[int, int]


class Sample(TypedDict):
    """A gated file, as gate_files gives it. It is a dict, so the CLI's prompt reads it as before;
    fsc and ssc are kept for gates.png, and are None in a sample state.load_gates reads, whose
    gates.png is drawn already."""

    number: int  # numbered from 1, in the order the files were given
    path: Path
    n_events: int
    pnn: list[str]
    pns: list[str]
    masks: np.ndarray  # one bool column per population, one row per event
    peaks: FinderPeaks  # what local_maxima.png draws
    stats: list[PopStats]
    table: list[str]  # population_table of stats
    local_maxima: int
    t11: float
    t21: float
    fsc: np.ndarray | None
    ssc: np.ndarray | None


class Kept(NamedTuple):
    """A file's kept cells as data nuggets: the file's number and name, and the cells' rows in
    it, numbered from 0. means is each nugget's cell mean on the clustering scale when the
    centers aren't the means (center_method "original" or "random"), None when they are; a nugget
    no cell joined keeps its center there."""

    number: int
    name: str
    rows: np.ndarray
    dn: DataNuggets
    means: np.ndarray | None = None

    def cell_means(self) -> np.ndarray:
        """Each nugget's cell mean on the clustering scale."""
        return self.dn.centers if self.means is None else self.means


class Scaling(NamedTuple):
    """The Scale stage: each channel's mean and SD (ddof 0) pooled over every clustered file's
    kept cells after the Transform stage, cells of them in files files, and the same cells'
    skewness (the third central moment over the SD cubed; 0 for a channel with one value). A
    channel with one value in every cell has SD 0 and is scaled by 1. apply centres and scales
    values in the transform's units; undo takes scaled values back to them."""

    mean: np.ndarray
    sd: np.ndarray
    cells: int
    files: int
    skew: np.ndarray

    def apply(self, x: np.ndarray) -> np.ndarray:
        return (x - self.mean) / self.sd

    def undo(self, x: np.ndarray) -> np.ndarray:
        return x * self.sd + self.mean

    def record(self) -> dict[str, object]:
        """The stage as run.json and the scale event record it."""
        return {
            "mean": self.mean.tolist(),
            "sd": self.sd.tolist(),
            "ddof": 0,
            "cells": int(self.cells),
            "skew": self.skew.tolist(),
        }


class Pool(NamedTuple):
    """Every kept file's nuggets, pooled in the files' order, and their clusters. With the Scale
    stage, the centers are on its scale and scaling takes them back to the transform's units;
    without it, scaling is None and the centers are in those units. The centers are what was
    clustered; means, when the centers aren't the cell means, holds those, and the tables of
    marker levels read cell_means(), so a cluster's levels are its cells' own mean. wwcss is the
    total weighted within-cluster sum of squares of the centers in use under their clusters,
    with their weights, on the clustering scale: what weighted k-means makes small, recorded
    for either method."""

    centers: np.ndarray
    weights: np.ndarray
    use: np.ndarray  # the nuggets some cell joined; the others have no say in the clusters
    tree: WhclustResult | None  # Whclust of the nuggets in use, or None for weighted k-means
    cl: np.ndarray  # each nugget's cluster, numbered from 0, or -1 for one not in use
    k: int
    scaling: Scaling | None = None
    means: np.ndarray | None = None
    wwcss: float | None = None

    def values(self, x: np.ndarray) -> np.ndarray:
        """x, on the clustering scale, in the transform's units: what every table of channel
        values gives."""
        return x if self.scaling is None else self.scaling.undo(x)

    def cell_means(self) -> np.ndarray:
        """Each nugget's cell mean on the clustering scale."""
        return self.centers if self.means is None else self.means


class Tables(NamedTuple):
    """The run's tables: nuggets_N.csv and events_N.csv by file number N, cluster_summary.csv
    and cluster_centers.csv."""

    nuggets: dict[int, pd.DataFrame]
    events: dict[int, pd.DataFrame]
    summary: pd.DataFrame
    centers: pd.DataFrame


class RunResult(NamedTuple):
    """What cluster_stage made: the channels clustered and their labels, selection.csv's table,
    each kept file's nuggets, their pool and clusters, the tables, the t-SNE of the nuggets in use
    (None without it), the files written, in the order they were written, and the Transform
    stage's cofactor (None only in a RunResult built without one)."""

    channels: list[str]
    labels: list[str]
    selection: pd.DataFrame
    kept: list[Kept]
    pool: Pool
    tables: Tables
    tsne: np.ndarray | None
    files: list[Path]
    cofactor: Cofactor | None = None
