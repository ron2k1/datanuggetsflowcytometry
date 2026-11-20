"""Fetch and verify the demo files listed in app/demo/manifest.json.

A file whose manifest entry has a ``url`` is downloaded (the Docker build runs this); a file
without one is committed and only checked. Every file is checked against its ``bytes`` and
``sha256``, and a mismatch is an error: a bad download is deleted and the exit code is 1, so the
image build fails instead of shipping a wrong file.

Standard library only, so it runs before the app's environment exists.

    python app/scripts/fetch_demos.py                 # fetch what is missing, check everything
    python app/scripts/fetch_demos.py --check         # check only, never download
    python app/scripts/fetch_demos.py --only pbmc     # one demo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FetchConfig:
    timeout_s: float = 60.0  # per request (connect and each read)
    retries: int = 3
    backoff_s: float = 5.0  # multiplied by the attempt number
    chunk_bytes: int = 1 << 20
    user_agent: str = "datanuggets-app-fetch/1"
    demo_dir_env: str = "DN_DEMO_DIR"
    manifest_name: str = "manifest.json"
    manifest_schema: str = "datanuggets-demos/1"


CONFIG = FetchConfig()
DEFAULT_DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"


class FetchError(Exception):
    """A file is missing, has the wrong size or checksum, or could not be downloaded."""


def sha256_of(path: Path, chunk: int = CONFIG.chunk_bytes) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def matches(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256_of(path) == sha256


def download(url: str, dest: Path, size: int, sha256: str, cfg: FetchConfig = CONFIG) -> None:
    """Stream ``url`` to ``dest`` through ``dest.part``, checking size and sha256 on the way.

    The part file is deleted on any failure; ``dest`` only ever holds a verified file.
    """
    if not url.startswith("https://"):
        raise FetchError(f"{dest.name}: refusing a non-https url")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    for attempt in range(1, cfg.retries + 1):
        try:
            h = hashlib.sha256()
            got = 0
            req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent})
            with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp, part.open("wb") as out:
                while block := resp.read(cfg.chunk_bytes):
                    got += len(block)
                    if got > size:
                        raise FetchError(f"{dest.name}: more than the expected {size:,} bytes")
                    h.update(block)
                    out.write(block)
            if got != size:
                raise FetchError(f"{dest.name}: got {got:,} bytes, expected {size:,}")
            if h.hexdigest() != sha256:
                raise FetchError(f"{dest.name}: sha256 {h.hexdigest()} does not match {sha256}")
            os.replace(part, dest)
            return
        except FetchError:
            part.unlink(missing_ok=True)
            raise  # a wrong file is not retried: the source changed
        except OSError as e:  # URLError, timeouts and HTTP errors are OSErrors
            part.unlink(missing_ok=True)
            last = e
            if attempt < cfg.retries:
                print(f"  {dest.name}: attempt {attempt} failed ({type(e).__name__}), retrying")
                time.sleep(cfg.backoff_s * attempt)
    raise FetchError(f"{dest.name}: download failed after {cfg.retries} attempts ({last!r})")


def load_manifest(demo_dir: Path) -> dict:
    manifest = json.loads((demo_dir / CONFIG.manifest_name).read_text(encoding="utf-8"))
    if manifest.get("schema") != CONFIG.manifest_schema:
        raise FetchError(
            f"manifest schema is {manifest.get('schema')!r}, expected {CONFIG.manifest_schema!r}"
        )
    return manifest


def inside(base: Path, rel: str) -> Path:
    """``base / rel``, refusing anything that resolves outside ``base``."""
    path = (base / rel).resolve()
    if not path.is_relative_to(base.resolve()):
        raise FetchError(f"{rel}: path leaves the demo folder")
    return path


def run(demo_dir: Path, only: set[str] | None, check_only: bool) -> int:
    manifest = load_manifest(demo_dir)
    ids = {d["id"] for d in manifest["demos"]}
    if only and (unknown := only - ids):
        raise FetchError(f"unknown demo id(s): {', '.join(sorted(unknown))}")
    errors = 0
    for demo in manifest["demos"]:
        if only and demo["id"] not in only:
            continue
        for f in demo["files"]:
            dest = inside(demo_dir, f["path"])
            label = f"{demo['id']}/{f['name']}"
            try:
                if matches(dest, f["bytes"], f["sha256"]):
                    print(f"ok       {label}")
                    continue
                if check_only or not f.get("url"):
                    state = "wrong size or sha256" if dest.exists() else "missing"
                    raise FetchError(f"{label}: {state}")
                print(f"fetching {label} ({f['bytes']:,} bytes)")
                download(f["url"], dest, f["bytes"], f["sha256"])
                print(f"ok       {label}")
            except FetchError as e:
                errors += 1
                print(f"ERROR    {e}", file=sys.stderr)
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--demo-dir",
        type=Path,
        default=None,
        help=f"folder holding {CONFIG.manifest_name} (default ${CONFIG.demo_dir_env} or app/demo)",
    )
    p.add_argument("--only", nargs="+", metavar="ID", help="only these demo ids")
    p.add_argument("--check", action="store_true", help="verify only; never download")
    a = p.parse_args(argv)
    demo_dir = a.demo_dir or Path(os.environ.get(CONFIG.demo_dir_env) or DEFAULT_DEMO_DIR)
    try:
        return run(demo_dir, set(a.only) if a.only else None, a.check)
    except (FetchError, OSError, ValueError, KeyError) as e:
        print(f"ERROR    {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
