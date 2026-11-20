"""datanuggets_flow: reading an FCS file, the gate and cluster settings, and the stages of a gate
job and a flow run with the run folder's record keeping around them."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


def read_fcs(path: Path):
    """(events, pnn, pns) for one FCS file."""
    from datanuggets_flow.pipeline import read_fcs as read

    return read(path)


def read_ranges(path: Path) -> list[float | None]:
    """Each channel's range from the file's $PnR, in channel order, decoded as the package's
    read_ranges decodes it; None for a channel whose header gives no usable range."""
    from datanuggets_flow.pipeline import read_ranges as read

    return list(read(path)[1])


def default_channels(pnn: Sequence[str], pns: Sequence[str], name: str) -> list[str]:
    """The package's own rule (resolve_channels with default settings) for one file; [] when the
    file has no channel it would pick."""
    from datanuggets_flow.exceptions import FlowError
    from datanuggets_flow.pipeline import resolve_channels
    from datanuggets_flow.settings import ClusterSettings

    sample = {"pnn": list(pnn), "pns": list(pns), "path": Path(name)}
    try:
        channels, _ = resolve_channels([sample], ClusterSettings())
    except FlowError:
        return []
    return channels


def colour_channels(pnn: Sequence[str]) -> list[str]:
    """A file's colour channels, sorted and each once: the $PnN names the package's default rule
    clusters, those that end in FLOW_CHANNEL_SUFFIX and do not start with one of
    FLOW_SCATTER_PREFIXES. Files whose lists are equal are one dataset."""
    from datanuggets_flow._defaults import FLOW_CHANNEL_SUFFIX, FLOW_SCATTER_PREFIXES

    suffix, scatter = FLOW_CHANNEL_SUFFIX, FLOW_SCATTER_PREFIXES
    return sorted({c for c in pnn if c.endswith(suffix) and not c.startswith(scatter)})


# ---- settings -----------------------------------------------------------------------------


def gate_defaults() -> dict:
    from datanuggets_flow.settings import GateSettings

    return GateSettings().to_dict()


def gate_settings(data: Mapping, n_files: int):
    """GateSettings.from_dict(data).check(n_files)."""
    from datanuggets_flow.settings import GateSettings

    return GateSettings.from_dict(dict(data)).check(n_files)


def cluster_defaults() -> dict:
    from datanuggets_flow.settings import ClusterSettings

    out = ClusterSettings().to_dict()
    out.pop("n_jobs", None)
    return out


def cluster_settings(data: Mapping):
    """ClusterSettings.from_dict(data).check()."""
    from datanuggets_flow.settings import ClusterSettings

    return ClusterSettings.from_dict(dict(data)).check()


def cofactor_rule() -> dict:
    """How the auto cofactor picks: per channel, from the cells the run clusters, the SD of its
    cells below 0 where at least min_negative_fraction of them are below 0, never under floor,
    and floor otherwise. It needs the cells, so a client can't preview the numbers."""
    from datanuggets_flow._defaults import FLOW_COFACTOR_FLOOR, FLOW_COFACTOR_MIN_NEGATIVE

    return {
        "rule": "per_channel",
        "floor": float(FLOW_COFACTOR_FLOOR),
        "min_negative_fraction": float(FLOW_COFACTOR_MIN_NEGATIVE),
    }


def run_transform(record: Mapping) -> dict:
    """A run.json's Transform stage as the package reads it: a per-channel auto record, or one
    of the earlier header rule with its range, as written; an older arcsinh with no
    cofactor_from is read as set, and a record without the stage gets it from its settings."""
    from datanuggets_flow import state

    return state.run_transform(dict(record))


# ---- stages (worker only) -----------------------------------------------------------------


def gate_stage(paths: Sequence[Path], out: Path, settings, *, on_event: Callable) -> None:
    from datanuggets_flow.pipeline import gate_stage as stage

    stage(list(paths), out, settings, on_event=on_event)


def load_gates(folder: Path):
    """The gate folder's record and samples, as datanuggets_flow.state reads them."""
    from datanuggets_flow import state

    return state.load_gates(folder)


def start_run(out: Path) -> None:
    """Refuses a folder that already holds a run, then marks out as a run in progress."""
    from datanuggets_flow import state

    state.check_new(out)
    state.begin(out)


def cluster_stage(samples, chosen: list[list[int]], out: Path, settings, *, on_event: Callable):
    from datanuggets_flow.pipeline import cluster_stage as stage

    return stage(samples, chosen, out, settings, on_event=on_event)


def write_run(
    out: Path,
    gates: Path,
    settings,
    chosen,
    channels,
    labels,
    *,
    scaling=None,
    cofactor=None,
    pool=None,
) -> None:
    """run.json, with the Transform stage (cofactor, the run's RunResult.cofactor: each
    channel's cofactor auto picked, or the number set), the Scale stage's pooled mean and SD
    (scaling, the run's pool.scaling; None when the stage was off) and, given the run's pool,
    the clustering block the package's clustering_record writes: the method, k asked and k
    used, the nuggets clustered and dropped (weight 0), the total WWCSS, and the create.DN and
    clustering calls that rebuild the run in R."""
    from datanuggets_flow import state

    state.write_run(
        out,
        gates,
        settings,
        chosen,
        channels,
        labels,
        scaling=scaling,
        cofactor=cofactor,
        pool=pool,
    )


def finish_run(out: Path) -> None:
    from datanuggets_flow import state

    state.finish(out)
