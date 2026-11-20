"""A gate job's work inside its job worker: the package's gate stage on the chosen FCS uploads."""

from __future__ import annotations

from pathlib import Path

from dnapp.core.config import GATE_SHARE, PROGRESS_START
from dnapp.core.package import flow
from dnapp.core.protocols import Reporter


def gate_work(spec: dict, rep: Reporter, out: Path) -> dict:
    paths = [Path(p) for p in spec["paths"]]
    settings = flow.gate_settings(spec["settings"], len(paths))

    def on_event(ev) -> None:
        rep.log(ev.message)
        done = (ev.file or 0) / max(ev.n_files, 1)
        rep.progress(
            PROGRESS_START + GATE_SHARE * done, ev.stage, f"Gated file {ev.file} of {ev.n_files}"
        )
        rep.check()

    out.mkdir(parents=True)
    flow.gate_stage(paths, out, settings, on_event=on_event)
    return {}
