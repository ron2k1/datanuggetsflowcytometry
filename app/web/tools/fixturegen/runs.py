"""Every run's payloads and fixtures: manifests, plot, cells, compare, and the small run files.
r3 is a flow run whose run.json predates the Transform stage's record; r7 (flowauto.py) is one the
server's worker makes here with cofactor auto. The ids keep their gaps, because the docs and the
tests name them: r6 is the run POST /flow/runs hands back still running (jobs.py), and r7 comes
after it."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .common import CELLS, DEMO_GROUPS, iso, refuse_leaks, scrub_obj, write_json
from .flow import flow_payloads
from .flowauto import RID as AUTO_RID
from .flowauto import auto_run

SMALL_FILE = 120_000  # run files at most this big are copied for fixture-mode downloads


def file_kind(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower()
    return {"csv": "csv", "png": "png", "json": "json"}.get(ext, "txt")


def run_payloads(mock: Path, page: dict, work: Path, gates: dict) -> dict:
    """Builds r3 from the mockup's flow run, and r7 (cofactor auto) from a run the server's flow
    worker makes here on the same gate."""
    runs = {}
    pb = page["pbmc-run-1"]
    rj, plot, cells, compare, extra = flow_payloads(
        mock / "out" / "flow-run-1", mock / "fcs", pb["tsne"]["d2"], DEMO_GROUPS
    )
    if plot["nuggets"]["cluster"] != pb["cluster"]:
        raise SystemExit("flow: the stored t-SNE rows are not in the same nugget order")
    runs["r3"] = {
        "kind": "flow",
        "dir": mock / "out" / "flow-run-1",
        "rj": rj,
        "plot": plot,
        "cells": cells,
        "compare": compare,
        "extra": extra,
    }
    pops = [[int(x) for x in e.split(",")] for e in rj["pops"].split(";")]
    groups = [DEMO_GROUPS[g["name"]] for g in gates["files"]]
    runs[AUTO_RID] = auto_run(mock / "out" / "flow-gates-1", work, pops, groups)
    return runs


def write_runs(out: Path, work: Path, runs: dict, gates: dict):
    """Writes each run's fixtures; returns the creation times, the run summaries and the copied files."""
    # Run manifests, plot, cells, compare.
    titles = {
        "r3": "PBMC, 4 files · K=8",
        AUTO_RID: "PBMC, 4 files · K=8, cofactor auto",
    }
    sources = {"r3": "g1", AUTO_RID: "g1"}
    created = {}
    summaries, manifests = [], {}
    files_index = {}
    for rid in ("r3", AUTO_RID):
        R = runs[rid]
        rj = R["rj"]
        created[rid] = iso(rj["created"])
        wdir = work / rid
        if wdir.exists():
            shutil.rmtree(wdir)
        wdir.mkdir(parents=True)
        listing = {}
        for p in sorted(R["dir"].rglob("*")):
            if p.is_file():
                listing[p.name] = p
        for name, df in R["extra"].items():
            if name in listing:
                continue
            dest = wdir / name
            df.to_csv(dest, index=False)
            listing[name] = dest
        files = [
            {"name": n, "bytes": p.stat().st_size, "kind": file_kind(n)}
            for n, p in sorted(listing.items())
        ]
        small = []
        (out / "files" / rid).mkdir(parents=True, exist_ok=True)
        for n, p in sorted(listing.items()):
            if p.suffix in (".csv", ".json") and p.stat().st_size <= SMALL_FILE:
                text = p.read_text(encoding="utf-8")
                if n == "run.json":
                    text = json.dumps(scrub_obj(json.loads(text)), indent=2)
                refuse_leaks(text, f"{rid}/{n}")
                (out / "files" / rid / n).write_text(text, encoding="utf-8", newline="\n")
                small.append(n)
        files_index[rid] = small
        k = R["plot"]["k"]
        if "settings" in R:  # made here by the server's worker, with the settings it records
            settings = R["settings"]
            files = R["files"]
        else:
            s = rj["settings"]
            pops = [[int(x) for x in e.split(",")] for e in rj["pops"].split(";")]
            settings = {
                "gate_id": "g1",
                "pops": pops,
                "groups": [DEMO_GROUPS[g["name"]] for g in gates["files"]],
                "channels": s["channels"],
                "exclude_channels": s["exclude_channels"],
                "row_filters": [],
                "k": s["k"],
                "cofactor": s["cofactor"],
                "dn_num1": s["dn_num1"],
                "dn_num2": s["dn_num2"],
                "seed": s["seed"],
                "tsne": s["tsne"],
                "tsne_perplexity": s["tsne_perplexity"],
                "tsne_seed": s["tsne_seed"],
                "cells_per_file": CELLS,
            }
        manifests[rid] = {
            "id": rid,
            "kind": R["kind"],
            "status": "done",
            "created": created[rid],
            "title": titles[rid],
            "settings": settings,
            "record": scrub_obj(rj),
            "k": k,
            "clusters": R["plot"]["clusters"],
            "files": files,
            "warnings": R.get("warnings", []),
        }
        summaries.append(
            {
                "id": rid,
                "kind": R["kind"],
                "status": "done",
                "created": created[rid],
                "title": titles[rid],
                "source": sources[rid],
                "k": k,
            }
        )
        write_json(out / f"GET__runs__{rid}.json", manifests[rid])
        write_json(out / f"GET__runs__{rid}__plot.json", R["plot"])
        write_json(out / f"GET__runs__{rid}__cells.json", R["cells"])
        write_json(out / f"GET__runs__{rid}__compare.json", R["compare"])
    write_json(out / "GET__runs.json", {"runs": summaries})
    return (created, summaries, files_index)
