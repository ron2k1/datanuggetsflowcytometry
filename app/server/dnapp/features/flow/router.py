"""POST /flow/runs (contract section 3.4): the cluster stage on the chosen populations of a done
gate."""

from __future__ import annotations

from fastapi import APIRouter, Request

from dnapp.core.config import GATE_FIGURES
from dnapp.core.datasets import check_one_dataset
from dnapp.core.deps import WS, check_job_room, st
from dnapp.core.errors import ApiError
from dnapp.core.filters import checked_filters
from dnapp.core.limits import check_max
from dnapp.core.package import flow
from dnapp.core.package.errors import refusals
from dnapp.core.package.filters import filter_spec, row_filter
from dnapp.core.pops import check_pops
from dnapp.features.flow.schemas import FlowRun

router = APIRouter()


@router.post("/flow/runs", status_code=202)
def post_flow(body: FlowRun, request: Request, ws: WS):
    s = st(request)
    caps = s.settings.caps
    gate = s.gates.find(ws, body.gate_id)
    if gate is None:
        raise ApiError(
            "invalid_setting", f"{body.gate_id} is not a gate in this workspace.", "gate_id"
        )
    if s.gates.status(ws, gate) != "done":
        raise ApiError("wrong_state", "The gate is not done yet.")
    # a gate made before POST /flow/gates checked its files may mix datasets, and a local
    # workspace keeps its gates; the uploads are there, since a gate's uploads cannot be deleted
    check_one_dataset([s.uploads.record(ws, u) for u in gate["uploads"]], "run", "gate_id")
    files = s.gates.files(ws, gate)
    check_pops(files, body.pops)
    if body.groups is not None and len(body.groups) != len(files):
        raise ApiError(
            "invalid_setting",
            f"groups gives {len(body.groups)} names for {len(files)} files; give one per file.",
            "groups",
        )
    settings = flow.cluster_defaults()
    sent = body.model_dump(exclude={"gate_id", "pops", "row_filters"}, exclude_none=True)
    if body.groups is None:
        sent["groups"] = None
    settings.update(sent)
    filters = checked_filters(body.row_filters, row_filter)
    specs = [filter_spec(f) for f in filters]
    check_max("k", settings.get("k"), caps.k_max)
    check_max("dn_num1", settings.get("dn_num1"), caps.dn_num1_max)
    check_max("dn_num2", settings.get("dn_num2"), caps.dn_num2_max)
    check_max("cells_per_file", settings.get("cells_per_file"), caps.cells_per_file_max)
    kept = sum(1 for p in body.pops if p)
    if caps.pooled_nuggets_max is not None and kept * settings["dn_num2"] > caps.pooled_nuggets_max:
        raise ApiError(
            "invalid_setting",
            f"{kept} files of {settings['dn_num2']} nuggets is more than the {caps.pooled_nuggets_max} pooled nuggets this server allows.",
            "dn_num2",
        )
    package_settings = dict(settings, row_filters=specs, n_jobs=s.settings.jobs)
    with refusals():
        checked = flow.cluster_settings(package_settings)
    spec = {
        "gates": str(s.gates.folder(ws, gate["id"])),
        "gate_figures": list(GATE_FIGURES),
        "pops": body.pops,
        "settings": checked.to_dict(),
        "param_names": sorted(set(checked.to_dict()) | {"pops", "groups", "row_filters"}),
    }
    record_settings = {
        "gate_id": body.gate_id,
        "pops": body.pops,
        **settings,
        "row_filters": filters,
    }
    title = f"{kept} of {len(files)} files, k = {settings['k']}"
    ip = check_job_room(request)
    return s.runs.create(ws, ip, "flow", spec, record_settings, title, body.gate_id)
