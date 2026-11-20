"""The live-cells step a front end runs between the population choice and the clustering: the
kept cells' values on a viability dye and on CD45, so the user can keep the live white cells by
thresholds they place themselves. Nothing here suggests a threshold. suggest_channels names the
channels that look like a viability dye or CD45, from their names alone; kept_values reads the
cells the chosen populations keep, exactly the ones cluster_stage hands its row filters, raw;
channel_histograms bins them on one arcsinh scale per channel shared by every file, by default
with each channel's cofactor as a run on the same cells would pick it; and count_kept counts the
cells a set of row filters keeps in each file, as cluster_stage counts them. The thresholds go to
the run as ClusterSettings.row_filters on the raw values, and the viability channel as
exclude_channels. save_kept_values and load_kept_values keep the values between requests, so a
count needs no FCS file read."""

from __future__ import annotations

import json
import numbers
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np
from datanuggets.filters import RowFilter, filter_mask, format_filter, parse_filter

from datanuggets_flow._defaults import (
    FLOW_CHANNEL_SUFFIX,
    FLOW_COFACTOR,
    FLOW_COFACTOR_WIDE,
    LIVECELLS_BINS,
    LIVECELLS_FLAT_WIDTH,
    LIVECELLS_RANGE_PAD,
    LIVECELLS_RANGE_QUANTILES,
    LIVECELLS_SCHEMA,
)
from datanuggets_flow._pipeline.clustering import MIN_KEPT_EVENTS, _kept_cells
from datanuggets_flow._pipeline.cofactor import NegativeTally, auto_cofactor
from datanuggets_flow._pipeline.fcs import read_fcs
from datanuggets_flow._pipeline.records import Cofactor, Reader
from datanuggets_flow._pipeline.selection import pick_events
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.settings import check_cofactor

# the step's display defaults (LIVECELLS_* in _defaults, none of them a threshold) stay
# importable from here too, as datanuggets_flow.livecells.LIVECELLS_BINS and so on

ROLES = ("viability", "cd45")
# a name holding one of these, in any case, reads as a viability dye: Zombie dyes, LIVE/DEAD,
# LIVE DEAD and LiveDead, Viability (Fixable Viability Dye), BD's FVS stains, 7-AAD, DAPI,
# propidium iodide, and PI as a word of its own
VIABILITY_NAME = re.compile(
    r"zombie"
    r"|live\s*[/_-]?\s*dead"
    r"|viability"
    r"|(?<![a-z0-9])fvs"
    r"|(?<![a-z0-9])7[\s_-]?aad(?![a-z0-9])"
    r"|(?<![a-z0-9])dapi(?![a-z0-9])"
    r"|propidium[\s_-]*iodide"
    r"|(?<![a-z0-9])pi(?![a-z0-9])",
    re.IGNORECASE,
)
# CD45 as a word of its own, so CD45RA, CD45RO, CD45R and CD450 don't read as it, and not followed
# by an isoform written apart (CD45-RA, CD45 RA, CD45_RO, CD45.RA, CD45/RA, CD45 R, CD45 RABC);
# CD45.1, CD45.2 and CD45 with a fluorochrome, such as CD45 PerCP, still do
CD45_NAME = re.compile(
    r"(?<![a-z0-9])cd45(?![a-z0-9])(?![\s_./-]*r[abco]*(?![a-z0-9]))", re.IGNORECASE
)
_NAMES = {"viability": VIABILITY_NAME, "cd45": CD45_NAME}


def suggest_channels(pnn: Sequence[str], pns: Sequence[str] | None = None) -> dict[str, object]:
    """The channel that looks like a viability dye and the one that looks like CD45, each by its
    $PnN, or None: {"viability": name | None, "cd45": name | None, "candidates": {"viability":
    [names], "cd45": [names]}}. A channel is a candidate when its $PnN or its $PnS matches,
    ignoring case. A role's suggestion is its one candidate; with several, the one whose $PnN ends
    in -A, the area channel the clustering takes, when exactly one does; otherwise None, with the
    candidates listed, since the package never picks between them. It reads names only, never
    values."""
    names = [str(n) for n in pnn]
    labels = [str(s) for s in pns] if pns is not None else [""] * len(names)
    if len(labels) != len(names):
        raise ValueError(f"pns gives {len(labels)} labels for {len(names)} channels")
    candidates = {
        role: [n for n, s in zip(names, labels) if pattern.search(n) or pattern.search(s)]
        for role, pattern in _NAMES.items()
    }
    found: dict[str, object] = {}
    for role, hits in candidates.items():
        area = [n for n in hits if n.endswith(FLOW_CHANNEL_SUFFIX)]
        found[role] = hits[0] if len(hits) == 1 else area[0] if len(area) == 1 else None
    return found | {"candidates": candidates}


class FileValues(NamedTuple):
    """One gated file's kept cells: its number (from 1, in gate order) and name, its events, the
    populations kept, and the kept cells' raw values, one row per cell in event order and one
    column per channel, (0, channels) for a file left out."""

    number: int
    name: str
    events: int
    pops: tuple[int, ...]
    values: np.ndarray

    @property
    def kept(self) -> int:
        return len(self.values)


class KeptValues(NamedTuple):
    """kept_values' result: the channels read, by $PnN, their labels ($PnS with the $PnN, or the
    $PnN alone), every gated file's FileValues, in gate order, and the auto cofactor of these
    values, one per channel, the ones a run clustering the same cells on these channels would use
    by default (one number, picked from the files' headers, for values saved under that earlier
    rule; None for values saved before a cofactor was recorded)."""

    channels: tuple[str, ...]
    labels: tuple[str, ...]
    files: tuple[FileValues, ...]
    cofactor: Cofactor | None = None


def _whole(v, low: int) -> bool:
    return isinstance(v, numbers.Integral) and not isinstance(v, bool) and v >= low


def _label(samples: Sequence[Mapping], channel: str) -> str:
    """channel's label in the first sample that has it, as resolve_channels writes labels."""
    for s in samples:
        if channel in s["pnn"]:
            label = s["pns"][list(s["pnn"]).index(channel)]
            return f"{label} ({channel})" if label else channel
    return channel


def kept_values(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    channels: Sequence[str],
    *,
    read: Reader = read_fcs,
) -> KeptValues:
    """The raw values on channels of the cells the populations chosen for each sample keep
    (numbered from 1, [] leaving a file out): the cells cluster_stage hands its row filters, read
    by the same step, which refuses a file that isn't the one gated. samples are gate_stage's, or
    state.load_gates(folder).samples. A file keeping no cells isn't read. The values' auto
    cofactor, which channel_histograms draws on by default, is auto_cofactor of a NegativeTally of
    them, in the files keeping MIN_KEPT_EVENTS or more, as a run with no row filters tallies them.
    FlowError names channels for a channel that is empty, repeated or missing from a file that
    keeps cells, and pops for a choice per sample that is missing, names a population the file
    doesn't have, or keeps no cells anywhere."""
    channels = tuple(channels)
    if not channels:
        raise FlowError("{param} names no channel; choose one or more", "channels")
    if len(set(channels)) != len(channels):
        raise FlowError("{param} repeats a channel; list each channel only once", "channels")
    if not samples:
        raise FlowError("no gated files to read")
    if len(chosen) != len(samples):
        raise FlowError(
            f"{{param}} gives {len(chosen)} choices for {len(samples)} files; give one per file",
            "pops",
        )
    pops_of = []
    for s, pops in zip(samples, chosen):
        n = np.shape(s["masks"])[1]
        bad = [p for p in pops if not (_whole(p, 1) and p <= n)]
        if bad:
            raise FlowError(
                f"{{param}}: {s['path'].name} has Pop 1 to Pop {n}; there is no Pop {bad[0]}",
                "pops",
            )
        pops_of.append(tuple(sorted({int(p) for p in pops})))
    keeps = [pick_events(s["masks"], pops) for s, pops in zip(samples, pops_of)]
    if not any(keep.any() for keep in keeps):
        raise FlowError("{param} keeps no cells in any file", "pops")
    for s, keep in zip(samples, keeps):
        missing = [c for c in channels if c not in s["pnn"]]
        if keep.any() and missing:
            raise FlowError(
                f"{{param}} names {missing[0]}, which {s['path'].name} doesn't have; its "
                f"channels: {', '.join(s['pnn'])}",
                "channels",
            )
    files, tally = [], NegativeTally(len(channels))
    for i, (s, pops, keep) in enumerate(zip(samples, pops_of, keeps)):
        rows = np.flatnonzero(keep)
        if len(rows):
            x, _ = _kept_cells(s, rows, channels, 0, read)  # cofactor 0: the values as read
        else:
            x = np.empty((0, len(channels)))
        if len(x) >= MIN_KEPT_EVENTS:  # a file the run leaves out counts for nothing
            tally.add(x)
        files.append(FileValues(i + 1, Path(s["path"]).name, int(s["n_events"]), pops, x))
    labels = tuple(_label(samples, c) for c in channels)
    return KeptValues(channels, labels, tuple(files), auto_cofactor(tally))


def save_kept_values(kept: KeptValues, path) -> Path:
    """kept as one .npz file at path, written as given, with no extension added: a JSON record
    of the channels, the files and the auto cofactor, and each file's values, stored as float32
    where that keeps every value exactly and as float64 otherwise, so load_kept_values gives back
    the same numbers."""
    record = {
        "schema": LIVECELLS_SCHEMA,
        "channels": list(kept.channels),
        "labels": list(kept.labels),
        "cofactor": kept.cofactor._asdict() if kept.cofactor is not None else None,
        "files": [
            {"number": f.number, "name": f.name, "events": f.events, "pops": list(f.pops)}
            for f in kept.files
        ],
    }
    arrays = {"record": np.array(json.dumps(record))}
    for f in kept.files:
        small = f.values.astype(np.float32)
        same = np.array_equal(small.astype(np.float64), f.values, equal_nan=True)
        arrays[f"values_{f.number}"] = small if same else f.values
    path = Path(path)
    with path.open("wb") as handle:
        np.savez(handle, **arrays)
    return path


def load_kept_values(path) -> KeptValues:
    """The KeptValues save_kept_values wrote at path, values as float64. A file that isn't one
    raises ValueError. One saved under the header rule loads its one cofactor as it was saved;
    one saved before the cofactor was recorded, with the same schema, loads with cofactor None,
    and channel_histograms then draws on 6000, the default it was drawn on."""
    with np.load(Path(path), allow_pickle=False) as arrays:
        try:
            record = json.loads(str(arrays["record"]))
        except (KeyError, ValueError):
            raise ValueError(f"{Path(path).name} isn't a {LIVECELLS_SCHEMA} file") from None
        if not isinstance(record, dict) or record.get("schema") != LIVECELLS_SCHEMA:
            raise ValueError(f"{Path(path).name} isn't a {LIVECELLS_SCHEMA} file")
        channels = tuple(record["channels"])
        files = []
        for entry in record["files"]:
            key = f"values_{entry['number']}"
            if key not in arrays.files:
                raise ValueError(f"{Path(path).name} has no {key}")
            values = arrays[key].astype(np.float64)
            if values.ndim != 2 or values.shape[1] != len(channels):
                raise ValueError(f"{Path(path).name}'s {key} doesn't hold {len(channels)} columns")
            files.append(
                FileValues(
                    int(entry["number"]),
                    str(entry["name"]),
                    int(entry["events"]),
                    tuple(int(p) for p in entry["pops"]),
                    values,
                )
            )
    picked = record.get("cofactor")
    cofactor = None
    if picked is not None:  # JSON gives the per-channel fields back as lists
        cofactor = Cofactor(
            **{k: tuple(v) if isinstance(v, list) else v for k, v in picked.items()}
        )
    return KeptValues(channels, tuple(record["labels"]), tuple(files), cofactor)


def _scaled(x: np.ndarray, cofactor: float) -> np.ndarray:
    return np.arcsinh(x / cofactor) if cofactor else x


def _shared_range(t: np.ndarray) -> tuple[float, float]:
    """The pooled range a channel's bins span: its LIVECELLS_RANGE_QUANTILES widened by
    LIVECELLS_RANGE_PAD of their width on each side, but not past the smallest and largest
    value, from the finite values t. One value alone is opened to LIVECELLS_FLAT_WIDTH."""
    q_lo, q_hi = (float(q) for q in np.quantile(t, LIVECELLS_RANGE_QUANTILES))
    pad = LIVECELLS_RANGE_PAD * (q_hi - q_lo)
    lo, hi = max(q_lo - pad, float(t.min())), min(q_hi + pad, float(t.max()))
    if not hi > lo:
        lo, hi = lo - LIVECELLS_FLAT_WIDTH / 2, lo + LIVECELLS_FLAT_WIDTH / 2
    return lo, hi


def _binned(t: np.ndarray, bins: int, lo: float, hi: float) -> dict[str, object]:
    """t's counts in bins equal bins from lo to hi, both ends kept, and its cells below lo, above
    hi and NaN, which the counts leave out. The four add up to len(t)."""
    nan = np.isnan(t)
    inside = (t >= lo) & (t <= hi)
    counts, _ = np.histogram(t[inside], bins=bins, range=(lo, hi))
    return {
        "counts": counts.astype(int).tolist(),
        "below": int((t < lo).sum()),
        "above": int((t > hi).sum()),
        "nan": int(nan.sum()),
    }


def channel_histograms(
    kept: KeptValues, *, bins: int = LIVECELLS_BINS, cofactor: float | str = FLOW_COFACTOR
) -> dict[str, object]:
    """Each channel's histogram of the kept cells on t = arcsinh(x / c), c that channel's
    cofactor, or on x itself with cofactor 0, with bin edges every file shares: the pooled counts,
    and each file's. cofactor "auto", the default, is kept.cofactor, the cofactors a run on the
    same cells would pick, one per channel (one number for values saved under the header rule,
    6000 for values saved before a cofactor was recorded); a number is used as given for every
    channel. The range comes from the pooled values (see _shared_range), and every cell outside it
    is counted in its file's below or above, a NaN in nan, so counts, below, above and nan add up
    to the file's kept cells. With a positive c_j a client turns channel j's t back into a raw
    value as c_j * sinh(t), the transform's inverse; with cofactor 0 the scale is linear and t is
    the raw value itself (0 * sinh(t) would give 0 there). The result is plain JSON values,
    "cofactor" first when one number serves every channel, and the per-channel keys after
    cofactor_from when each has its own:

        {"cofactor": float, "bins": int, "kept": int,
         "files": [{"number", "name", "events", "pops", "kept"}],
         "channels": [{"channel", "label", "lo", "hi", "edges", "counts", "below", "above", "nan",
                       "files": [{"number", "counts", "below", "above", "nan"}]}],
         "cofactor_from": "auto" | "set",
         "cofactors": [float], "negative_fraction": [float], "negative_sd": [float | None]}
    """
    if not _whole(bins, 1):
        raise FlowError(f"{{param}} is {bins}; it takes a whole number of bins, 1 or more", "bins")
    check_cofactor(cofactor)
    if not isinstance(cofactor, str):
        picked = Cofactor(float(cofactor), "set")
    elif kept.cofactor is not None:
        picked = kept.cofactor
    else:
        picked = Cofactor(FLOW_COFACTOR_WIDE, "auto")  # values saved before it was recorded
    c = picked.per_channel(len(kept.channels))
    out = []
    for j, (channel, label) in enumerate(zip(kept.channels, kept.labels)):
        scaled = [_scaled(f.values[:, j], float(c[j])) for f in kept.files]
        pooled = np.concatenate(scaled)
        finite = pooled[np.isfinite(pooled)]
        if not finite.size:
            raise FlowError(
                f"{{param}}: {channel} has no finite value in the kept cells", "channels"
            )
        lo, hi = _shared_range(finite)
        per_file = [_binned(t, bins, lo, hi) for t in scaled]
        pooled_counts = np.sum([p["counts"] for p in per_file], axis=0)
        out.append(
            {
                "channel": channel,
                "label": label,
                "lo": lo,
                "hi": hi,
                "edges": np.linspace(lo, hi, bins + 1).tolist(),
                "counts": pooled_counts.astype(int).tolist(),
                **{k: sum(p[k] for p in per_file) for k in ("below", "above", "nan")},
                "files": [{"number": f.number} | p for f, p in zip(kept.files, per_file)],
            }
        )
    hist = {} if picked.values is not None else {"cofactor": float(picked.value)}
    hist |= {
        "bins": int(bins),
        "kept": sum(f.kept for f in kept.files),
        "files": [
            {
                "number": f.number,
                "name": f.name,
                "events": f.events,
                "pops": list(f.pops),
                "kept": f.kept,
            }
            for f in kept.files
        ],
        "channels": out,
        "cofactor_from": picked.source,
    }
    if picked.values is not None:
        record = picked.transform()
        hist |= {k: record[k] for k in ("cofactors", "negative_fraction", "negative_sd")}
    return hist


def _row_filters(row_filters: Sequence[str | RowFilter]) -> list[RowFilter]:
    """Specs as RowFilters, a bad one refused naming row_filters."""
    found = []
    for f in row_filters:
        if isinstance(f, RowFilter):
            found.append(f)
            continue
        try:
            found.append(parse_filter(f))
        except ValueError as e:
            raise FlowError(f"{{param}}: {e}", "row_filters") from None
    return found


def count_kept(kept: KeptValues, row_filters: Sequence[str | RowFilter]) -> dict[str, object]:
    """How many of each file's kept cells pass every one of row_filters (specs or RowFilters) on
    their raw values, by filters.filter_mask, exactly as cluster_stage counts them in
    selection.csv's filtered; left_out is true for a file the run would leave out, one passing
    fewer than MIN_KEPT_EVENTS. No filters count every kept cell. A filter on a channel kept
    doesn't hold, or a cell that isn't a finite number under one, raises FlowError naming
    row_filters. The result is plain JSON values:

        {"row_filters": [canonical spec], "kept": int, "passed": int,
         "files": [{"number", "name", "events", "kept", "passed", "left_out"}]}
    """
    filters = _row_filters(row_filters)
    for f in filters:
        if f.column not in kept.channels:
            raise FlowError(
                f"{{param}} names {f.column}, which these values don't hold; they hold "
                f"{', '.join(kept.channels)}",
                "row_filters",
            )
    files = []
    for fv in kept.files:
        passed = fv.kept
        if filters and fv.kept:
            try:
                mask = filter_mask(
                    lambda c, v=fv.values: v[:, kept.channels.index(c)], filters, fv.kept
                )
            except ValueError as e:
                raise FlowError(f"{{param}} in {fv.name}: {e}", "row_filters") from None
            passed = int(mask.sum())
        files.append(
            {
                "number": fv.number,
                "name": fv.name,
                "events": fv.events,
                "kept": fv.kept,
                "passed": passed,
                "left_out": passed < MIN_KEPT_EVENTS,
            }
        )
    return {
        "row_filters": [format_filter(f) for f in filters],
        "kept": sum(f["kept"] for f in files),
        "passed": sum(f["passed"] for f in files),
        "files": files,
    }
