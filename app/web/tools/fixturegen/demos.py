"""GET /demos and the PBMC demo's load, over the uploads the fixtures already hold."""

from __future__ import annotations

import json
from pathlib import Path

from dnapp.core.config import DEFAULT_DEMO_DIR

from .common import write_json

# the license and the credit come from the shipped manifest, so the fixture page shows what the
# server sends
CREDIT = ("license", "license_url", "attribution")


def write_demos(out: Path, by_name: dict, gates: dict) -> None:
    """Writes the demo list and each load."""
    manifest = json.loads((DEFAULT_DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))
    shipped = {d["id"]: d for d in manifest["demos"]}

    def demo_files(names):
        return [{"name": n, "bytes": by_name[n]["bytes"]} for n in names]

    def credit(demo_id):
        return {k: shipped[demo_id].get(k) for k in CREDIT}

    demos = [
        {
            "id": "pbmc",
            "title": "PBMC flow cytometry",
            "kind": "fcs",
            "files": demo_files([g["name"] for g in gates["files"]]),
            **credit("pbmc"),
            "source_url": "https://zenodo.org/records/22079206",
            "rows": sum(by_name[g["name"]]["rows"] for g in gates["files"]),
            "description": "4 of the record's 44 FCS files, 39 channels each.",
            "available": True,
        },
    ]
    write_json(out / "GET__demos.json", {"demos": demos})
    write_json(
        out / "POST__demos__pbmc__load.json",
        {"uploads": [by_name[g["name"]] for g in gates["files"]]},
    )
