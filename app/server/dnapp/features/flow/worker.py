"""A flow run's work inside its job worker: the package's cluster stage on a done gate, with the
run folder's record keeping around it."""

from __future__ import annotations

import shutil
from pathlib import Path

from dnapp.core.config import FLOW_FIGURES, FLOW_RECORD, FLOW_STEPS, PROGRESS_START
from dnapp.core.package import flow
from dnapp.core.protocols import Reporter

# the job's step line for each stage event but "nuggets", which names its file, and "tsne",
# which gives its nuggets and dims
STEP_MESSAGES = {
    "select": "Selected cells",
    "transform": "Transformed the channels",
    "scale": "Scaled the channels",
    "cluster": "Clustered",
    "figures": "Drawing the figures",
}


def flow_work(spec: dict, rep: Reporter, out: Path) -> dict:
    gates = Path(spec["gates"])
    folder = flow.load_gates(gates)
    settings = flow.cluster_settings(spec["settings"])
    flow.start_run(out)
    for name in spec["gate_figures"]:
        shutil.copyfile(gates / name, out / name)

    def on_event(ev) -> None:
        # a per-file "channels", "cofactor" or "scale" event's message is empty, and logs
        # nothing, as do "tsne" and "figures"; the "transform" event's gives the rule and a line
        # per channel with its cofactor. Each event is a cancel point, so the t-SNE fits and the
        # figures each start with one
        rep.log(ev.message)
        if ev.stage == "nuggets":
            lo, hi = FLOW_STEPS["nuggets_from"], FLOW_STEPS["nuggets_to"]
            p = lo + (hi - lo) * (ev.file or 0) / max(ev.n_files, 1)
            msg = f"Nuggets for file {ev.file} of {ev.n_files}"
        elif ev.stage == "channels" and ev.file:
            lo, hi = PROGRESS_START, FLOW_STEPS["select"]
            p = lo + (hi - lo) * ev.file / max(ev.n_files, 1)
            msg = f"Channels: read file {ev.file} of {ev.n_files}"
        elif ev.stage == "cofactor" and ev.file:
            lo, hi = FLOW_STEPS["select"], FLOW_STEPS["cofactor"]
            p = lo + (hi - lo) * ev.file / max(ev.n_files, 1)
            msg = f"Cofactor: read file {ev.file} of {ev.n_files}"
        elif ev.stage == "scale" and ev.file:
            lo, hi = FLOW_STEPS["transform"], FLOW_STEPS["scale"]
            p = lo + (hi - lo) * ev.file / max(ev.n_files, 1)
            msg = f"Scaling: read file {ev.file} of {ev.n_files}"
        elif ev.stage == "tsne":
            p = FLOW_STEPS["tsne_3d" if ev.data["dims"] == 3 else "cluster"]
            msg = f"t-SNE of {ev.data['nuggets']:,} nuggets in {ev.data['dims']}D"
        else:
            p = FLOW_STEPS.get(ev.stage, rep.p)
            msg = STEP_MESSAGES.get(ev.stage, ev.stage)
        rep.progress(p, ev.stage, msg)
        rep.check()

    chosen = [list(p) for p in spec["pops"]]
    result = flow.cluster_stage(folder.samples, chosen, out, settings, on_event=on_event)
    rep.progress(FLOW_FIGURES, "figures", "Drew the figures")
    rep.check()
    # run.json's transform gets the cofactors the stage used and how they were chosen: auto's
    # one per channel, with each one's share of cells below 0 and their SD, or the number set;
    # its clustering block, from the pool, says how the nuggets were clustered and gives the R
    # calls that rebuild them
    flow.write_run(
        out,
        gates,
        settings,
        chosen,
        result.channels,
        result.labels,
        scaling=result.pool.scaling,
        cofactor=result.cofactor,
        pool=result.pool,
    )
    rep.progress(FLOW_RECORD, "record", "Saved the run record")
    flow.finish_run(out)
    return {"k": int(result.pool.k)}
