"""GET /config (trial and local) and GET /health."""

from __future__ import annotations

from pathlib import Path

from datanuggets_flow.settings import ClusterSettings, GateSettings

from dnapp.core.package import runtime
from dnapp.core.package.flow import cofactor_rule
from dnapp.features.meta.service import docker_commands

from .common import CELLS, write_json


def write_config(out: Path) -> None:
    """Writes both configs and the health answer."""
    # Config and health.
    cluster_defaults = {k: v for k, v in ClusterSettings().to_dict().items() if k != "n_jobs"}
    cluster_defaults.update({"row_filters": [], "groups": None, "cells_per_file": CELLS})
    MB, GB = 1_000_000, 1_000_000_000
    caps = {
        "upload_fcs_bytes": 200 * MB,
        "workspace_bytes": GB,
        "fcs_events": 3_000_000,
        "fcs_files_per_gate": 8,
        "k_max": 100,
        "dn_num1_max": 10_000,
        "dn_num2_max": 2_000,
        "pooled_nuggets_max": 8_000,
        "cells_per_file_max": 2_000,
        "cells_max_total": 50_000,
        "runs_per_workspace": 10,
        "jobs_pending_per_ip": 2,
        "jobs_per_ip_hour": 20,
        "workspaces_per_ip_hour": 5,
        "heavy_budget_s_per_day": 14_400,
        "job_timeout_s": 900,
        "queue_max": 8,
        "ttl_idle_s": 21_600,
        "ttl_max_s": 86_400,
        "sweep_s": 600,
        "min_free_bytes": GB,
        # contract-livecells.md section 2.4, trial column
        "livecells_channels_max": 8,
        "livecells_bins_min": 8,
        "livecells_bins_max": 512,
        "livecells_per_gate": 8,
        "livecells_cells_max": 6_000_000,
        "livecells_filters_max": 16,
        "livecells_counts_per_ip_minute": 120,
        "livecells_memory_sets": 2,
    }
    package_version = runtime.package_version()  # the server's own, so the two can't differ
    base_cfg = {
        "version": "0.1.0",
        "package_version": package_version,
        "defaults": {
            "gate": GateSettings().to_dict(),
            "cluster": cluster_defaults,
            "cofactor_auto": cofactor_rule(),
        },
        "limits": {"k_max": 100},
        **docker_commands(package_version),  # the server's own, at the package's version
    }
    write_json(
        out / "GET__config.json",
        {
            "mode": "trial",
            **base_cfg,
            "caps": caps,
            "ttl": {"idle_s": 21_600, "max_s": 86_400},
            "storage_note": "Files stay in a temporary workspace and are deleted within 24 hours. Do not upload identifiable patient data.",
        },
    )
    write_json(
        out / "GET__config.local.json",
        {
            "mode": "local",
            **base_cfg,
            "caps": None,
            "ttl": None,
            "storage_note": "Files stay on this computer.",
        },
    )
    write_json(
        out / "GET__health.json",
        {"status": "ok", "mode": "trial", "version": "0.1.0", "jobs": {"running": 0, "queued": 0}},
    )
