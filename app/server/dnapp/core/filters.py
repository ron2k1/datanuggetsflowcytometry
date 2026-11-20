"""The row filter every request that filters rows takes (flow runs, live-cells counts), and its
check against the package's own parser."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dnapp.core.errors import ApiError

Number = float | int
FilterValue = Number | str | list[Number | str]


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    op: Literal["<", "<=", ">", ">=", "==", "!=", "between", "in"]
    value: FilterValue


def filter_json(f: Filter) -> dict:
    for v in f.value if isinstance(f.value, list) else [f.value]:
        if isinstance(v, str) and any(ch in v for ch in ",[]"):
            raise ApiError(
                "invalid_setting",
                "Filter values cannot contain commas or square brackets.",
                "row_filters",
            )
    return f.model_dump()


def checked_filters(filters: list[Filter], build: Callable[[dict], object]) -> list[dict]:
    """Each filter's JSON, after build (the package's parser) accepted it; its ValueError is a
    422 on row_filters."""
    out = []
    for f in filters:
        data = filter_json(f)
        try:
            build(data)
        except ValueError as e:
            raise ApiError("invalid_setting", str(e), "row_filters") from None
        out.append(data)
    return out
