"""The two stages a backend runs: gate_stage, the gate step with its figures and the gate
folder's record, and cluster_stage, every clustering step with its tables and figures. The
figures, the gate folder's record and the viewer's tables load only when a stage runs."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from datanuggets.projection import tsne_3d

from datanuggets_flow._defaults import (
    FLOW_COFACTOR_MIN_NEGATIVE,
    FLOW_GATE_DPI,
    FLOW_RESULT_DPI,
    FLOW_SKEW_WARN,
)
from datanuggets_flow._pipeline.clustering import (
    cluster_nuggets,
    finite_channels,
    make_nuggets,
    negative_tally,
    pooled_scaling,
    resolve_channels,
    tsne_embedding,
    warn_stain_differences,
)
from datanuggets_flow._pipeline.cofactor import resolve_cofactor
from datanuggets_flow._pipeline.fcs import read_fcs
from datanuggets_flow._pipeline.gating import gate_files, on_channels
from datanuggets_flow._pipeline.records import (
    Cofactor,
    OnEvent,
    RangesReader,
    Reader,
    RunResult,
    Sample,
    Scaling,
    StageEvent,
)
from datanuggets_flow._pipeline.tables import result_tables, selection_table, write_tables
from datanuggets_flow.exceptions import FlowError

if TYPE_CHECKING:
    from matplotlib.figure import Figure

    from datanuggets_flow.settings import ClusterSettings, GateSettings


def gate_stage(
    paths: Sequence[Path],
    out: Path,
    settings: GateSettings,
    *,
    read: Reader = read_fcs,
    ranges: RangesReader | None = None,
    on_event: OnEvent | None = None,
    figure: Callable[..., Figure] | None = None,
) -> list[Sample]:
    """The gate stage in the folder out, which must exist: each file gated by gate_files (read
    and ranges are its), local_maxima.png and gates.png drawn on figure (see flow.figures), and
    the gate folder's record saved by state.save_gates, gates.json last. cluster_stage clusters
    the samples it gives, or the ones state.load_gates reads back from out."""
    from datanuggets_flow.figures import gates_figure, local_maxima_figure, save_figures
    from datanuggets_flow.state import save_gates

    samples = gate_files(paths, settings, read=read, ranges=ranges, on_event=on_event)
    settings = on_channels(settings, samples[0]["pnn"])  # the channels gate_files settled on
    channels = (settings.fsc, settings.ssc)
    figs = {
        "local_maxima.png": local_maxima_figure(samples, channels=channels, figure=figure),
        "gates.png": gates_figure(samples, channels=channels, figure=figure),
    }
    save_figures(figs, out, FLOW_GATE_DPI)
    save_gates(out, samples, settings)
    return samples


def _transform_event(cofactor: Cofactor, labels: Sequence[str], n: int) -> StageEvent:
    """The Transform stage's lines, with the cofactor used and why, and its record: for auto, the
    rule and a line per channel with its cofactor, its share of cells below 0 and, where the rule
    took their spread, their SD."""
    transform = cofactor.transform()
    data = {"transform": transform}
    if transform["name"] != "arcsinh":
        line = "\nTransform: none; the channels are clustered as stored"
        return StageEvent("transform", None, n, line, data)
    if cofactor.values is None:
        c = f"{cofactor.value:g}"
        why = "as set" if cofactor.source != "auto" else "(auto)"
        line = f"\nTransform: arcsinh(x / {c}) of every clustered channel; cofactor {c} {why}"
        return StageEvent("transform", None, n, line, data)
    floor = f"{cofactor.value:g}"
    lines = [
        (
            "\nTransform: arcsinh(x / c) of every clustered channel, c per channel (auto: the SD "
            f"of the cells below 0 where at least {FLOW_COFACTOR_MIN_NEGATIVE:.0%} of the kept "
            f"cells are below 0, at least {floor}; else {floor})"
        )
    ]
    for label, c, f, sd in zip(labels, cofactor.values, cofactor.negative, cofactor.spread):
        spread = f", SD {sd:,.0f}" if sd is not None and f >= FLOW_COFACTOR_MIN_NEGATIVE else ""
        lines.append(f"  {label}: {c:,.0f}  ({100 * f:.1f}% below 0{spread})")
    return StageEvent("transform", None, n, "\n".join(lines), data)


def _scale_event(scaling: Scaling | None, labels: Sequence[str], n: int) -> StageEvent:
    """The Scale stage's lines, the pooled mean, SD and skewness of each channel, with a warning
    when a channel's skewness is beyond FLOW_SKEW_WARN either way, and its record."""
    if scaling is None:
        line = "Scale: none; the channels keep the transform's units"
        return StageEvent("scale", None, n, line, {"standardize": False})
    lines = [
        (
            "Scale: every channel to mean 0 and SD 1, pooled over "
            f"{scaling.files} files' {scaling.cells:,} cells"
        )
    ]
    lines += [
        f"  {label}: mean {m:.4g}, SD {sd:.4g}, skew {g:.3g}"
        for label, m, sd, g in zip(labels, scaling.mean, scaling.sd, scaling.skew)
    ]
    skewed = int((abs(scaling.skew) > FLOW_SKEW_WARN).sum())
    if skewed:
        lines += [
            (
                f"  Warning: {skewed} of {len(labels)} channels {'has' if skewed == 1 else 'have'} "
                f"skewness beyond {FLOW_SKEW_WARN:g} either way after the transform."
            ),
            (
                "  Their mean and SD follow the long tail, so most cells take a narrow band of each "
                "scaled axis; a smaller cofactor compresses the tail."
            ),
        ]
    return StageEvent("scale", None, n, "\n".join(lines), {"standardize": scaling.record()})


def cluster_stage(
    samples: Sequence[Mapping],
    chosen: Sequence[Sequence[int]],
    out: Path,
    settings: ClusterSettings,
    *,
    read: Reader = read_fcs,
    on_event: OnEvent | None = None,
    figure: Callable[..., Figure] | None = None,
) -> RunResult:
    """The clustering stage in the folder out, which must exist: the channels resolved (default
    ones less any holding NaN or an infinite value, by finite_channels, a pass over the raw
    values), selection.csv, the cofactor resolved once by resolve_cofactor before any arcsinh
    (settings.cofactor "auto" picks one per channel from negative_tally, a pass over the raw
    values of the cells the run clusters; a number is used as set for every channel, with no such
    pass) and given to every step after as Cofactor.applied, the Transform stage (arcsinh(x / c)
    with each channel's c, or none with cofactor 0), the Scale stage (unless settings.standardize
    is off: every channel centred and scaled to SD 1 by pooled_scaling's mean and SD), the kept
    cells' nuggets on those scaled values, their clustering (settings.method: weighted k-means,
    or the hierarchical tree), the tables, the t-SNE unless settings.tsne is off, the viewer's
    tables (flow.outputs.viewer_tables), and the figures, drawn on figure (see flow.figures).
    The tables give channel values in the transform's units.
    Events: "channels" per file read (with nothing to print) while the default channels are
    checked, "select" with selection.csv's table, "cofactor" per file read (nothing to print)
    while auto tallies, "transform" with what it does and the cofactor used and why, "scale" per
    file read (with nothing to print) while the Scale stage pools its stats, then "scale" with
    what it does, "nuggets" per kept file, "cluster" with each cluster's percent and the k used,
    "tsne" before the 2-D fit and again before the 3-D call (nothing to print; its data gives
    the nuggets and the dims, 2 then 3), and "figures" (nothing to print) once the viewer's
    tables are written, before the figures are drawn. A handler that raises stops the stage at
    that event. The result's cofactor is the Cofactor used, for state.write_run. With
    row_filters, selection.csv counts the cells that pass them, so it is written after the
    nuggets are made.
    The settings, that chosen gives one choice per sample and that groups names one group per
    sample are checked before anything is read or written: a backend calls this without the
    CLI's checks, and a short chosen would drop its missing files from the tables without a
    word."""
    settings.check()
    if not samples:
        raise FlowError("no gated files to cluster")
    if len(chosen) != len(samples):
        raise FlowError(
            f"{{param}} gives {len(chosen)} choices for {len(samples)} files; give one per file",
            "pops",
        )
    if settings.groups is not None and len(settings.groups) != len(samples):
        raise FlowError(
            f"{{param}} gives {len(settings.groups)} names for {len(samples)} files; give one per "
            "file",
            "groups",
        )
    channels, labels = resolve_channels(samples, settings)
    if settings.channels is None:  # the run chose them, so it leaves out what it can't cluster
        channels, labels = finite_channels(
            samples, chosen, channels, labels, settings, read=read, on_event=on_event
        )
    warn_stain_differences(samples, channels)
    selection = selection_table(samples, chosen)
    files = []
    if not settings.row_filters:
        selection.to_csv(out / "selection.csv", index=False)
        files.append(out / "selection.csv")
    emit = on_event or (lambda event: None)
    n = len(samples)
    table = "\n" + selection.to_string(index=False)
    emit(StageEvent("select", None, n, table, {"selection": selection}))

    def tally():
        return negative_tally(samples, chosen, channels, settings, read=read, on_event=emit)

    cofactor = resolve_cofactor(settings.cofactor, tally)
    settings = replace(settings, cofactor=cofactor.applied)  # every step after takes the numbers
    emit(_transform_event(cofactor, labels, n))
    scaling = None
    if settings.standardize:
        scaling = pooled_scaling(samples, chosen, channels, settings, read=read, on_event=emit)
    emit(_scale_event(scaling, labels, n))
    filtered, cells = {}, {}
    kept = make_nuggets(
        samples,
        chosen,
        channels,
        settings,
        read=read,
        on_event=on_event,
        filtered=filtered,
        cells=cells,
        scaling=scaling,
    )
    if settings.row_filters:
        selection = selection_table(samples, chosen, filtered)
        selection.to_csv(out / "selection.csv", index=False)
        files.append(out / "selection.csv")
    pool = cluster_nuggets(
        kept,
        settings.k,
        scaling,
        method=settings.method,
        num_init=settings.num_init,
        max_iter=settings.max_iter,
        seed=settings.seed,
        n_jobs=settings.n_jobs,
    )
    tables = result_tables(kept, pool, labels)
    files += write_tables(tables, out)
    percent = tables.summary.pivot(index="cluster", columns="file_number", values="percent")
    lines = [
        "\nPercent of each file's kept cells in each cluster:",
        "(columns are file numbers; selection.csv names the files)",
        percent.round(1).to_string(),
    ]
    emit(StageEvent("cluster", None, n, "\n".join(lines), {"percent": percent, "k": pool.k}))
    xy = xyz = None
    if settings.tsne:
        used = pool.centers[pool.use]
        emit(StageEvent("tsne", None, n, "", {"nuggets": len(used), "dims": 2}))
        xy = tsne_embedding(used, settings)
        emit(StageEvent("tsne", None, n, "", {"nuggets": len(used), "dims": 3}))
        xyz = tsne_3d(used, perplexity=settings.tsne_perplexity, seed=settings.tsne_seed)
    from datanuggets_flow.outputs import pool_colors, viewer_tables

    viewer = viewer_tables(
        samples, kept, pool, tables.summary, channels, labels, settings, xy, cells, tsne_xyz=xyz
    )
    for name, frame in viewer.items():
        frame.to_csv(out / name, index=False)
        files.append(out / name)
    from datanuggets_flow.figures import result_figures, save_figures

    emit(StageEvent("figures", None, n, "", {}))
    figs = result_figures(
        pool,
        tables.centers,
        labels,
        cofactor.applied,
        xy,
        figure=figure,
        colors=pool_colors(pool),
    )
    files += save_figures(figs, out, FLOW_RESULT_DPI)
    return RunResult(channels, labels, selection, kept, pool, tables, xy, files, cofactor)
