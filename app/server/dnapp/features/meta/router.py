"""GET /health and GET /config (contract section 3.2)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from dnapp.core.deps import st
from dnapp.core.package import flow, runtime
from dnapp.features.meta.service import app_version, docker_commands

router = APIRouter()


@router.get("/health")
def health(request: Request):
    s = st(request)
    return {
        "status": "ok",
        "mode": s.settings.mode,
        "version": app_version(),
        "jobs": s.jobs.counts(),
    }


@router.get("/config")
def config(request: Request):
    s = st(request)
    caps = s.settings.caps
    trial = s.settings.trial
    package_version = runtime.package_version()
    return {
        "mode": s.settings.mode,
        "version": app_version(),
        "package_version": package_version,
        "caps": caps.public() if trial else None,
        "ttl": {"idle_s": caps.ttl_idle_s, "max_s": caps.ttl_max_s} if trial else None,
        "defaults": {
            "gate": flow.gate_defaults(),
            "cluster": flow.cluster_defaults(),
            # how the cluster default's cofactor "auto" picks each channel's from the run's cells
            "cofactor_auto": flow.cofactor_rule(),
        },
        "limits": {"k_max": caps.k_max},
        **docker_commands(package_version, s.settings.docker_command),
        "storage_note": s.settings.storage_note,
    }
