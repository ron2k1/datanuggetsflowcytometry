"""POST /datasets (contract section 3.3): sets or removes the name of one channel set. The server
checks the request and keeps the name; it does not group uploads, which the page does."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Request

from dnapp.core.config import (
    DATASET_CHANNEL_CHARS,
    DATASET_CHANNELS_BYTES,
    DATASET_CHANNELS_MAX,
    DATASET_NAME_MAX,
)
from dnapp.core.deps import WS, st
from dnapp.core.errors import ApiError
from dnapp.core.limits import check_max
from dnapp.features.datasets.schemas import DatasetRequest
from dnapp.features.datasets.service import set_name

router = APIRouter()
# Unicode's control characters (Cc), the line and paragraph separators (Zl, Zp) and the bidi
# controls (Bidi_Control), which reorder the text around a name where it is shown
CONTROL = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u2028\u2029\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
# half a UTF-16 surrogate pair: a JSON escape can carry one, but UTF-8 cannot encode it, so a
# record that held one failed every answer that lists it, GET /workspace's included
LONE = re.compile(r"[\ud800-\udfff]")


def checked_channels(channels: list[str]) -> list[str]:
    """The channels sorted; 422 on channels unless they are 1 to DATASET_CHANNELS_MAX non-empty
    names, each once, at most DATASET_CHANNEL_CHARS long and with no character LONE matches, in a
    list json.dumps writes in at most DATASET_CHANNELS_BYTES. Names are compared as sent, and a
    control character is kept: the names are an upload's own, and flowio reads a $PnN that is not
    UTF-8 as ISO-8859-1, so a Windows-1252 dash (0x96) is U+0096."""
    if not channels:
        raise ApiError("invalid_setting", "List at least one channel.", "channels")
    check_max("channels", len(channels), DATASET_CHANNELS_MAX)
    for c in channels:
        if not c:
            raise ApiError("invalid_setting", "A channel name cannot be empty.", "channels")
        if len(c) > DATASET_CHANNEL_CHARS:
            raise ApiError(
                "invalid_setting",
                f"A channel name is {len(c)} characters long; this server allows at most "
                f"{DATASET_CHANNEL_CHARS}.",
                "channels",
            )
        if LONE.search(c):
            raise ApiError(
                "invalid_setting",
                "A channel name has a lone surrogate (U+D800 to U+DFFF), which is not a character.",
                "channels",
            )
    if len(set(channels)) != len(channels):
        raise ApiError("invalid_setting", "List each channel once.", "channels")
    size = len(json.dumps(channels))  # as meta.json keeps it, each non-ASCII character escaped
    if size > DATASET_CHANNELS_BYTES:
        raise ApiError(
            "invalid_setting",
            f"The channel list is {size} bytes as JSON; this server allows at most "
            f"{DATASET_CHANNELS_BYTES}.",
            "channels",
        )
    return sorted(channels)


def checked_name(name: str) -> str:
    """The name trimmed ("" removes the set's name); 422 on name when it is longer than
    DATASET_NAME_MAX or holds a character CONTROL or LONE matches."""
    name = name.strip()
    if len(name) > DATASET_NAME_MAX:
        raise ApiError(
            "invalid_setting",
            f"The name is {len(name)} characters long; a dataset name is at most "
            f"{DATASET_NAME_MAX}.",
            "name",
        )
    if CONTROL.search(name):
        raise ApiError(
            "invalid_setting",
            "The name has a control character, such as a tab, a line break or a text direction "
            "mark.",
            "name",
        )
    if LONE.search(name):
        raise ApiError(
            "invalid_setting",
            "The name has a lone surrogate (U+D800 to U+DFFF), which is not a character.",
            "name",
        )
    return name


@router.post("/datasets")
def post_datasets(body: DatasetRequest, request: Request, ws: WS):
    channels, name = checked_channels(body.channels), checked_name(body.name)
    return {"datasets": set_name(ws, channels, name, st(request).uploads)}
