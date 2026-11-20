"""The gate step: each file read and gated with Cabrera's finder, and its populations
counted and described, a line each."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from datanuggets_flow._defaults import (
    FLOW_CHANNEL_SUFFIX,
    FLOW_OFFSCALE_MAX,
    FLOW_SCATTER_PREFIXES,
)
from datanuggets_flow._pipeline.clustering import default_channels
from datanuggets_flow._pipeline.fcs import read_fcs, read_ranges
from datanuggets_flow._pipeline.records import (
    OnEvent,
    PopStats,
    RangesReader,
    Reader,
    Sample,
    StageEvent,
)
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.gate import gate_peaks

if TYPE_CHECKING:
    from datanuggets_flow.settings import GateSettings


def gate_channels(
    pnn: Sequence[str], fsc: str | None = None, ssc: str | None = None
) -> tuple[str | None, str | None]:
    """The gate's two channels for a file with channels pnn, fsc and ssc where given. One not
    given is the file's forward scatter for fsc, side scatter for ssc: its first channel named
    so (FLOW_SCATTER_PREFIXES) ending in -A, else its first named so, else the first of its
    default_channels, as on a mass cytometer, which records no scatter. Never the other's channel;
    None when the file has no channel left."""

    def pick(prefix: str, other: str | None) -> str | None:
        named = [c for c in pnn if c.startswith(prefix) and c != other]
        areas = [c for c in named if c.endswith(FLOW_CHANNEL_SUFFIX)]
        rest = [c for c in default_channels(pnn) if c != other]
        return next(iter(areas + named + rest), None)

    fsc = fsc or pick(FLOW_SCATTER_PREFIXES[0], ssc)
    return fsc, ssc or pick(FLOW_SCATTER_PREFIXES[1], fsc)


def on_channels(settings: GateSettings, pnn: Sequence[str]) -> GateSettings:
    """settings with fsc and ssc that aren't set taken from channels pnn by gate_channels. The
    gate step settles them on its first file; a caller that draws or records its samples settles
    them the same way, on the first sample's channels."""
    fsc, ssc = gate_channels(pnn, settings.fsc, settings.ssc)
    return replace(settings, fsc=fsc, ssc=ssc)


def gate_notes(stats: Sequence[PopStats], kept: int, disc: str) -> list[str]:
    """A line under a file's populations when one is empty under the reference area rule, which
    can draw a peak's area where there are no events, or when no peak was kept."""
    if not kept:
        return [
            (
                "  No peak was kept, so this file has no populations: a few events far beyond the "
                "rest can squeeze the others into the grid's edge, where no peak is kept"
            )
        ]
    empty = [f"Pop {p.pop}" for p in stats if not p.events]
    if empty and disc == "reference":
        return [
            (
                f"  {', '.join(empty)} {'holds' if len(empty) == 1 else 'hold'} no events: the "
                "reference area rule draws each area about the peak mirrored across the diagonal, "
                "the peak-centred rule (disc peak) about the peak"
            )
        ]
    return []


def on_scale(scatter, channels, ranges) -> np.ndarray | None:
    """The events inside each gate channel's range ($PnR; ranges is read_ranges' channels and one
    range or None for each), or None to gate every event: when none is past it, or when more than
    FLOW_OFFSCALE_MAX of them are, since then the range doesn't describe the values."""
    inside = np.ones(len(scatter[0]), dtype=bool)
    names, tops = ranges
    for values, channel in zip(scatter, channels):
        # the first channel of the name, as the gate reads (pnn.index)
        top = tops[names.index(channel)] if channel in names else None
        if top is not None:
            inside &= values <= top
    past = len(inside) - int(inside.sum())
    return inside if 0 < past <= FLOW_OFFSCALE_MAX * len(inside) else None


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
    ranges: RangesReader | None = None,
    on_event: OnEvent | None = None,
) -> list[Sample]:
    """Each file read and gated on settings.fsc against settings.ssc with Cabrera's finder, its
    populations counted, in the order given. fsc and ssc not set are settled on the first file's
    channels (on_channels). A "gate" event per file carries its lines. The settings are checked
    against the number of files before any is read, since a backend calls this without the CLI's
    checks, and a file without either channel, or with NaN or an infinite value in one, stops the
    run before it is gated. ranges gives each file's channel ranges for on_scale; it defaults to
    read_ranges when read is read_fcs, and to none for a stand-in reader with no file behind it."""
    if not paths:
        raise FlowError("no files to gate")
    settings.check(len(paths))
    if ranges is None and read is read_fcs:
        ranges = read_ranges
    samples = []
    for i, path in enumerate(map(Path, paths)):
        events, pnn, pns = read(path)
        if not i:
            settings = on_channels(settings, pnn)
        scatter = []
        for param, channel in (("fsc", settings.fsc), ("ssc", settings.ssc)):
            if channel not in pnn:
                lacks = f"no channel {channel}" if channel else "no channel left to gate on"
                raise FlowError(
                    f"{path.name} has {lacks}; its channels: {', '.join(pnn)}; set {{param}} to "
                    "one",
                    param,
                )
            # a copy, so the events can be freed while gates.png waits for it
            scatter.append(events[:, pnn.index(channel)].copy())
            if not np.isfinite(scatter[-1]).all():
                raise FlowError(
                    f"{path.name}'s {channel} holds values that aren't numbers (NaN or infinite); "
                    "set {param} to another channel",
                    param,
                )
        fsc, ssc = scatter
        finder = settings.for_file(i)
        channels = (settings.fsc, settings.ssc)
        inside = on_scale(scatter, channels, ranges(path)) if ranges else None
        if inside is None:
            masks, peaks = gate_peaks(fsc, ssc, **finder)
        else:
            found, peaks = gate_peaks(fsc[inside], ssc[inside], **finder)
            masks = np.zeros((len(fsc), found.shape[1]), dtype=bool)
            masks[inside] = found
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
                *gate_notes(stats, len(peaks.peaks), settings.disc),
            ]
            if inside is not None:
                lines.append(
                    f"  {len(fsc) - int(inside.sum()):,} events past the range of {channels[0]} "
                    f"or {channels[1]} are left out of every population"
                )
            data = {"events": len(fsc), "local_maxima": len(peaks.candidates), "populations": stats}
            on_event(StageEvent("gate", i + 1, len(paths), "\n".join(lines), data))
    return samples
