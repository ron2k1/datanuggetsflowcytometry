"""How numbers and tables become JSON: floats to SIG_DIGITS significant digits (NaN, infinity and
missing as null), arrays as nested lists, and the readers for the CSV and JSON files the package
writes."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from dnapp.core.config import SIG_DIGITS


def r4(v) -> float | None:
    """A float to SIG_DIGITS significant digits; NaN, infinity and missing become None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return float(f"{f:.{SIG_DIGITS}g}")


def q(a) -> list:
    """An array (any depth) as nested lists of r4 floats."""
    arr = np.asarray(a, dtype=float)
    if arr.ndim == 0:
        return r4(arr)
    flat = [r4(v) for v in arr.ravel().tolist()]
    return np.array(flat, dtype=object).reshape(arr.shape).tolist()


def ints(a) -> list[int]:
    return [int(v) for v in np.asarray(a).ravel().tolist()]


def short(name: str) -> str:
    """'CD38 (FJComp-APC-Cy5.5-A)' -> 'CD38'."""
    return name.split(" (")[0]


def read_csv(path: Path, text: tuple[str, ...] = ()):
    """A CSV the package wrote, as a pandas DataFrame (pandas loads on first use).

    The columns named in text keep each cell as the text in the file: pandas' defaults read a
    group called None, NA or nan as missing and 01 as the number 1, and all are valid names. With
    text, only an empty cell is missing in any column (the package writes NaN as an empty cell, so
    its numeric columns read the same either way)."""
    import pandas as pd

    if not text:
        return pd.read_csv(path)
    return pd.read_csv(path, dtype={c: str for c in text}, keep_default_na=False, na_values=[""])


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
