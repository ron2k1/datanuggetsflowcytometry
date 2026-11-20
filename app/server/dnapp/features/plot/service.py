"""The plot payload of a done run: its nuggets, clusters, PCA and t-SNE, read from the CSVs
and JSON the package wrote (pandas and the csv module). Nothing here computes what the
package computes."""

from __future__ import annotations

from pathlib import Path

from dnapp.core.config import MAX_PCS
from dnapp.core.errors import ApiError
from dnapp.core.package import flow
from dnapp.core.payload import ints, q, read_csv, short
from dnapp.core.run_outputs import clusters, flow_groups, group_order, kept_files


def _pca(out: Path, key_cols, key_frame) -> dict | None:
    """The plot payload's pca block from pca_scores/loadings/variance/center.csv, scores in
    key_frame's row order (matched on key_cols). scale is pca_center.csv's scale column, which a
    flow run with the Scale stage writes (a row x scores ((x - center) / scale) @ loadings), and
    None without it."""
    paths = [out / f"pca_{n}.csv" for n in ("scores", "loadings", "variance", "center")]
    if not all(p.is_file() for p in paths):
        return None
    sc, lo, var, cen = (read_csv(p) for p in paths)
    comps = [c for c in sc.columns if c.startswith("PC")][:MAX_PCS]
    merged = key_frame[key_cols].merge(sc[key_cols + comps], on=key_cols, how="left")
    return {
        "components": comps,
        "scores": q(merged[comps].to_numpy(dtype=float)),
        "variance": q(var["variance_ratio"].to_numpy(dtype=float)[: len(comps)]),
        "loadings": q(lo[comps].to_numpy(dtype=float)),
        "center": q(cen["center"].to_numpy(dtype=float)),
        "scale": q(cen["scale"].to_numpy(dtype=float)) if "scale" in cen.columns else None,
    }


def _fit(path: Path, key_cols, key_frame, dims: int) -> list | None:
    """A t-SNE CSV's first dims columns in key_frame's row order (matched on key_cols)."""
    if not path.is_file():
        return None
    merged = key_frame[key_cols].merge(read_csv(path), on=key_cols, how="left")
    return q(merged[[f"tsne{i + 1}" for i in range(dims)]].to_numpy(dtype=float))


def _tsne(out: Path, key_cols, key_frame) -> dict | None:
    """The plot payload's tsne block: d2 from tsne.csv, and d3 from tsne3d.csv, None for a run
    made before the package fitted a 3-D t-SNE or of fewer than three columns or nuggets."""
    d2 = _fit(out / "tsne.csv", key_cols, key_frame, 2)
    if d2 is None:
        return None
    return {"d2": d2, "d3": _fit(out / "tsne3d.csv", key_cols, key_frame, 3)}


def flow_nuggets(out: Path):
    import pandas as pd

    parts = []
    for f in sorted(out.glob("nuggets_*.csv"), key=lambda p: int(p.stem.split("_")[1])):
        df = read_csv(f)
        df.insert(0, "file_number", int(f.stem.split("_")[1]))
        parts.append(df)
    if not parts:
        raise ApiError("wrong_state", "This run has no nugget tables.")
    nug = pd.concat(parts, ignore_index=True)
    return nug[nug["weight"].to_numpy(dtype=float) > 0].reset_index(drop=True)


def flow_transform(record: dict) -> list[dict]:
    """A flow plot's transform list: the Transform stage as run.json records it, unrounded, then
    the Scale stage as {"name": "scale", "mean", "sd"} when run.json records one. The Transform
    stage is arcsinh with cofactor_from "auto" and cofactors, one per channel in the order of
    columns, with negative_fraction, negative_sd, floor and min_negative_fraction; or arcsinh
    with the one cofactor set; or, for a run.json of the earlier header rule, arcsinh with its
    one auto cofactor and the range it was picked by. none adds nothing; a run.json from before
    cofactor_from reads as set, and one from before the stage was recorded takes its settings'
    cofactor. The centers are in the Transform stage's units either way, since the CSVs undo the
    Scale stage, so "scale" says what the nuggets were clustered on, not how to read them."""
    t = flow.run_transform(record)
    steps = [t] if t.get("name") == "arcsinh" else []
    st = record.get("standardize")
    if isinstance(st, dict):
        steps.append({"name": "scale", "mean": q(st["mean"]), "sd": q(st["sd"])})
    return steps


def flow_plot(rid: str, out: Path, record: dict, settings: dict) -> dict:
    labels = list(record.get("labels", []))
    nug = flow_nuggets(out)
    cl = clusters(out)
    k = len(cl)
    kept = kept_files(out)
    groups = flow_groups(out, settings)
    return {
        "run_id": rid,
        "kind": "flow",
        "method": None,
        "columns": labels,
        "short_columns": [short(c) for c in labels],
        "transform": flow_transform(record),
        "k": k,
        "clusters": cl,
        "nuggets": {
            "n": len(nug),
            "nugget0": ints(nug["nugget0"]),
            "file": ints(nug["file_number"]),
            # a nugget's count of cells, exact: q's 4 digits would show 12,347 as 12,350
            "weight": nug["weight"].to_numpy(dtype=float).tolist(),
            "cluster": ints(nug["cluster"]),
            "centers": q(nug[labels].to_numpy(dtype=float)),
        },
        "pca": _pca(out, ["file_number", "nugget0"], nug),
        "tsne": _tsne(out, ["file_number", "nugget0"], nug),
        "files": [{"number": n, "name": name, "group": groups.get(n)} for n, name in kept],
        "groups": group_order(groups, [n for n, _ in kept]),
        "warnings": [],
    }
