"""Demos: the manifest's listing, and loading a demo's files as uploads."""

from __future__ import annotations

import json

from dnapp.core.config import DEFAULT_DEMO_DIR
from testkit import API, assert_error

ZENODO = "https://doi.org/10.5281/zenodo.22079206"


def test_demos(make_client, fcs_202, tmp_path):
    import hashlib

    c = make_client(sub="d")
    demo = c.app.state.dn.settings.demo_dir
    assert c.get(f"{API}/demos").json() == {"demos": []}
    (demo / "data").mkdir(parents=True)
    (demo / "data" / "202.fcs").write_bytes(fcs_202.read_bytes())
    credit = "Kreutmair and Unger (2026), Zenodo. 50,000 events of its 202.fcs."
    manifest = {
        "schema": "datanuggets-demos/1",
        "demos": [
            {
                "id": "pbmc202",
                "title": "One PBMC sample",
                "kind": "fcs",
                "files": [
                    {
                        "name": "202.fcs",
                        "path": "data/202.fcs",
                        "bytes": fcs_202.stat().st_size,
                        "sha256": hashlib.sha256(fcs_202.read_bytes()).hexdigest(),
                        "url": None,
                    }
                ],
                "license": "CC BY 4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_url": ZENODO,
                "attribution": credit,
                "rows": 50_000,
                "description": "50,000 events, 5 channels.",
            },
            {
                "id": "gone",
                "title": "x",
                "kind": "fcs",
                "files": [{"name": "a.fcs", "path": "data/a.fcs"}],
            },
        ],
    }
    (demo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    demos = c.get(f"{API}/demos").json()["demos"]
    assert set(demos[0]) == {
        "id",
        "title",
        "kind",
        "files",
        "license",
        "license_url",
        "source_url",
        "attribution",
        "rows",
        "description",
        "available",
    }
    assert demos[0]["attribution"] == credit
    assert demos[0]["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert demos[1]["attribution"] is None and demos[1]["license_url"] is None
    assert [d["available"] for d in demos] == [True, False]
    r = c.post(f"{API}/demos/pbmc202/load")
    assert r.status_code == 201
    ups = r.json()["uploads"]
    assert len(ups) == 1 and ups[0]["demo"] == "pbmc202" and ups[0]["name"] == "202.fcs"
    assert ups[0]["kind"] == "fcs" and ups[0]["rows"] == 50_000
    assert_error(c.post(f"{API}/demos/gone/load"), 409, "wrong_state")
    assert_error(c.post(f"{API}/demos/nope/load"), 404, "not_found")


def test_the_shipped_demos_are_fcs_only():
    """The app is flow only, so the image ships the PBMC demo and no CSV one; its files sit in
    data/ only once fetched, so this reads the manifest, not the folder."""
    shipped = json.loads((DEFAULT_DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert [d["id"] for d in shipped["demos"]] == ["pbmc"]
    for d in shipped["demos"]:
        assert d["kind"] == "fcs" and all(f["path"].endswith(".fcs") for f in d["files"]), d["id"]
    assert not list((DEFAULT_DEMO_DIR / "data").glob("*.csv"))


def test_every_shipped_demo_carries_its_attribution():
    """CC BY needs the credit, the license and a link to it wherever the data are shown, and the
    demo card shows what /demos sends. The PBMC files are four of a Zenodo record's 44, so the
    credit names its authors and its DOI, and says the use is not endorsed."""
    shipped = json.loads((DEFAULT_DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))
    by_id = {d["id"]: d for d in shipped["demos"]}
    for d in by_id.values():
        assert d["attribution"] and d["source_url"], d["id"]
        if d["license"].startswith("CC BY"):
            assert d["license_url"].startswith("https://creativecommons.org/licenses/by/"), d["id"]
    pbmc = by_id["pbmc"]
    assert pbmc["license"] == "CC BY 4.0"
    assert pbmc["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert pbmc["source_url"] == ZENODO
    assert pbmc["attribution"].startswith("Stefanie Kreutmair and Susanne Unger (2026).")
    assert ZENODO in pbmc["attribution"] and "does not imply endorsement" in pbmc["attribution"]
