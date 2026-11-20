"""The request body of POST /datasets."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: list[str]
    name: str  # a blank one removes the set's name
