"""The request bodies of POST /flow/gates/{gid}/livecells and of its counts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictFloat

from dnapp.core.filters import Filter


class LivecellsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pops: list[list[int]]
    channels: list[str]
    bins: int | None = None
    # "auto" (the default: each channel's cofactor a run clustering the kept cells would pick) or
    # a number from 0 for every channel; StrictFloat takes an integer but not true or false,
    # which a plain float reads as 1 and 0
    cofactor: StrictFloat | str | None = None


class CountsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_filters: list[Filter] = []
