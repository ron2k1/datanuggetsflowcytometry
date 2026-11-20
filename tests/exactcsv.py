"""Reading back a CSV the package wrote with every float exactly as written. pandas 3.0.6, the
version uv.lock pins, misreads some correctly written shortest-repr floats with its default
parser, one of a flow run's nugget centers by 2 ulps. float_precision="round_trip" reads them
exactly but pandas 3.1 deprecates it, and engine="python" goes through the same conversion as the
default. Reading the cells as text and converting them with .astype(float) is exact on 3.0.6 and
3.1 and warns on neither."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_exact(path: Path) -> pd.DataFrame:
    """The table pd.read_csv reads from path, with each float column parsed again from the file's
    text. Integer and text columns are as pd.read_csv gives them, and an empty cell in a float
    column is NaN either way."""
    frame = pd.read_csv(path)
    text = pd.read_csv(path, dtype=str)
    for name in frame.columns:
        if pd.api.types.is_float_dtype(frame[name]):
            frame[name] = text[name].astype(float)
    return frame
