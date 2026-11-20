"""The comparison payload of a done flow run: cluster counts and percents per file, the group
summary and the marker means, read from the CSVs the package wrote."""

from __future__ import annotations

from pathlib import Path

from dnapp.core.payload import ints, q, r4, read_csv
from dnapp.core.run_outputs import GROUP_TEXT, clusters, flow_groups, kept_files


def compare(rid: str, out: Path, record: dict, settings: dict) -> dict:
    s = read_csv(out / "cluster_summary.csv")
    labels = list(record.get("labels", []))
    cl = clusters(out)
    k = len(cl)
    kept = kept_files(out)
    groups = flow_groups(out, settings)
    counts = s.pivot(index="file_number", columns="cluster", values="cells")
    percent = s.pivot(index="file_number", columns="cluster", values="percent")
    order = [n for n, _ in kept]
    cols = list(range(1, k + 1))
    counts = counts.reindex(index=order, columns=cols).fillna(0)
    percent = percent.reindex(index=order, columns=cols)
    files = [
        {"number": n, "name": name, "group": groups.get(n), "cells": int(counts.loc[n].sum())}
        for n, name in kept
    ]
    # every group, in first appearance by file number (group_summary.csv's order), so a group
    # whose files were all left out keeps its place with 0 kept files; the reference is the group
    # of the first kept file, as the package picks it
    group_names = list(dict.fromkeys(groups[n] for n in sorted(groups))) if groups else None
    group_files = (
        [sum(1 for n in order if groups.get(n) == g) for g in group_names] if group_names else None
    )
    reference = groups.get(order[0]) if groups and order else None
    gs_path, gm_path, cm_path = (
        out / f for f in ("group_summary.csv", "group_markers.csv", "cluster_markers.csv")
    )
    group_summary = None
    log2fc_pseudocount = None
    if gs_path.is_file():
        g = read_csv(gs_path, text=GROUP_TEXT)
        group_summary = [
            {
                "group": str(r.group),
                "cluster": int(r.cluster),
                "samples": int(r.samples),
                "mean_percent": r4(r.mean_percent),
                "sd_percent": r4(r.sd_percent),
                "min_percent": r4(r.min_percent),
                "max_percent": r4(r.max_percent),
                "diff_vs_ref": r4(r.diff_vs_ref),
                "log2fc_vs_ref": r4(r.log2fc_vs_ref),
            }
            for r in g.itertuples(index=False)
        ]
        # the package writes the same value on every row; a run from before it has no column
        if "log2fc_pseudocount" in g.columns and len(g):
            log2fc_pseudocount = r4(g["log2fc_pseudocount"].iloc[0])
    cluster_markers = []
    if cm_path.is_file():
        m = read_csv(cm_path)
        means = m[labels].to_numpy(dtype=float)
        cluster_markers = [
            {"file_number": int(n), "cluster": int(c), "cells": int(cells_), "means": q(row)}
            for n, c, cells_, row in zip(m["file_number"], m["cluster"], m["cells"], means)
        ]
    group_markers = None
    if gm_path.is_file():
        g = read_csv(gm_path, text=GROUP_TEXT)
        group_markers = [
            {
                "group": str(group),
                "cluster": int(c),
                "channel": str(label),
                "samples": int(n),
                "mean": r4(mean),
                "diff_vs_ref": r4(diff),
            }
            for group, c, label, n, mean, diff in zip(
                g["group"], g["cluster"], g["label"], g["samples"], g["mean"], g["diff_vs_ref"]
            )
        ]
    return {
        "run_id": rid,
        "k": k,
        "clusters": cl,
        "files": files,
        "counts": [ints(counts.loc[n].to_numpy()) for n in order],
        "percent": [q(percent.loc[n].to_numpy(dtype=float)) for n in order],
        "groups": group_names,
        "group_files": group_files,
        "reference": reference,
        "log2fc_pseudocount": log2fc_pseudocount,
        "group_summary": group_summary,
        "channels": labels,
        "cluster_markers": cluster_markers,
        "group_markers": group_markers,
    }
