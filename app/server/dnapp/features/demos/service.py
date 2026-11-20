"""The demo datasets this server ships: DN_DEMO_DIR/manifest.json and the files it names."""

from __future__ import annotations

import json
from pathlib import Path

from dnapp.core.errors import not_found


def manifest(root: Path) -> list[dict]:
    path = root / "manifest.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("demos", [])


def available(root: Path, demo: dict) -> bool:
    return all((root / f["path"]).is_file() for f in demo.get("files", []))


def find(root: Path, demo_id: str) -> dict:
    """The demo's manifest entry, or 404."""
    demo = next((d for d in manifest(root) if d.get("id") == demo_id), None)
    if demo is None:
        raise not_found("demo")
    return demo


def listing(root: Path) -> list[dict]:
    return [
        {
            "id": d["id"],
            "title": d.get("title"),
            "kind": d.get("kind"),
            "files": [{"name": f["name"], "bytes": f.get("bytes")} for f in d.get("files", [])],
            "license": d.get("license"),
            "license_url": d.get("license_url"),
            "source_url": d.get("source_url"),
            "attribution": d.get("attribution"),  # the credit the license asks for, shown as is
            "rows": d.get("rows"),
            "description": d.get("description"),
            "available": available(root, d),
        }
        for d in manifest(root)
    ]
