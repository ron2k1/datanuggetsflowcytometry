"""The gate step: each file read and gated with Cabrera's finder, and its populations
counted and described, a line each."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from datanuggets_flow._pipeline.fcs import read_fcs
from datanuggets_flow._pipeline.records import OnEvent, PopStats, Reader, Sample, StageEvent
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.gate import gate_peaks

if TYPE_CHECKING:
    from datanuggets_flow.settings import GateSettings


def population_stats(fsc, ssc, masks, peaks) -> list[PopStats]:
    """Each population's PopStats, from the file's scatter channels, its masks and the grid cell
    each population grows from (FinderPeaks.peaks, one row per mask column)."""
    return [
        PopStats(
            j + 1,
            int(m.sum()),
            100 * float(m.mean()),
            float(np.median(fsc[m])) if m.any() else 0.0,
            float(np.median(ssc[m])) if m.any() else 0.0,
            (int(peaks[j][0]), int(peaks[j][1])),
        )
        for j, m in enumerate(np.asarray(masks, dtype=bool).T)
    ]


def population_table(stats: Sequence[PopStats], fsc_name: str, ssc_name: str) -> list[str]:
    """The line the CLI prints for each population, with its scatter channels' names."""
    return [
        f"  Pop {p.pop}: {p.events:>9,} events ({p.percent:4.1f}%), median {fsc_name} "
        f"{p.median_fsc:>9,.0f}, {ssc_name} {p.median_ssc:>9,.0f}"
        for p in stats
    ]


def gate_files(
    paths: Sequence[Path],
    settings: GateSettings,
    *,
    read: Reader = read_fcs,
    on_event: OnEvent | None = None,
) -> list[Sample]:
    """Each file read and gated on settings.fsc against settings.ssc with Cabrera's finder, its
    populations counted, in the order given. A "gate" event per file carries its lines. The
    settings are checked against the number of files before any is read, since a backend calls
    this without the CLI's checks, and a file without either scatter channel stops the run before
    it is gated."""
    if not paths:
        raise FlowError("no files to gate")
    settings.check(len(paths))
    samples = []
    for i, path in enumerate(map(Path, paths)):
        events, pnn, pns = read(path)
        for param, channel in (("fsc", settings.fsc), ("ssc", settings.ssc)):
            if channel not in pnn:
                raise FlowError(
                    f"{path.name} has no channel {channel}; its channels: {', '.join(pnn)}", param
                )
        # copies, so the events can be freed while gates.png waits for them
        fsc = events[:, pnn.index(settings.fsc)].copy()
        ssc = events[:, pnn.index(settings.ssc)].copy()
        finder = settings.for_file(i)
        masks, peaks = gate_peaks(fsc, ssc, **finder)
        stats = population_stats(fsc, ssc, masks, peaks.peaks)
        table = population_table(stats, settings.fsc, settings.ssc)
        samples.append(
            Sample(
                number=i + 1,
                path=path,
                n_events=len(fsc),
                pnn=pnn,
                pns=pns,
                masks=masks,
                peaks=peaks,
                stats=stats,
                table=table,
                local_maxima=len(peaks.candidates),
                t11=finder["t11"],
                t21=finder["t21"],
                fsc=fsc,
                ssc=ssc,
            )
        )
        if on_event:
            lines = [
                f"\nFile {i + 1}, {path.name}: {len(fsc):,} events",
                "\n".join(table),
                f"  {len(peaks.candidates)} local maxima, {len(peaks.peaks)} kept as peaks",
            ]
            data = {"events": len(fsc), "local_maxima": len(peaks.candidates), "populations": stats}
            on_event(StageEvent("gate", i + 1, len(paths), "\n".join(lines), data))
    return samples
