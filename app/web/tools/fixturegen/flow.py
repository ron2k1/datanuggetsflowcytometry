"""The flow run's plot, cells and compare payloads, from its CSVs and the FCS files it read."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from datanuggets import wpca
from datanuggets.colors import PARENT_K
from datanuggets.projection import component_signs
from datanuggets_flow.compare import group_markers, group_summary
from datanuggets_flow.pipeline import read_fcs

from dnapp.features.plot.service import flow_transform

from .colors import clusters_block
from .common import CELLS, MAX_PCS, q, short, sig

# The group_summary payload fields, as the server reads them from group_summary.csv.
GS_KEYS = (
    "group",
    "cluster",
    "samples",
    "mean_percent",
    "sd_percent",
    "min_percent",
    "max_percent",
    "diff_vs_ref",
    "log2fc_vs_ref",
)


def flow_payloads(run: Path, fcs_dir: Path, tsne_d2, groups: dict):
    rid = "r3"
    rj = json.loads((run / "run.json").read_text(encoding="utf-8"))
    s = rj["settings"]
    labels, channels = rj["labels"], rj["channels"]
    cofactor, seed, k = float(s["cofactor"]), int(s["seed"]), int(s["k"])
    sel = pd.read_csv(run / "selection.csv")
    files = sel[sel["kept"] > 0][["file_number", "file", "kept"]].to_dict("records")
    parts = []
    for f in files:
        df = pd.read_csv(run / f"nuggets_{f['file_number']}.csv")
        df["file"] = int(f["file_number"])
        parts.append(df)
    nug = pd.concat(parts, ignore_index=True)
    use = nug["weight"].to_numpy(float) > 0
    centers = nug[labels].to_numpy(float)[use]
    weight = nug["weight"].to_numpy(float)[use]
    cluster = nug["cluster"].to_numpy()[use]
    fileno = nug["file"].to_numpy()[use]
    pca = wpca(centers, wrow=weight)
    signs = component_signs(pca.rotation)
    rot_all = np.asarray(pca.rotation) * signs
    scores_all = np.asarray(pca.x) * signs
    center = np.asarray(pca.center, float)
    lam = np.nan_to_num(np.asarray(pca.sdev, float) ** 2)
    ratio = lam / lam.sum()
    m = min(MAX_PCS, len(labels))
    pcs = [f"PC{j}" for j in range(1, m + 1)]
    rot = rot_all[:, :m]
    err = np.max(np.abs((centers - center) @ rot - scores_all[:, :m])) / np.max(
        np.abs(scores_all[:, :m])
    )
    if err > 1e-9:
        raise SystemExit(f"flow: projecting centers misses the scores by {err:g}")
    print(f"flow: project(centers) equals the signed wpca scores (max rel diff {err:.1e})")
    if len(tsne_d2) != len(centers):
        raise SystemExit("flow: the stored t-SNE does not match the nuggets in use")
    # A flow run's colour families are cuts of its own tree (datanuggets.colors.tree_parents),
    # which this builder does not have; up to PARENT_K clusters each is its own family anyway.
    if k > PARENT_K:
        raise SystemExit(f"flow: K={k} needs the run's tree for its colour families")
    clusters = clusters_block(k, list(range(k)))
    names = {int(f["file_number"]): f["file"] for f in files}
    group_list = list(dict.fromkeys(groups[names[n]] for n in sorted(names)))
    plot = {
        "run_id": rid,
        "kind": "flow",
        "method": None,
        "columns": labels,
        "short_columns": [short(c) for c in labels],
        # as the server reads this run.json, written before the Transform stage was recorded:
        # its settings' cofactor, as set
        "transform": flow_transform(rj),
        "k": k,
        "clusters": clusters,
        "nuggets": {
            "n": len(centers),
            "nugget0": nug["nugget0"].to_numpy()[use].tolist(),
            "file": fileno.tolist(),
            "weight": q(weight),
            "cluster": cluster.tolist(),
            "centers": q(centers),
        },
        "pca": {
            "components": pcs,
            "scores": q(scores_all[:, :m]),
            "variance": q(ratio[:m]),
            "loadings": q(rot),
            "center": q(center),
        },
        "tsne": {"d2": q(np.asarray(tsne_d2))},
        "files": [
            {"number": n, "name": names[n], "group": groups[names[n]]} for n in sorted(names)
        ],
        "groups": group_list,
        "warnings": [],
    }

    # Every kept event's values, from the FCS file itself, for cells.csv and cluster_markers.csv.
    cell_rows, marker_rows, nug_check = [], [], 0.0
    cpf = int(CELLS)
    for f in files:
        num = int(f["file_number"])
        arr, pnn, _ = read_fcs(fcs_dir / f["file"])
        idx = [pnn.index(c) for c in channels]
        ev = pd.read_csv(run / f"events_{num}.csv").sort_values("event0").reset_index(drop=True)
        if len(ev) != int(f["kept"]):
            raise SystemExit(
                f"flow: events_{num}.csv has {len(ev)} rows, selection.csv kept {f['kept']}"
            )
        xv = arr[ev["event0"].to_numpy()][:, idx]
        xv = np.arcsinh(xv / cofactor) if cofactor else xv
        # Each nugget's center is the mean of its own events (center_method "mean").
        nf = nug[nug["file"] == num].set_index("nugget0")
        by_nug = pd.DataFrame(xv).groupby(ev["nugget0"].to_numpy()).mean()
        ref = nf.loc[by_nug.index, labels].to_numpy(float)
        nug_check = max(
            nug_check,
            float(np.max(np.abs(by_nug.to_numpy() - ref) / np.maximum(1e-12, np.abs(ref)))),
        )
        for c in range(1, k + 1):
            mask = ev["cluster"].to_numpy() == c
            n_c = int(mask.sum())
            means = xv[mask].mean(axis=0) if n_c else np.full(len(labels), np.nan)
            wn = nf[nf["cluster"] == c]
            wn = wn[wn["weight"] > 0]
            if n_c:
                wmean = (wn[labels].to_numpy(float) * wn["weight"].to_numpy(float)[:, None]).sum(
                    0
                ) / wn["weight"].sum()
                rel = np.max(np.abs(wmean - means) / np.maximum(1e-12, np.abs(means)))
                if rel > 1e-6:
                    raise SystemExit(
                        f"flow: file {num} cluster {c}: weighted nugget mean misses the cell mean by {rel:g}"
                    )
            marker_rows.append(
                {
                    "file_number": num,
                    "file": f["file"],
                    "cluster": c,
                    "cells": n_c,
                    **{lab: means[j] for j, lab in enumerate(labels)},
                }
            )
        ncell = min(cpf, len(ev))
        pick = np.sort(np.random.default_rng([seed, num]).choice(len(ev), ncell, replace=False))
        xs = xv[pick]
        ps = (xs - center) @ rot
        for r, j in enumerate(pick):
            cell_rows.append(
                (
                    num,
                    int(ev["event0"][j]),
                    int(ev["nugget0"][j]),
                    int(ev["cluster"][j]),
                    ps[r],
                    xs[r],
                )
            )
    print(
        f"flow: nugget centers equal the mean of their events (max rel diff {nug_check:.1e}); "
        "weighted nugget means equal direct cell means per file and cluster"
    )
    cells = {
        "run_id": rid,
        "n": len(cell_rows),
        "cap_per_file": cpf,
        "columns": labels,
        "file": [r[0] for r in cell_rows],
        "row0": [r[1] for r in cell_rows],
        "nugget0": [r[2] for r in cell_rows],
        "cluster": [r[3] for r in cell_rows],
        "pca": q(np.array([r[4] for r in cell_rows])),
        "values": q(np.array([r[5] for r in cell_rows])),
    }
    cells_table = pd.DataFrame(
        {
            "file_number": cells["file"],
            "event0": cells["row0"],
            "nugget0": cells["nugget0"],
            "cluster": cells["cluster"],
        }
    )
    pa, va = np.array([r[4] for r in cell_rows]), np.array([r[5] for r in cell_rows])
    for j, pc in enumerate(pcs):
        cells_table[pc] = pa[:, j]
    for j, lab in enumerate(labels):
        cells_table[lab] = va[:, j]

    summ = pd.read_csv(run / "cluster_summary.csv")
    markers = pd.DataFrame(marker_rows)
    kept_nums = sorted(names)
    counts = [
        [
            int(summ[(summ.file_number == n) & (summ.cluster == c)]["cells"].sum())
            for c in range(1, k + 1)
        ]
        for n in kept_nums
    ]
    percent = [
        [
            float(summ[(summ.file_number == n) & (summ.cluster == c)]["percent"].sum())
            for c in range(1, k + 1)
        ]
        for n in kept_nums
    ]
    for n, row in zip(kept_nums, counts):
        got = markers[markers.file_number == n].sort_values("cluster")["cells"].tolist()
        if got != row:
            raise SystemExit(
                f"flow: file {n} cell counts from events_{n}.csv differ from cluster_summary.csv"
            )
    # The group tables are the package's own (datanuggets_flow.compare) on this run's cluster
    # summary and the per-file marker means above, so a rebuild follows its formulas, the log2FC
    # pseudocount among them. Its reference is the group of the lowest-numbered kept file.
    by_number = {n: groups[names[n]] for n in kept_nums}
    gs = group_summary(summ[summ.file_number.isin(kept_nums)], by_number)
    gm = group_markers(markers, by_number, channels, labels)
    reference = group_list[0]
    if not (gs.loc[gs.group == reference, "diff_vs_ref"] == 0).all():
        raise SystemExit(f"flow: the package's reference group is not {reference}")
    # As the server sends them: the kept files in each group, and the package's pseudocount (half
    # a cell per file) from its log2fc_pseudocount column, null for a table without that column.
    group_files = [sum(1 for n in kept_nums if groups[names[n]] == g) for g in group_list]
    pc = sig(gs["log2fc_pseudocount"].iloc[0]) if "log2fc_pseudocount" in gs else None
    compare = {
        "run_id": rid,
        "k": k,
        "clusters": clusters,
        "files": [
            {"number": n, "name": names[n], "group": groups[names[n]], "cells": int(sum(counts[i]))}
            for i, n in enumerate(kept_nums)
        ],
        "counts": counts,
        "percent": q(percent),
        "groups": group_list,
        "group_files": group_files,
        "reference": reference,
        "log2fc_pseudocount": pc,
        "group_summary": [
            {key: r[key] if key == "group" else sig(r[key]) for key in GS_KEYS}
            for r in gs.to_dict("records")
        ],
        "channels": labels,
        "cluster_markers": [
            {
                "file_number": int(r["file_number"]),
                "cluster": int(r["cluster"]),
                "cells": int(r["cells"]),
                "means": q([r[lab] for lab in labels]),
            }
            for _, r in markers.iterrows()
        ],
        "group_markers": [
            {
                "group": r["group"],
                "cluster": int(r["cluster"]),
                "channel": r["label"],
                "samples": int(r["samples"]),
                "mean": sig(r["mean"]),
                "diff_vs_ref": sig(r["diff_vs_ref"]),
            }
            for _, r in gm.iterrows()
        ],
    }
    extra = {
        "cluster_colors.csv": pd.DataFrame(
            {
                "cluster": range(1, k + 1),
                "parent": [c["parent"] for c in clusters],
                "color": [c["color"] for c in clusters],
            }
        ),
        "cluster_markers.csv": markers,
        "pca_scores.csv": pd.concat(
            [
                pd.DataFrame({"file_number": fileno, "nugget0": plot["nuggets"]["nugget0"]}),
                pd.DataFrame(
                    scores_all, columns=[f"PC{j + 1}" for j in range(scores_all.shape[1])]
                ),
            ],
            axis=1,
        ),
        "pca_loadings.csv": pd.concat(
            [
                pd.DataFrame({"channel": channels, "label": labels}),
                pd.DataFrame(rot_all, columns=[f"PC{j + 1}" for j in range(rot_all.shape[1])]),
            ],
            axis=1,
        ),
        "pca_variance.csv": pd.DataFrame(
            {
                "component": [f"PC{j + 1}" for j in range(len(lam))],
                "sdev": np.asarray(pca.sdev, float),
                "variance_ratio": ratio,
            }
        ),
        "pca_center.csv": pd.DataFrame({"channel": channels, "label": labels, "center": center}),
        "tsne.csv": pd.DataFrame(
            {
                "file_number": fileno,
                "nugget0": plot["nuggets"]["nugget0"],
                "tsne1": np.asarray(tsne_d2)[:, 0],
                "tsne2": np.asarray(tsne_d2)[:, 1],
            }
        ),
        "cells.csv": cells_table,
        "groups.csv": pd.DataFrame(
            {
                "file_number": kept_nums,
                "file": [names[n] for n in kept_nums],
                "group": [groups[names[n]] for n in kept_nums],
                "kept": ["true"] * len(kept_nums),
            }
        ),
        # As the package writes them: its reference column is the reference group's mean.
        "group_summary.csv": gs,
        "group_markers.csv": gm,
    }
    return rj, plot, cells, compare, extra
