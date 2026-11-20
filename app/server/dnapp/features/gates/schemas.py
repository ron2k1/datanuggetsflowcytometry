"""The request body of POST /flow/gates."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class GateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uploads: list[str]
    settings: dict = {}
