"""GET and POST /flow/gates/{gid}/livecells, GET /flow/gates/{gid}/livecells/{lid} and POST
/flow/gates/{gid}/livecells/{lid}/counts (contract-livecells.md section 2). The server checks
counts and ranges; the package refuses the rest, and nothing here proposes a threshold."""

from __future__ import annotations

import re

from fastapi import APIRouter, Request

from dnapp.core.deps import WS, check_job_room, ip_of, own, st
from dnapp.core.errors import ApiError
from dnapp.core.filters import checked_filters
from dnapp.core.limits import check_max
from dnapp.core.package import livecells
from dnapp.core.package.errors import refusals
from dnapp.core.package.filters import filter_spec, row_filter
from dnapp.core.pops import check_pops
from dnapp.core.state import State
from dnapp.core.workspace import Workspace
from dnapp.features.livecells.schemas import CountsRequest, LivecellsRequest
from dnapp.features.livecells.service import KIND, LiveCells

router = APIRouter()
SETS = "/flow/gates/{gid}/livecells"
# half a UTF-16 surrogate pair: a JSON escape can carry one, but UTF-8 cannot encode it, so a set
# that kept one in its request failed every answer that lists it
LONE = re.compile(r"[\ud800-\udfff]")


def service(request: Request) -> LiveCells:
    return own(request, KIND, LiveCells)


def done_gate(s: State, ws: Workspace, gid: str) -> dict:
    gate = s.gates.record(ws, gid)
    if s.gates.status(ws, gate) != "done":
        raise ApiError("wrong_state", "The gate is not done yet.")
    return gate


def started(s: State, live: LiveCells, ws: Workspace, rec: dict) -> dict:
    return {"job": s.jobs.view(live.job(ws, rec)), "livecells_id": rec["id"]}


@router.get(SETS)
def get_livecells(gid: str, request: Request, ws: WS):
    s, live = st(request), service(request)
    gate = done_gate(s, ws, gid)
    channels = s.gates.files(ws, gate)[0]["channels"]  # gate file 1, as the channel rule reads
    suggested = livecells.suggest([c["pnn"] for c in channels], [c["pns"] for c in channels])
    with ws.lock:  # the records, which other requests' threads change
        sets = [live.summary(ws, r) for r in live.of_gate(ws, gid)]
    return s.scrub.obj(
        {"gate_id": gid, "channels": channels, "suggested": suggested, "livecells": sets}
    )


def normalized(body: LivecellsRequest, s: State, files: list[dict]) -> dict:
    """The request as the cache compares it: pops sorted per file, the channels in order, and
    bins and cofactor filled in; 422 naming the field that is out of range, or channels for a
    scatter channel or one LONE matches. Any number of distinct marker channels passes, up to the
    trial cap."""
    caps = s.settings.caps
    check_pops(files, body.pops)
    if not body.channels:
        raise ApiError("invalid_setting", "Choose at least one channel.", "channels")
    check_max("channels", len(body.channels), caps.livecells_channels_max)
    if len(set(body.channels)) != len(body.channels):
        raise ApiError("invalid_setting", "Choose each channel once.", "channels")
    if any(LONE.search(c) for c in body.channels):  # before a message names one
        raise ApiError(
            "invalid_setting",
            "A channel name has a lone surrogate (U+D800 to U+DFFF), which is not a character.",
            "channels",
        )
    scatter = livecells.scatter(body.channels)
    if scatter:
        raise ApiError(
            "invalid_setting",
            f"{', '.join(scatter)}: the live-cell filters take marker channels, not forward or "
            "side scatter, which the gate settings set.",
            "channels",
        )
    sent = {k: v for k, v in (("bins", body.bins), ("cofactor", body.cofactor)) if v is not None}
    filled = livecells.defaults() | sent
    lo, hi = caps.livecells_bins_min, caps.livecells_bins_max
    if not lo <= filled["bins"] <= hi:
        raise ApiError(
            "invalid_setting", f"bins is {filled['bins']}; this server takes {lo} to {hi}.", "bins"
        )
    cofactor = filled["cofactor"]
    with refusals():  # "auto" or a finite number from 0, by the package's own rule
        livecells.check_cofactor(cofactor)
    return {
        "pops": [sorted(set(p)) for p in body.pops],
        "channels": list(body.channels),
        "bins": int(filled["bins"]),
        "cofactor": cofactor if isinstance(cofactor, str) else float(cofactor),
    }


@router.post(SETS, status_code=202)
def post_livecells(gid: str, body: LivecellsRequest, request: Request, ws: WS):
    s, live = st(request), service(request)
    gate = done_gate(s, ws, gid)
    asked = normalized(body, s, s.gates.files(ws, gate))
    with ws.lock:  # the records, which other requests' threads change
        hit = live.matching(ws, gid, asked)
        if hit is not None:  # the cache: no new job, and no job room needed
            return started(s, live, ws, hit)
    spec = {
        "gates": str(s.gates.folder(ws, gid)),
        **{k: asked[k] for k in ("pops", "channels", "bins", "cofactor")},
        "cells_max": s.settings.caps.livecells_cells_max,
        "request": asked,
        "param_names": ["pops", "channels", "bins", "cofactor"],
    }
    # a new set is a job like a gate or a run: the pending, hourly, queue and day caps hold it,
    # and it counts toward the address's jobs in the hour (a hit found under the lock does not)
    ip = check_job_room(request)
    rec, new = live.create(ws, ip, gid, asked, spec)
    if new:
        s.limits.note_job(ip)
    return started(s, live, ws, rec)


@router.get(SETS + "/{lid}")
def get_set(gid: str, lid: str, request: Request, ws: WS):
    s, live = st(request), service(request)
    s.gates.record(ws, gid)
    return live.view(ws, live.record(ws, gid, lid))


@router.post(SETS + "/{lid}/counts")
def post_counts(gid: str, lid: str, body: CountsRequest, request: Request, ws: WS):
    """A plain def: FastAPI runs it in its threadpool, never on the event loop and never in the
    job pool, so a count does not wait behind a run."""
    s, live = st(request), service(request)
    caps = s.settings.caps
    s.limits.take_per_minute(
        "livecells_counts", ip_of(request), caps.livecells_counts_per_ip_minute, "counts"
    )
    s.gates.record(ws, gid)
    rec = live.record(ws, gid, lid)
    if live.status(ws, rec) != "done":
        raise ApiError("wrong_state", "The live-cells set is not done yet.")
    check_max("row_filters", len(body.row_filters), caps.livecells_filters_max)
    held = rec["request"]["channels"]
    for f in body.row_filters:
        if f.column not in held:
            raise ApiError(
                "invalid_setting",
                f"{f.column} is not one of this set's channels: {', '.join(held)}.",
                "row_filters",
            )
    specs = [filter_spec(f) for f in checked_filters(body.row_filters, row_filter)]
    return live.counts(ws, rec, specs)
