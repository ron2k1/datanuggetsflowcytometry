"""datanuggets-flow's arguments: the flags, the FCS paths they name, the settings they give,
checked before any file is read, and the rules each mode holds them to."""

from __future__ import annotations

import argparse
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path

from datanuggets_flow import pipeline
from datanuggets_flow._defaults import (
    CENTER_METHODS,
    DRAWS,
    FLOW_COFACTOR_AUTO,
    FLOW_COFACTOR_FLOOR,
    FLOW_GATES_NAME,
    FLOW_METHODS,
    FLOW_OUT_DIR,
    FLOW_RUN_NAME,
)
from datanuggets_flow.settings import (
    AREAS,
    DISC_ALIASES,
    ClusterSettings,
    GateSettings,
    check_groups,
    cli_flag,
)


def per_file(text: str | None, name: str) -> tuple[float, ...] | None:
    """--t11 or --t21 as GateSettings takes it: one number for every file, or one per file
    separated by commas, or None when it is left out. GateSettings.check counts them against the
    files, so the rule is kept in one place."""
    if text is None:
        return None
    try:
        return tuple(float(t) for t in str(text).split(","))
    except ValueError as e:
        raise SystemExit(f"{name} takes numbers like 22 or 22,20,18,18, got {text!r}") from e


def _cofactor(text: str) -> float | str:
    """--cofactor as ClusterSettings takes it: auto, or a number. Anything else is passed on as
    given, for ClusterSettings.check to refuse with the rule."""
    if text == FLOW_COFACTOR_AUTO:
        return text
    try:
        return float(text)
    except ValueError:
        return text


def _fcs_paths(items) -> list[Path]:
    paths = []
    for item in map(Path, items):
        if item.is_dir():  # a folder's .fcs files by name, leaving out macOS's ._ copies
            paths += sorted(
                p
                for p in item.iterdir()
                if p.suffix.lower() == ".fcs" and not p.name.startswith(".")
            )
        elif item.is_file():
            paths.append(item)
        else:
            raise SystemExit(f"{item}: no such file or folder")
    if not paths:
        raise SystemExit(f"no .fcs files in {', '.join(map(str, items))}")
    return paths


def _parser() -> argparse.ArgumentParser:
    """The flags. One that sets a GateSettings or ClusterSettings field, under the field's name,
    defaults to None, so a run without it takes the settings' default, which its help shows."""
    gate, cluster = GateSettings(), ClusterSettings()
    p = argparse.ArgumentParser(
        prog="datanuggets-flow",
        description="Gate FCS files on two channels (forward against side scatter unless --fsc "
        "and --ssc name others), keep the populations you pick, and cluster their cells with data "
        "nuggets and weighted k-means (or the hierarchical tree).",
    )
    p.add_argument("paths", nargs="*", help="FCS files, or folders of them; none with --from-gates")
    stage = p.add_mutually_exclusive_group()
    stage.add_argument(
        "--gates-only",
        action="store_true",
        help="gate the files, draw local_maxima.png and gates.png, save the gates in --out, and "
        "stop, without asking",
    )
    stage.add_argument(
        "--from-gates",
        metavar="GATES",
        help="choose populations over the figures of GATES, a --gates-only folder, and cluster "
        "its files, which must not have changed",
    )
    p.add_argument(
        "--pops",
        help='populations to keep, e.g. "1,2" for every file or "1,2;1;1" '
        "file by file; without it you are asked",
    )
    p.add_argument(
        "--out",
        help="new output folder (default: outputs/flow-<timestamp>, or "
        "outputs/flow-gates-<timestamp> with --gates-only); existing paths are refused",
    )
    p.add_argument("--k", type=int, help=f"clusters (default: {cluster.k})")
    p.add_argument(
        "--method",
        choices=FLOW_METHODS,
        help="wkmeans: WCluster's weighted k-means of the pooled nuggets, as Wkmeans clusters "
        "them; tree: the hierarchical tree, Whclust cut into --k clusters, or into as many as "
        f"there are nuggets when that's fewer (default: {cluster.method})",
    )
    p.add_argument(
        "--center-method",
        choices=CENTER_METHODS,
        help="each nugget's center, create.DN's center.method: original, the point the nugget "
        "was built around; mean, its cells' mean; random, one of its cells at random (default: "
        f"{cluster.center_method})",
    )
    p.add_argument(
        "--num-init",
        type=int,
        metavar="N",
        help=f"weighted k-means' random starts, the best kept (default: {cluster.num_init})",
    )
    p.add_argument(
        "--max-iter",
        type=int,
        metavar="N",
        help=f"weighted k-means' rounds per start at most (default: {cluster.max_iter})",
    )
    p.add_argument(
        "--draws",
        choices=DRAWS,
        help="create_dn's draws from --seed: r, R's set.seed draws, so the nuggets are "
        "create.DN's; numpy, the draws runs made before this flag (default: "
        f"{cluster.draws})",
    )
    p.add_argument(
        "--cofactor",
        type=_cofactor,
        metavar="COFACTOR",
        help="the Transform stage: fluorescence is clustered as arcsinh(x / cofactor), or as "
        f"stored with 0; {cluster.cofactor} (the default) picks one per channel from the spread "
        f"of its cells below 0, at least {FLOW_COFACTOR_FLOOR:g}; a number applies to every "
        "channel; 0 keeps the channels linear",
    )
    p.add_argument(
        "--no-standardize",
        dest="standardize",
        action="store_false",
        default=None,
        help="leave out the Scale stage: keep each channel in the transform's units instead of "
        "centring it and scaling it to SD 1 by the mean and SD pooled over the files",
    )
    p.add_argument(
        "--dn-num1",
        type=int,
        help="create_dn's dn_num1, the nuggets its first pass makes from a file's kept cells "
        f"before they are reduced to --dn-num2 (default: {cluster.dn_num1})",
    )
    p.add_argument("--dn-num2", type=int, help=f"nuggets per file (default: {cluster.dn_num2})")
    p.add_argument(
        "--seed",
        type=int,
        help=f"the seed of create_dn and of weighted k-means (default: {cluster.seed})",
    )
    p.add_argument(
        "--jobs",
        type=int,
        dest="n_jobs",
        metavar="JOBS",
        help="cores create_dn and weighted k-means use, -1 for every one; the results are the "
        f"same for any (default: {cluster.n_jobs})",
    )
    channels = p.add_mutually_exclusive_group()
    channels.add_argument(
        "--channels",
        help="comma-separated channels to cluster (default: every -A channel but scatter, FS and "
        "SS, or every channel but those and Time when a file has fewer than two)",
    )
    channels.add_argument(
        "--exclude-channels", help="comma-separated channels to leave out of the default ones"
    )
    p.add_argument(
        "--fsc",
        help="the channel the gate takes across (default: the first file's forward scatter, an "
        "FS channel ending -A first, or its first marker channel when it has none)",
    )
    p.add_argument(
        "--ssc",
        help="the channel the gate takes up (default: the first file's side scatter, an SS "
        "channel ending -A first, or a marker channel when it has none)",
    )
    p.add_argument(
        "--disc",
        type=lambda d: DISC_ALIASES.get(d, d),  # his, the old name, still works
        choices=tuple(AREAS),
        help="reference: the reference code's gates, so the populations match cfc.py's figures; "
        "peak: datanuggets_flow.find_area, the disc centred on the peak "
        f"(default: {gate.disc})",
    )
    p.add_argument(
        "--t11",
        help="the first peak's distance threshold, one for all files or one per file, e.g. "
        f"22,20,18,18 as in cfc.py (default: {gate.t11[0]})",
    )
    p.add_argument(
        "--t21",
        help="the first peak's density threshold, the same way, e.g. 0.25,0.5,0.5,0.5 "
        f"(default: {gate.t21[0]})",
    )
    p.add_argument(
        "--t12",
        type=float,
        help=f"every other peak's distance threshold, in every file (default: {gate.t12})",
    )
    p.add_argument(
        "--t22",
        type=float,
        help=f"every other peak's density threshold, in every file (default: {gate.t22})",
    )
    p.add_argument(
        "--n-row",
        type=int,
        help=f"rows of the window the finder's local maxima are found in (default: {gate.n_row})",
    )
    p.add_argument("--n-col", type=int, help=f"columns of that window (default: {gate.n_col})")
    p.add_argument(
        "--no-tsne",
        dest="tsne",
        action="store_false",
        default=None,
        help="leave out the t-SNE of the nuggets, clusters_tsne.png, and the need for scikit-learn",
    )
    p.add_argument(
        "--tsne-perplexity",
        type=float,
        help="the t-SNE's perplexity, lowered to (nuggets - 1) / 3 when that's smaller "
        f"(default: {cluster.tsne_perplexity:g})",
    )
    p.add_argument("--tsne-seed", type=int, help=f"the t-SNE's seed (default: {cluster.tsne_seed})")
    p.add_argument(
        "--filter",
        dest="row_filters",
        action="append",
        metavar="SPEC",
        help='keep only kept cells that pass, on raw $PnN values, e.g. "[FJComp-BV510-A] > 1000"; '
        "bracket a channel name with spaces; repeat to AND several",
    )
    p.add_argument(
        "--groups",
        help='one group name per file, in file order, separated by ;, e.g. "ctrl;ctrl;treated"; '
        "adds groups.csv, group_summary.csv and group_markers.csv",
    )
    p.add_argument(
        "--cells-per-file",
        type=int,
        help="kept cells per file sampled into cells.csv, 0 for none "
        f"(default: {cluster.cells_per_file})",
    )
    p.add_argument("--no-show", action="store_true", help="save the figures without opening them")
    return p


def _given(args, cls) -> list[str]:
    """The settings of cls whose flags were given."""
    return [f.name for f in fields(cls) if getattr(args, f.name, None) is not None]


def _mode_rules(args) -> None:
    """Refuses a flag the mode can't use, before any setting is checked or file read: FCS paths
    or a gate setting with --from-gates, which reuses its folder's files and gates, and a
    clustering setting or --pops with --gates-only, which stops before them."""
    if args.from_gates is None and not args.paths:
        raise SystemExit("give FCS files or folders, or --from-gates GATES")
    if args.from_gates is not None and args.paths:
        raise SystemExit(
            "--from-gates reads the FCS files its gate folder records; give no FCS paths"
        )
    gate = _given(args, GateSettings) if args.from_gates is not None else []
    if gate:
        raise SystemExit(
            f"{cli_flag(gate[0])} sets the gate stage, and --from-gates reuses the gates in "
            f"{args.from_gates}; run --gates-only again to change it"
        )
    cluster = _given(args, ClusterSettings) + ["pops"] * (args.pops is not None)
    if args.gates_only and cluster:
        raise SystemExit(
            f"{cli_flag(cluster[0])} sets the clustering stage, which --gates-only stops before"
        )


def _flags(cls, args, **values):
    """cls's settings from the flags named for them, values standing in for flags that are read
    another way first. A flag left out, or a value of None, keeps cls's default."""
    given = {f.name: getattr(args, f.name, None) for f in fields(cls)} | values
    return cls(**{name: v for name, v in given.items() if v is not None})


def _settings(args) -> ClusterSettings:
    """The settings the flags give, checked before any file is read, so a bad value stops the run
    first; the clustering's are returned. --t11 and --t21 wait for the files to be counted, and
    --groups, whose names are checked here, for groups_for to count them against the files. A
    flag that would have no effect is refused rather than ignored: the t-SNE's with --no-tsne,
    and weighted k-means' starts and rounds with --method tree."""
    for name in ("tsne_perplexity", "tsne_seed"):
        if args.tsne is False and getattr(args, name) is not None:
            raise SystemExit(f"{cli_flag(name)} has no effect with --no-tsne")
    if args.method == "tree" and (args.num_init is not None or args.max_iter is not None):
        raise SystemExit(
            "--num-init and --max-iter set weighted k-means, not the hierarchical tree"
        )
    _flags(GateSettings, args, t11=None, t21=None).check()
    if args.groups is not None:
        check_groups([name.strip() for name in args.groups.split(";")])
    cluster = _flags(
        ClusterSettings,
        args,
        channels=_channel_names(args.channels),
        exclude_channels=_channel_names(args.exclude_channels),
        row_filters=tuple(args.row_filters) if args.row_filters else None,
        groups=None,
    )
    return cluster.check()


def groups_for(args, cluster: ClusterSettings, n_files: int) -> ClusterSettings:
    """cluster with --groups, once the files are counted: one name per file, by
    pipeline.parse_groups. Without --groups, cluster as it is."""
    if args.groups is None:
        return cluster
    return replace(cluster, groups=pipeline.parse_groups(args.groups, n_files))


def _out(args, name: str) -> Path:
    """--out, or a folder under FLOW_OUT_DIR named for the UTC time by the pattern name, so each
    run has its own."""
    return Path(args.out) if args.out else Path(FLOW_OUT_DIR) / datetime.now(UTC).strftime(name)


def _check_args(args) -> tuple[list[Path], GateSettings, Path]:
    """Validate arguments without writing files; return inputs, the gate settings and output.
    The gate settings are built once, here, with --t11 and --t21 as given and checked against the
    files; one left out gives the settings' one value for every file. --pops is counted against
    the files too, by the rule parse_selection reads it with."""
    paths = _fcs_paths(args.paths)
    t11, t21 = per_file(args.t11, "--t11"), per_file(args.t21, "--t21")
    gate = _flags(GateSettings, args, t11=t11, t21=t21).check(len(paths))
    out = _out(args, FLOW_GATES_NAME if args.gates_only else FLOW_RUN_NAME)
    if args.pops is not None:
        pipeline.selection_choices(args.pops, len(paths))
    return paths, gate, out


def _channel_names(names: str | None) -> tuple[str, ...] | None:
    """--channels or --exclude-channels as ClusterSettings takes it: its names, or None when it
    is left out."""
    return tuple(c.strip() for c in names.split(",")) if names else None
