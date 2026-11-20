"""r7: a flow run made here by the server's own flow worker on the gate g1 stands for, with the
pops r3 used and the cluster defaults, so its cofactor is "auto". Its plot, cells and compare
payloads and its manifest parts come from the server's own readers of the run folder.

Auto picks one cofactor per clustered channel from the cells the run clusters: the SD of the
cells below 0 where at least 1% of them are below 0, at least 150, and 150 otherwise. run.json
records each channel's cofactor with its share of cells below 0 and their SD. r3's run.json,
written before the Transform stage was recorded, stays beside it as the older shape, read as set.

To keep the fixtures small the run asks for NUGGETS nuggets and CELLS_PER_FILE cells per file;
every other setting is the default, and the manifest's settings say so."""

from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

from dnapp.core.config import GATE_FIGURES, TRIAL_CAPS
from dnapp.core.package import flow
from dnapp.core.run_outputs import clusters, file_entries
from dnapp.features.compare.service import compare
from dnapp.features.flow.worker import flow_work
from dnapp.features.plot.cells import cells
from dnapp.features.plot.service import flow_plot

from .common import scrub, scrub_obj, short

RID = "r7"
NUGGETS = 250  # dn_num2: nuggets per file (the default is 1000)
CELLS_PER_FILE = 500  # cells_per_file (the default is 2000)


class LogOnly:
    """The job worker's Reporter, keeping only the log lines, scrubbed as the worker writes them."""

    p = 0.0

    def __init__(self):
        self.lines: list[str] = []

    def check(self) -> None:
        pass

    def log(self, text: str) -> None:
        self.lines += [scrub(x) for x in str(text).splitlines() if x.strip()]

    def progress(self, p: float, stage, message=None) -> None:
        self.p = max(self.p, p)


def auto_run(gates: Path, work: Path, pops: list[list[int]], groups: list[str]) -> dict:
    """Runs the flow worker on the gate folder into work/flow-auto-run and returns the run's entry
    for write_runs: its folder, run.json, payloads, manifest settings, warnings and log."""
    out = work / "flow-auto-run"
    if out.exists():
        shutil.rmtree(out)
    # as POST /flow/runs builds them: the defaults, then what the request sends
    settings = flow.cluster_defaults()
    settings.update(groups=groups, dn_num2=NUGGETS, cells_per_file=CELLS_PER_FILE)
    checked = flow.cluster_settings(dict(settings, row_filters=[], n_jobs=1))
    spec = {
        "gates": str(gates),
        "gate_figures": list(GATE_FIGURES),
        "pops": pops,
        "settings": checked.to_dict(),
    }
    rep = LogOnly()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        flow_work(spec, rep, out)
    found = []
    for w in caught:  # as the job worker keeps them: scrubbed, each once
        text = scrub(str(w.message))
        if text not in found:
            found.append(text)
    record = json.loads((out / "run.json").read_text(encoding="utf-8"))
    t = flow.run_transform(record)
    cofactors = t.get("cofactors") or ()
    if t.get("cofactor_from") != "auto" or len(cofactors) != len(record["labels"]):
        raise SystemExit(f"flow auto run: run.json's transform is {t}, not auto per channel")
    raised = [
        f"{short(lab)} {c:,.0f}" for lab, c in zip(record["labels"], cofactors) if c > t["floor"]
    ]
    print(
        f"flow auto run: cofactor per channel, {t['floor']:g} on {len(cofactors) - len(raised)} of "
        f"{len(cofactors)} channels; above it {', '.join(raised) or 'none'}"
    )
    record_settings = {"gate_id": "g1", "pops": pops, **settings, "row_filters": []}
    plot = flow_plot(RID, out, record, record_settings)
    plot["warnings"] = plot["warnings"] + found
    body = cells(RID, out, record, CELLS_PER_FILE, TRIAL_CAPS.cells_max_total)
    cmp = compare(RID, out, record, record_settings)
    return {
        "kind": "flow",
        "dir": out,
        "rj": record,
        "plot": scrub_obj(plot),
        "cells": scrub_obj(body),
        "compare": scrub_obj(cmp),
        "extra": {},
        "settings": record_settings,
        "warnings": found,
        "clusters": clusters(out),
        "files": file_entries(out),
        "log": rep.lines,
        "created": record.get("created"),
    }
