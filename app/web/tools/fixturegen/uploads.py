"""Upload records, read from the public FCS files."""

from __future__ import annotations

from pathlib import Path

from datanuggets_flow.pipeline import read_fcs, read_ranges

from .common import sig, write_json


def fcs_upload(path: Path, uid: str, demo: str, created: str) -> dict:
    arr, pnn, pns = read_fcs(path)
    # Each channel's $PnR range as the package's auto cofactor decodes it, unrounded, as the
    # server's describe_fcs gives it.
    _, ranges = read_ranges(path)
    if len(ranges) != len(pnn):
        raise SystemExit(f"{path.name}: {len(ranges)} ranges for {len(pnn)} channels")
    cols = [
        {
            "name": n,
            "label": s or "",
            "numeric": True,
            "min": sig(arr[:, j].min()),
            "max": sig(arr[:, j].max()),
            "mean": sig(arr[:, j].mean()),
            "missing": 0,
            "range": ranges[j],
        }
        for j, (n, s) in enumerate(zip(pnn, pns))
    ]
    return {
        "id": uid,
        "name": path.name,
        "kind": "fcs",
        "bytes": path.stat().st_size,
        "rows": int(arr.shape[0]),
        "columns": cols,
        "created": created,
        "demo": demo,
    }


def write_uploads(out: Path, mock: Path, gates: dict, t_ws: str):
    """Writes the upload fixtures; returns the uploads, their ids by file name, and uploads by name."""
    # The ids start at u3, as the gate, the docs and the tests name them.
    up_ids, uploads = {}, []
    for i, g in enumerate(gates["files"]):
        uid = f"u{3 + i}"
        up_ids[g["name"]] = uid
        uploads.append(fcs_upload(mock / "fcs" / g["name"], uid, "pbmc", t_ws))
    for up in uploads:
        write_json(out / f"GET__uploads__{up['id']}.json", up)
    write_json(out / "GET__uploads.json", {"uploads": uploads})
    # What POST /uploads answers for the first demo file.
    write_json(out / "POST__uploads.json", uploads[0])
    by_name = {u["name"]: u for u in uploads}
    return (uploads, up_ids, by_name)
