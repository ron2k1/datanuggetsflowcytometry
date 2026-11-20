"""Reading a finished run's folder, the format the package writes and more than one feature reads:
the files it offers, its clusters, and a flow run's files and groups. Nothing here computes what
the package computes."""

from __future__ import annotations

from pathlib import Path

from dnapp.core.payload import read_csv

KINDS = {".csv": "csv", ".png": "png", ".json": "json", ".txt": "txt"}
SKIP_FILES = ("INCOMPLETE.txt",)
# columns of groups.csv, group_summary.csv and group_markers.csv that hold names the user or the
# files chose, read as the text written (read_csv's text)
GROUP_TEXT = ("group", "file", "label")


# ---- files --------------------------------------------------------------------------------


def run_files(out: Path) -> dict[str, str]:
    """name -> path relative to out for every file a finished run offers: its own files, then
    plots/*.png under their own names (prefixed plots- when that name is taken)."""
    files: dict[str, str] = {}
    if not out.is_dir():
        return files
    for p in sorted(out.iterdir()):
        if p.is_file() and p.name not in SKIP_FILES and p.suffix.lower() in KINDS:
            files[p.name] = p.name
    plots = out / "plots"
    if plots.is_dir():
        for p in sorted(plots.iterdir()):
            if p.is_file() and p.suffix.lower() in KINDS:
                name = p.name if p.name not in files else f"plots-{p.name}"
                files[name] = f"plots/{p.name}"
    return files


def file_entries(out: Path) -> list[dict]:
    return [
        {"name": name, "bytes": (out / rel).stat().st_size, "kind": KINDS[Path(rel).suffix.lower()]}
        for name, rel in run_files(out).items()
    ]


# ---- clusters -----------------------------------------------------------------------------


def clusters(out: Path) -> list[dict]:
    """The run's clusters from its cluster_colors.csv, which numbers clusters and parents from 1."""
    df = read_csv(out / "cluster_colors.csv")
    return [
        {"cluster": int(c), "parent": int(p), "color": str(col)}
        for c, p, col in zip(df["cluster"], df["parent"], df["color"])
    ]


# ---- a flow run's files and groups --------------------------------------------------------


def flow_groups(out: Path, settings: dict) -> dict[int, str]:
    """file_number -> group, from groups.csv, or from the settings when it is missing."""
    path = out / "groups.csv"
    if path.is_file():
        g = read_csv(path, text=GROUP_TEXT)
        return {int(n): str(v) for n, v in zip(g["file_number"], g["group"])}
    groups = settings.get("groups")
    return {i + 1: str(v) for i, v in enumerate(groups)} if groups else {}


def kept_files(out: Path) -> list[tuple[int, str]]:
    s = read_csv(out / "cluster_summary.csv")
    seen = {}
    for n, name in zip(s["file_number"], s["file"]):
        seen.setdefault(int(n), str(name))
    return sorted(seen.items())


def group_order(groups: dict[int, str], kept: list[int]) -> list[str] | None:
    if not groups:
        return None
    order: list[str] = []
    for n in kept:
        g = groups.get(n)
        if g is not None and g not in order:
            order.append(g)
    return order
