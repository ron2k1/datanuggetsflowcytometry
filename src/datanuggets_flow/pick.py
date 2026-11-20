"""Pick the cells to cluster from the gate figures, then cluster them: each FCS file is gated on
FSC-A against SSC-A with Cabrera's lymphmacro_finder, its numbered populations are shown and
counted, you choose which to keep (one, several, or all, file by file), and the kept events'
fluorescence channels go into data nuggets per file and weighted k-means (WCluster's Wkmeans, or
with --method tree the hierarchical tree) of all the files' nuggets together, so a cluster is the
same cells in every file.

    datanuggets-flow FOLDER                   asks which populations to keep in each file
    datanuggets-flow FOLDER --pops 1,2        keeps Pop 1 and Pop 2 of every file
    datanuggets-flow a.fcs b.fcs --pops "1,2;1"   Pop 1 and 2 of a.fcs, Pop 1 of b.fcs
    datanuggets-flow FOLDER --t11 22,20,18,18 --t21 0.25,0.5,0.5,0.5   cfc.py's thresholds
    datanuggets-flow FOLDER --gates-only --out GATES   gates and draws the files, then stops
    datanuggets-flow --from-gates GATES       asks over GATES' figures, then clusters

A folder's files go in name order, so per-file thresholds and --pops follow that order. The two
stages give the one-shot run's tables: --from-gates clusters with the masks GATES holds, reading
each file only once its size and SHA-256 are the ones it was gated with.

Events are read as stored, so a file with a real compensation matrix gets a warning; spectral
(Aurora) files are unmixed already.

The steps are datanuggets_flow.pipeline's, called through it. datanuggets_flow._pick.args
reads and checks the arguments, datanuggets_flow._pick.prompt asks which populations to keep, and
this module runs the steps in the mode the flags choose and prints their events and errors. Every
name this module had is still importable from here."""

from __future__ import annotations

import shutil
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from datanuggets import DataNuggetWarning

from datanuggets_flow import pipeline, state
from datanuggets_flow._defaults import FLOW_GATE_DPI, FLOW_RUN_NAME

# the flags' and the prompt's helpers, and pipeline's parse_pops and pick_events, are importable
# from here as before
from datanuggets_flow._pick.args import (
    _channel_names,
    _check_args,
    _fcs_paths,  # noqa: F401
    _flags,  # noqa: F401
    _given,  # noqa: F401
    _mode_rules,
    _out,
    _parser,
    _settings,
    groups_for,
    per_file,  # noqa: F401
)
from datanuggets_flow._pick.prompt import _ask, _choose_pops, _live_input  # noqa: F401
from datanuggets_flow.exceptions import FlowError
from datanuggets_flow.pipeline import parse_pops, pick_events  # noqa: F401
from datanuggets_flow.settings import ClusterSettings, cli_flag


def read_fcs(path) -> tuple[np.ndarray, list[str], list[str]]:
    """pipeline.read_fcs, its spillover warning printed as a line of the run's output. Every step
    reads through this name, so a test can stand in for the FCS reader."""
    with warnings.catch_warnings(record=True, action="always", category=DataNuggetWarning) as w:
        found = pipeline.read_fcs(path)
    for caught in w:
        if issubclass(caught.category, DataNuggetWarning):
            print(f"warning: {caught.message}")
        else:  # flowio's own, shown as they would have been
            warnings.warn_explicit(caught.message, caught.category, caught.filename, caught.lineno)
    return found


def _pyplot(no_show: bool, *, tables: bool, tsne: bool):
    """matplotlib's pyplot, once it is known to import, drawing off screen with --no-show. pandas
    is checked here too when the run makes tables, and scikit-learn when the t-SNE is drawn. All
    three are dependencies of the package, so one is missing only from a damaged install, and the
    run stops before any file is read."""
    try:
        import matplotlib

        if tables:
            import pandas  # noqa: F401
        if tsne:
            import sklearn  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "datanuggets-flow needs matplotlib, pandas and scikit-learn: "
            "pip install datanuggets-flow"
        ) from e
    if no_show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _print_event(event: pipeline.StageEvent) -> None:
    """A step's lines, as the run prints them; a progress event with no message prints
    nothing."""
    if event.message:
        print(event.message)


def _read(path):
    """read_fcs, looked up when called, so a test's stand-in for it is the reader the steps use."""
    return read_fcs(path)


# the line saying where each gate figure is, in the order they are drawn, the same in every mode
DRAWN = {
    "local_maxima.png": "\nThe local maxima and each Pop's peak are drawn in",
    "gates.png": "The populations are drawn in",
}


def _print_drawn(folder: Path, *names: str) -> None:
    """Where the gate figures names are in folder, a line each."""
    for name in names:
        print(f"{DRAWN[name]} {folder / name}")


def _gate_files(paths, settings, out, plt) -> list[dict]:
    """The one-shot run's gate step: each file gated by pipeline.gate_files, its populations
    printed as it goes, then the density grid, local maxima and the peak each Pop grows from
    drawn on one figure, local_maxima.png, the one the populations are chosen from. gates.png
    waits for the choice."""
    from datanuggets_flow.figures import local_maxima_figure, save_figures

    samples = pipeline.gate_files(paths, settings, read=_read, on_event=_print_event)
    figs = {"local_maxima.png": local_maxima_figure(samples, figure=plt.figure)}
    save_figures(figs, out, FLOW_GATE_DPI)
    _print_drawn(out, "local_maxima.png")
    return samples


def _draw_gates(samples, plt, out) -> None:
    """gates.png, once the populations are chosen: each file's events in gray and each of its
    populations in color, one panel per file."""
    from datanuggets_flow.figures import gates_figure, save_figures

    save_figures({"gates.png": gates_figure(samples, figure=plt.figure)}, out, FLOW_GATE_DPI)
    _print_drawn(out, "gates.png")


def _choose_channels(samples, names, exclude=None) -> tuple[list[str], list[str]]:
    """The fluorescence channels to cluster and their labels, by pipeline.resolve_channels, for
    --channels and --exclude-channels given as names. The run checks them before asking for
    populations, so a bad channel stops it first."""
    settings = ClusterSettings(
        channels=_channel_names(names), exclude_channels=_channel_names(exclude) or ()
    )
    try:
        return pipeline.resolve_channels(samples, settings)
    except FlowError as e:
        raise SystemExit(e.cli(cli_flag)) from None


def main(argv=None) -> None:
    """datanuggets-flow. A FlowError, a bad setting's or a step's, stops it with its message, the
    setting written as its flag."""
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except FlowError as e:
        raise SystemExit(e.cli(cli_flag)) from None


@contextmanager
def _marked(out: Path):
    """The new folder out, marked incomplete until the steps in the with block finish. A step
    that fails, or a Ctrl+C, leaves the marker and says where the partial outputs are."""
    state.begin(out)
    try:
        yield
    except (Exception, SystemExit, KeyboardInterrupt):
        print(f"\nRun incomplete; partial outputs are in {out.resolve()}", file=sys.stderr)
        raise
    state.finish(out)


def _run(args) -> None:
    """The run in its mode: every check, then the output folder, the steps, and the figures
    shown. --gates-only stops once the gates are saved; --from-gates goes to _from_gates."""
    # --pops "", as a script that expands an unset variable gives it, is no --pops in every mode:
    # the run asks, and --gates-only doesn't count it as a clustering flag
    args.pops = args.pops or None
    _mode_rules(args)
    cluster = _settings(args)
    if args.from_gates is not None:
        _from_gates(args, cluster)
        return
    stop = args.gates_only
    plt = _pyplot(args.no_show, tables=not stop, tsne=cluster.tsne and not stop)
    paths, gate, out = _check_args(args)
    cluster = groups_for(args, cluster, len(paths))
    with _marked(out):
        if stop:  # nothing is asked between the figures, so the library's stage writes the folder
            pipeline.gate_stage(
                paths, out, gate, read=_read, on_event=_print_event, figure=plt.figure
            )
            _print_drawn(out, *DRAWN)
        else:
            samples = _gate_files(paths, gate, out, plt)
            _choose_channels(samples, args.channels, args.exclude_channels)
            chosen = _choose_pops(samples, args.pops, plt, not args.no_show)
            _draw_gates(samples, plt, out)
            pipeline.cluster_stage(
                samples,
                chosen,
                out,
                cluster,
                read=_read,
                on_event=_print_event,
                figure=plt.figure,
            )
    if stop:
        where = out.resolve()
        print(f"\nGates are in {where}")
        print(f'Choose populations and cluster with: datanuggets-flow --from-gates "{where}"')
    else:
        print(f"\nOutputs are in {out.resolve()}")
    if not args.no_show:
        plt.show()


def _note_versions(gates: state.GateFolder) -> None:
    """A line naming each package whose version differs from the one gates was made with. The
    run goes on, since the masks are the gates, but the packages that cluster can move the
    tables."""
    changed = state.changed_versions(gates.versions)
    if changed:
        listed = ", ".join(
            f"{name} {was or 'not installed'} (now {now or 'not installed'})"
            for name, (was, now) in changed.items()
        )
        message = f"note: {gates.path} was gated with {listed}; its masks are used as saved"
        n = len(gates.samples)
        _print_event(pipeline.StageEvent("gate", None, n, message, {"versions": changed}))


def _from_gates(args, cluster: ClusterSettings) -> None:
    """--from-gates: the gate folder and its files checked, --out refused if it is taken, and
    the channels resolved, all before the populations are asked over the folder's figures, so a
    run that can't go ahead stops before the question. The run folder is made only after it;
    the gate figures are copied in as they are, and run.json records the gate folder, the choice,
    the cofactor used, the Scale stage's pooled mean and SD, and how the nuggets were clustered,
    with the R calls that rebuild them. The gate folder itself is only read."""
    plt = _pyplot(args.no_show, tables=True, tsne=cluster.tsne)
    # figures imports matplotlib, so only once _pyplot has found it
    from datanuggets_flow.figures import png_figure

    gates = state.load_gates(Path(args.from_gates))
    _note_versions(gates)
    samples = gates.samples
    cluster = groups_for(args, cluster, len(samples))
    out = state.check_new(_out(args, FLOW_RUN_NAME))
    _choose_channels(samples, args.channels, args.exclude_channels)
    show = not args.no_show
    figures = [gates.path / name for name in DRAWN]
    _print_drawn(gates.path, *DRAWN)
    if show:
        for path in figures:
            png_figure(path, FLOW_GATE_DPI, figure=plt.figure)
    chosen = _choose_pops(samples, args.pops, plt, show)
    with _marked(out):
        for path in figures:
            shutil.copyfile(path, out / path.name)
        run = pipeline.cluster_stage(
            samples,
            chosen,
            out,
            cluster,
            read=_read,
            on_event=_print_event,
            figure=plt.figure,
        )
        state.write_run(
            out,
            gates.path,
            cluster,
            chosen,
            run.channels,
            run.labels,
            scaling=run.pool.scaling,
            cofactor=run.cofactor,
            pool=run.pool,
        )
    print(f"\nOutputs are in {out.resolve()}")
    if show:
        plt.show()


if __name__ == "__main__":
    main()
