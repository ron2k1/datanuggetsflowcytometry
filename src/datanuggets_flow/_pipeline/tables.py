"""The run's tables: selection.csv's, and the nuggets, events, cluster summary and cluster
centers tables, with the CSV files they are written to. pandas loads only when a table is made."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from datanuggets import wmean

from datanuggets_flow._pipeline.records import Kept, Pool, Tables
from datanuggets_flow._pipeline.selection import pick_events

if TYPE_CHECKING:
    import pandas as pd


def selection_table(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    filtered: Mapping[int, int] | None = None,
) -> pd.DataFrame:
    """selection.csv: each file's number, name and populations kept, and its events, how many of
    them are kept and what percent. With filtered, the kept cells that pass the run's filters by
    file number, as make_nuggets counts them, it gains filtered and filtered_percent (of the
    events)."""
    import pandas as pd

    rows = []
    for i, (s, pops) in enumerate(zip(samples, chosen)):
        keep = pick_events(s["masks"], pops)
        rows.append(
            {
                "file_number": i + 1,
                "file": s["path"].name,
                "populations": ",".join(map(str, pops)) or "none",
                "events": len(keep),
                "kept": int(keep.sum()),
                "percent": 100 * keep.mean(),
            }
        )
        if filtered is not None:
            rows[-1]["filtered"] = filtered[i + 1]
            rows[-1]["filtered_percent"] = 100 * filtered[i + 1] / len(keep)
    return pd.DataFrame(rows)


def result_tables(kept: Sequence[Kept], pool: Pool, labels: Sequence[str]) -> Tables:
    """The run's tables. N is the file's number, as the prompt and selection.csv number it.
    Clusters are numbered from 1; event0 is the event's row in its file and nugget0 the nugget's
    row in nuggets_N.csv, both numbered from 0. The nugget and cluster centers are in the
    Transform stage's units, taken back from the Scale stage's by pool.values; a nugget's scale
    stays on the scale it was made on, the Scale stage's when it ran."""
    import pandas as pd

    labels = list(labels)
    nuggets, events, summary, start = {}, {}, [], 0
    for kp in kept:
        dn = kp.dn
        part = pool.cl[start : start + dn.n_nuggets]
        start += dn.n_nuggets
        nug = pd.DataFrame(pool.values(dn.centers), columns=labels)
        nug.insert(0, "nugget0", np.arange(dn.n_nuggets))
        nug["weight"], nug["scale"], nug["cluster"] = dn.weights, dn.scales, part + 1
        nuggets[kp.number] = nug
        ev = part[dn.assignments]
        events[kp.number] = pd.DataFrame(
            {"event0": kp.rows, "nugget0": dn.assignments, "cluster": ev + 1}
        )
        counts = np.bincount(ev, minlength=pool.k)
        summary += [
            {
                "file_number": kp.number,
                "file": kp.name,
                "cluster": c + 1,
                "cells": int(counts[c]),
                "percent": 100 * counts[c] / len(ev),
            }
            for c in range(pool.k)
        ]
    use = pool.use
    centers = pd.DataFrame(
        pool.values(wmean(pool.cell_means()[use], pool.cl[use], pool.weights[use])),
        columns=labels,
    )
    centers.insert(0, "cluster", np.arange(1, pool.k + 1))
    return Tables(nuggets, events, pd.DataFrame(summary), centers)


def write_tables(tables: Tables, out: Path) -> list[Path]:
    """nuggets_N.csv and events_N.csv for each kept file, then cluster_summary.csv and
    cluster_centers.csv, in the folder out; their paths, in that order."""
    named = []
    for num, nuggets in tables.nuggets.items():
        named += [(f"nuggets_{num}.csv", nuggets), (f"events_{num}.csv", tables.events[num])]
    named += [("cluster_summary.csv", tables.summary), ("cluster_centers.csv", tables.centers)]
    for name, table in named:
        table.to_csv(out / name, index=False)
    return [out / name for name, _ in named]
