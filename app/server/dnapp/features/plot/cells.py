"""The cells payload of a done run: its sampled cells (cells.csv), thinned to the server's
total cap."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from dnapp.core.errors import ApiError
from dnapp.core.payload import ints, q, read_csv


def _thin(n: int, cap: int) -> np.ndarray:
    """Evenly spaced rows when n passes cap, so the payload stays bounded."""
    if n <= cap:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, cap).round().astype(int))


def cells(rid: str, out: Path, record: dict, cap_per_file: int, cap_total: int) -> dict:
    path = out / "cells.csv"
    if not path.is_file():
        raise ApiError("wrong_state", "This run has no sampled cells (cells.csv).")
    df = read_csv(path)
    df = df.iloc[_thin(len(df), cap_total)].reset_index(drop=True)
    pcs = [c for c in df.columns if c.startswith("PC") and c[2:].isdigit()]
    columns = list(record.get("labels", []))
    return {
        "run_id": rid,
        "n": len(df),
        "cap_per_file": int(cap_per_file),
        "columns": columns,
        "file": ints(df["file_number"]),
        "row0": ints(df["event0"]),
        "nugget0": ints(df["nugget0"]),
        "cluster": ints(df["cluster"].to_numpy(dtype=int)),
        "pca": q(df[pcs].to_numpy(dtype=float)) if pcs else None,
        "values": q(df[columns].to_numpy(dtype=float)),
    }
