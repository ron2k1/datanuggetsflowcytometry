"""Download the large (1M+ events) public demo sets listed in app/demo/large.json, on demand.

They are never committed and never copied into the Docker image: run this on the machine that
will analyse them, then upload the files in the app (local mode has no size caps).

    python app/scripts/fetch_demo_large.py --set nkg2a          # 9 FCS files, 196.6 MB

Every file is checked against the size and sha256 recorded in large.json; a mismatch deletes
the download and exits 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# fetch_demos.py sits beside this file; added explicitly so `python -I` (no script dir on
# sys.path) works too
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_demos import FetchError, download, matches

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LargeConfig:
    catalog: Path = REPO / "app" / "demo" / "large.json"
    catalog_schema: str = "datanuggets-large-demos/1"
    out_dir: Path = REPO / "tmp" / "demo-large"  # tmp/ is gitignored


CONFIG = LargeConfig()


def load_catalog(path: Path) -> dict:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if catalog.get("schema") != CONFIG.catalog_schema:
        raise FetchError(
            f"{path.name}: schema {catalog.get('schema')!r}, expected {CONFIG.catalog_schema!r}"
        )
    return catalog


def fetch_set(entry: dict, out: Path) -> None:
    folder = out / entry["id"]
    for f in entry["files"]:
        dest = folder / f["name"]
        if matches(dest, f["bytes"], f["sha256"]):
            print(f"ok       {entry['id']}/{f['name']} (already here)")
        else:
            print(f"fetching {entry['id']}/{f['name']} ({f['bytes']:,} bytes)")
            download(f["url"], dest, f["bytes"], f["sha256"])
            print(f"ok       {entry['id']}/{f['name']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--set",
        dest="sets",
        nargs="+",
        required=True,
        metavar="ID",
        help="set ids from large.json (nkg2a) or all",
    )
    p.add_argument("--out", type=Path, default=CONFIG.out_dir, help=f"default {CONFIG.out_dir}")
    a = p.parse_args(argv)
    try:
        catalog = load_catalog(CONFIG.catalog)
        by_id = {s["id"]: s for s in catalog["sets"]}
        wanted = list(by_id) if "all" in a.sets else a.sets
        if unknown := [s for s in wanted if s not in by_id]:
            raise FetchError(f"unknown set(s): {', '.join(unknown)}; known: {', '.join(by_id)}")
        for sid in wanted:
            fetch_set(by_id[sid], a.out)
            print(f"license  {sid}: {by_id[sid]['license']}. {by_id[sid]['attribution']}")
        return 0
    except (FetchError, OSError, ValueError, KeyError) as e:
        print(f"ERROR    {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
