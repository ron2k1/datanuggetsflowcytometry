"""The flow pipeline's settings, one frozen dataclass per stage: GateSettings for the gate finder,
ClusterSettings for data nuggets, their clustering (weighted k-means or the hierarchical tree) and
the t-SNE. Their defaults are datanuggets-flow's,
from _defaults. check() refuses a bad value with a FlowError naming the setting, which the CLI
shows as its flag (cli_flag) and the library by its name. to_dict and from_dict carry the
settings through JSON, so a stage can record the ones it ran with."""

from __future__ import annotations

import math
import numbers
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from typing import Self

from datanuggets.filters import parse_filter

from datanuggets_flow._defaults import (
    CENTER_METHODS,
    DN_NUM1,
    DRAWS,
    FINDER_N_COL,
    FINDER_N_ROW,
    FINDER_T11,
    FINDER_T12,
    FINDER_T21,
    FINDER_T22,
    FLOW_CELLS_PER_FILE,
    FLOW_CENTER_METHOD,
    FLOW_COFACTOR,
    FLOW_COFACTOR_AUTO,
    FLOW_DISC,
    FLOW_DN_NUM2,
    FLOW_DRAWS,
    FLOW_FSC,
    FLOW_GROUP_NAME,
    FLOW_K,
    FLOW_LEGACY_CENTER_METHOD,
    FLOW_LEGACY_DRAWS,
    FLOW_LEGACY_METHOD,
    FLOW_MAX_ITER,
    FLOW_METHOD,
    FLOW_METHODS,
    FLOW_N_JOBS,
    FLOW_NUM_INIT,
    FLOW_SSC,
    FLOW_STANDARDIZE,
    SEED,
    SEED_MAX,
    TSNE_PERPLEXITY,
    TSNE_SEED,
)
from datanuggets_flow._validate import check_n_jobs
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.gate import MSIZE
from datanuggets_flow.peaks import find_area, mirrored_area

AREAS = {"reference": mirrored_area, "peak": find_area}  # disc's area rules
DISC_ALIASES = {"his": "reference"}  # their old names, still read
# the settings whose flag isn't their name
FLAGS = {
    "n_jobs": "--jobs",
    "tsne": "--no-tsne",
    "standardize": "--no-standardize",
    "row_filters": "--filter",
}
GROUP_NAME = re.compile(FLOW_GROUP_NAME)


def cli_flag(name: str) -> str:
    """The datanuggets-flow flag that sets name: --dn-num2 for dn_num2, and --jobs for n_jobs."""
    return FLAGS.get(name, "--" + name.replace("_", "-"))


def _finite(v) -> bool:
    """v is a finite number. A bool isn't, though Python counts it as one."""
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and math.isfinite(v)


def _whole(v, low, high=math.inf) -> bool:
    """v is an int, not a bool, from low to high."""
    return isinstance(v, int) and not isinstance(v, bool) and low <= v <= high


def _refused(name: str, value, takes: str) -> FlowError:
    """The error for a setting whose value is out of range, saying what it takes."""
    return FlowError(f"{{param}} is {value}; it takes {takes}", name)


def check_channels(channels: Sequence[str]) -> None:
    """Refuses channels to cluster that aren't two or more distinct ones, or that name one twice,
    with a FlowError naming channels. The rule is kept here alone: ClusterSettings.check runs it
    on a list given before any file is read, and pipeline.resolve_channels on the list it settles
    on once a file's channels are known, which the default rule or an exclusion can leave short."""
    if len(set(channels)) < 2:
        raise FlowError(
            "choose at least two distinct fluorescence channels for clustering and PCA", "channels"
        )
    if len(set(channels)) != len(channels):
        raise FlowError("{param} repeats a channel; list each channel only once", "channels")


def check_cofactor(cofactor) -> None:
    """Refuses a Transform stage cofactor that isn't "auto", spelt so, or a finite number from 0,
    naming cofactor. The rule is kept here alone: ClusterSettings.check runs it, resolve_cofactor
    before it tallies a cell, and live cells' channel_histograms on the cofactor it is given."""
    if isinstance(cofactor, str) and cofactor == FLOW_COFACTOR_AUTO:
        return
    if not (_finite(cofactor) and cofactor >= 0):
        takes = f"{FLOW_COFACTOR_AUTO}, 0 (linear) or a positive number"
        raise _refused("cofactor", cofactor, takes)


def check_groups(groups: Sequence[str]) -> None:
    """Refuses a group name that is empty or isn't 1 to 40 letters, digits, spaces and _ . + -
    starting with a letter or digit, naming groups."""
    for name in groups:
        if not isinstance(name, str) or not name.strip():
            raise FlowError("{param} has an empty name", "groups")
        if not GROUP_NAME.fullmatch(name):
            raise FlowError(
                f"{{param}} has {name!r}; a name takes 1 to 40 letters, digits, spaces and "
                "_ . + -, starting with a letter or digit",
                "groups",
            )


class _Settings:
    """to_dict and from_dict for the settings dataclasses."""

    def to_dict(self) -> dict[str, object]:
        """The settings as JSON writes them, tuples as lists."""
        return {k: list(v) if isinstance(v, tuple) else v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Self:
        """The settings to_dict gave, lists back as tuples. A key that isn't a setting is refused,
        so a record from another version isn't read as if it held the same settings."""
        names = {f.name for f in fields(cls)}
        for key in data:
            if key not in names:
                kind = cls.__name__.removesuffix("Settings").lower()
                raise FlowError(f"{{param}} isn't a {kind} setting", key)
        return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in data.items()})


@dataclass(frozen=True, kw_only=True)
class GateSettings(_Settings):
    """The gate finder's settings: the scatter channels it gates on, disc, the area rule
    (reference for cfc.py's mirrored_area, the reference code's gates; peak for find_area, the
    disc on the peak), and lymphmacro_finder's thresholds and window. t11 and t21, the first
    peak's, give one value for every file or one per file, as cfc.py's per-file values do. disc
    his, the reference rule's old name, is read as reference, so older gate records still load."""

    fsc: str = FLOW_FSC
    ssc: str = FLOW_SSC
    disc: str = FLOW_DISC
    t11: tuple[float, ...] = (FINDER_T11,)
    t21: tuple[float, ...] = (FINDER_T21,)
    t12: float = FINDER_T12
    t22: float = FINDER_T22
    n_row: int = FINDER_N_ROW
    n_col: int = FINDER_N_COL

    def __post_init__(self):
        if isinstance(self.disc, str):  # JSON may hand over a list, which check() refuses
            object.__setattr__(self, "disc", DISC_ALIASES.get(self.disc, self.disc))

    def check(self, n_files: int | None = None) -> Self:
        """self, when the finder takes every value. With n_files, t11 and t21 must also give one
        value, or one per file."""
        if self.disc not in AREAS:
            raise FlowError(f"{{param}} is {self.disc!r}; it takes {' or '.join(AREAS)}", "disc")
        for name in ("t11", "t21"):
            got = len(getattr(self, name))
            if not got:
                raise FlowError("{param} gives no values; give one, or one per file", name)
            if n_files is not None and got not in (1, n_files):
                raise FlowError(
                    f"{{param}} gives {got} values for {n_files} files; give one, or one per file",
                    name,
                )
        for name, values in (("t11", self.t11), ("t12", (self.t12,))):
            for v in values:
                if not (_finite(v) and v > 0):
                    raise _refused(name, v, "a positive distance in grid cells")
        for name, values in (("t21", self.t21), ("t22", (self.t22,))):
            for v in values:
                if not (_finite(v) and v >= 0):
                    raise _refused(name, v, "a fraction of the peak's density, 0 or more")
        for name in ("n_row", "n_col"):
            if not _whole(getattr(self, name), 1, MSIZE):
                raise _refused(name, getattr(self, name), f"1 to {MSIZE} grid cells")
        return self

    def for_file(self, index: int) -> dict[str, object]:
        """gate_peaks' keyword arguments for the file at index, counting from 0: its own t11 and
        t21, or the ones every file shares, and disc's area rule."""
        return {
            "n_row": self.n_row,
            "n_col": self.n_col,
            "t11": self.t11[index if len(self.t11) > 1 else 0],
            "t21": self.t21[index if len(self.t21) > 1 else 0],
            "t12": self.t12,
            "t22": self.t22,
            "area": AREAS[self.disc],
        }


@dataclass(frozen=True, kw_only=True)
class ClusterSettings(_Settings):
    """The clustering stage's settings: the channels to cluster (None for every -A channel but
    FSC and SSC, less exclude_channels), the Transform stage, arcsinh(x / cofactor) of them (0
    keeps them linear; a number applies to every channel; "auto", the default, is the cofactors
    pipeline.resolve_cofactor picks, one per channel, from the raw values of the cells the run
    clusters when the stage runs, and is kept as asked; the steps after it take those as a tuple),
    the Scale stage (standardize: each channel centred and scaled to SD 1 by the mean and SD
    pooled over every clustered file's kept cells), create_dn's dn_num1, dn_num2
    per file, center_method, seed and n_jobs, draws (create_dn's draws from seed: "r", the
    default, R's set.seed(seed) draws, so each file's nuggets are create.DN's; "numpy", the int
    seed's own, which every run made before draws existed used), the clustering of the pooled
    nuggets into k clusters (method: "wkmeans", weighted k-means with num_init starts of up to
    max_iter rounds, always on R's set.seed(seed) draws, so it matches WCluster's Wkmeans on the
    pooled Weight > 0 nuggets; or "tree", the hierarchical tree, Whclust cut into k), and whether
    a t-SNE of the nuggets is drawn, with its perplexity and seed. row_filters are
    filters.parse_filter specs on $PnN channels' raw (untransformed) values, ANDed with the
    populations kept; groups names one group per gated file, in file order, for the comparison
    tables; cells_per_file is how many of each file's kept cells cells.csv samples (0: none). A
    record written before standardize existed loads with it on, its default. One written before
    method existed ran the tree on mean centers, and one written before draws existed built its
    nuggets on numpy's draws, and each loads so (from_dict)."""

    channels: tuple[str, ...] | None = None
    exclude_channels: tuple[str, ...] = ()
    cofactor: float | str = FLOW_COFACTOR
    standardize: bool = FLOW_STANDARDIZE
    dn_num1: int = DN_NUM1
    dn_num2: int = FLOW_DN_NUM2
    center_method: str = FLOW_CENTER_METHOD
    seed: int = SEED
    draws: str = FLOW_DRAWS
    n_jobs: int = FLOW_N_JOBS
    k: int = FLOW_K
    method: str = FLOW_METHOD
    num_init: int = FLOW_NUM_INIT
    max_iter: int = FLOW_MAX_ITER
    tsne: bool = True
    tsne_perplexity: float = TSNE_PERPLEXITY
    tsne_seed: int = TSNE_SEED
    row_filters: tuple[str, ...] = ()
    groups: tuple[str, ...] | None = None
    cells_per_file: int = FLOW_CELLS_PER_FILE

    def check(self) -> Self:
        """self, when create_dn, the clustering and the t-SNE take every value. The default
        channels are checked once a file's channels are known."""
        if not _whole(self.k, 1):
            raise _refused("k", self.k, "1 or more clusters")
        if self.method not in FLOW_METHODS:
            raise _refused("method", repr(self.method), " or ".join(FLOW_METHODS))
        if self.center_method not in CENTER_METHODS:
            raise _refused("center_method", repr(self.center_method), ", ".join(CENTER_METHODS))
        if self.draws not in DRAWS:
            raise _refused("draws", repr(self.draws), " or ".join(DRAWS))
        for name in ("num_init", "max_iter"):
            if not _whole(getattr(self, name), 1):
                raise _refused(name, getattr(self, name), "a whole number from 1")
        if not _whole(self.dn_num1, 3):  # room for dn_num2 of 2 below it
            raise _refused("dn_num1", self.dn_num1, "3 or more nuggets")
        if not _whole(self.dn_num2, 2, self.dn_num1 - 1):
            raise _refused("dn_num2", self.dn_num2, f"2 to {self.dn_num1 - 1} nuggets per file")
        check_cofactor(self.cofactor)
        if not isinstance(self.standardize, bool):
            raise _refused("standardize", self.standardize, "true or false")
        # weighted k-means draws RDraws(seed) whatever draws says, so seed is R's set.seed range
        if not _whole(self.seed, 0, SEED_MAX):
            raise _refused(
                "seed", self.seed, f"a whole number from 0 to {SEED_MAX}, R's largest seed"
            )
        if not _whole(self.tsne_seed, 0):
            raise _refused("tsne_seed", self.tsne_seed, "a whole number from 0")
        try:
            check_n_jobs(self.n_jobs)
        except ValueError:
            raise _refused("n_jobs", self.n_jobs, "-1 (every core) or 1 or more") from None
        if self.channels is not None:
            check_channels(self.channels)
            if self.exclude_channels:
                raise FlowError("{param} can't be combined with channels", "exclude_channels")
        if not (_finite(self.tsne_perplexity) and self.tsne_perplexity > 0):
            raise _refused("tsne_perplexity", self.tsne_perplexity, "a positive number")
        self.filters()
        if self.groups is not None:
            check_groups(self.groups)
        if not _whole(self.cells_per_file, 0):
            raise _refused("cells_per_file", self.cells_per_file, "a whole number from 0")
        return self

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Self:
        """_Settings.from_dict, but a record without method predates it: that run clustered with
        the tree on mean centers, so it loads as method "tree" and center_method "mean" (unless it
        names one), not as today's defaults. A record without draws, whatever its method,
        predates draws too: its nuggets were built on numpy's draws, so it loads as draws
        "numpy" and builds the nuggets it built then."""
        if "method" not in data:
            data = {"center_method": FLOW_LEGACY_CENTER_METHOD, **data}
            data["method"] = FLOW_LEGACY_METHOD
        if "draws" not in data:
            data = {**data, "draws": FLOW_LEGACY_DRAWS}
        return super().from_dict(data)

    def filters(self) -> list:
        """row_filters as filters.RowFilter, a spec that doesn't read refused naming
        row_filters."""
        found = []
        for spec in self.row_filters:
            try:
                found.append(parse_filter(spec))
            except ValueError as e:
                raise FlowError(f"{{param}}: {e}", "row_filters") from None
        return found
