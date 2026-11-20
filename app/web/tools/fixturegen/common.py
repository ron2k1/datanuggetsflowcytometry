"""Shared by every part: the values the contract pins, scrubbing, the API's float rounding, writing."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

MAX_PCS = 5
CELLS = 2000  # contract: FLOW_CELLS_PER_FILE
DEMO_GROUPS = {"190.fcs": "Demo A", "193.fcs": "Demo A", "199.fcs": "Demo B", "223.fcs": "Demo B"}
WIN_PATH = re.compile(r'[A-Za-z]:\\(?:[^\\\n"]+\\)*([^\\\n"]*)')
# A fixture must not tell where it was built, and nothing below names that machine. It looks for a
# home folder in a Windows or POSIX path (with up to four separators, as JSON escapes them, the
# way scripts/check_dist.py looks), any drive path, a path turned into a folder name, the running
# user's own name, and words kept only as SHA-256 digests: the development setup's account name
# and its profile, sync, project and tool folder names. A hit names its kind, never the value
HOME_PATH = re.compile(
    r"(?i:\b[a-z]:[\\/]{1,4}users[\\/]{1,4}[^\\/\s\"']+)|(?<![\w.~-])/(?:Users|home)/[^/\s\"']+"
)
DRIVE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\|/(?!/))")
FOLDER_PATH = re.compile(r"(?i)(?<![a-z0-9])[a-z]--users-")
DENY = frozenset(
    {
        "155521b950c68ca76d57111cd3377198d205b0a7667b89d5222f08afc67d6961",
        "4dcf07fc1ad313cf7b0df6bebc270538d66310d49a03460423fd2d42514a69fc",
        "5417dcf3515cce99d317b6d1e22915f647f195e0f1cd9578534cf18a6d353895",
        "567781541aa1d043041ec08be14e1c519629784e3952d0d079ac87640242ba5e",
        "fcbd50491bdd4883db7305d646eb5a3ee769f69e26e5148d6d5ffa3e69afdcaf",
    }
)
HOME_NAME = Path.home().name.lower()
TOKEN = re.compile(r"[A-Za-z0-9]+")
PART = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")  # camelCase parts, to find a word inside a name


def scrub(s: str) -> str:
    return WIN_PATH.sub(lambda m: m.group(1), s)


def scrub_obj(v):
    if isinstance(v, str):
        return scrub(v)
    if isinstance(v, list):
        return [scrub_obj(x) for x in v]
    if isinstance(v, dict):
        return {k: scrub_obj(x) for k, x in v.items()}
    return v


def sig(v):
    """Four significant digits, as the API sends floats; NaN and missing become null."""
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    v = float(v)
    if not math.isfinite(v):
        return None
    return float(f"{v:.4g}")


def q(a):
    if isinstance(a, np.ndarray):
        a = a.tolist()
    if isinstance(a, (list, tuple)):
        return [q(x) for x in a]
    return sig(a)


def iso(text: str) -> str:
    return datetime.fromisoformat(text).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def short(name: str) -> str:
    return name.split(" (")[0].removeprefix("feature:")


def leak(text: str) -> str | None:
    """The kind of thing in text that would tell where the fixtures were built, or None."""
    for kind, rx in (
        ("a home-folder path", HOME_PATH),
        ("a drive path", DRIVE_PATH),
        ("a path made into a folder name", FOLDER_PATH),
    ):
        if rx.search(text):
            return kind
    words = {w.lower() for rx in (TOKEN, PART) for w in rx.findall(text)}
    if len(HOME_NAME) >= 4 and HOME_NAME in words:
        return "the user's own name"
    for w in words:
        if not w.isdigit():
            d = hashlib.sha256(w.encode()).hexdigest()
            if d in DENY:
                return f"a denied word (sha256 {d[:12]})"
    return None


def refuse_leaks(text: str, what: str) -> None:
    kind = leak(text)
    if kind:
        raise SystemExit(f"refusing to write {what}: it holds {kind}")


def write_json(path: Path, obj) -> None:
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    refuse_leaks(text, path.name)
    path.write_text(text, encoding="utf-8", newline="\n")


def log_lines(path: Path) -> list[str]:
    lines = [
        scrub(x).rstrip() for x in path.read_text(encoding="utf-8", errors="replace").splitlines()
    ]
    return [x for x in lines if x.strip()]
