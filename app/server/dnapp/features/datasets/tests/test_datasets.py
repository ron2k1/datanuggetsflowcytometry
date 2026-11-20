"""POST /datasets: the name of one channel set, kept in the workspace's meta.json and listed by
GET /workspace. The set is matched as a set, a blank name removes its record, and an id is never
used twice. No upload is needed: a name may be given to a set no upload has. The channels are
those of the repo's own FCS files, and the uploads are built from 202's recorded events."""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest

from dnapp.core.config import (
    DATASET_CHANNEL_CHARS,
    DATASET_CHANNELS_BYTES,
    DATASET_CHANNELS_MAX,
    DATASET_NAME_MAX,
    DATASETS_MAX,
)
from dnapp.core.datasets import colour_set
from dnapp.core.workspace import META
from testkit import API, FLOW, assert_error, channel_list, upload, watch

AF700, BV510, SPARK = "FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"
PANEL = sorted([AF700, BV510, SPARK])  # 202.fcs's colour channels
# four more colour channels of 202's panel, as the PBMC demo's 190.fcs in the fixtures names them
MORE = ["FJComp-BV421-A", "FJComp-BV480-A", "FJComp-BV570-A", "FJComp-FITC-A"]
LONG = (AF700 * 10)[: DATASET_CHANNEL_CHARS + 1]
# what a trimmed name may not hold: control characters (Unicode Cc), the line and paragraph
# separators and the bidi controls
REFUSED = [*"\t\n\x00\x1f\x7f\x85\x9f\u2028\u2029\u061c\u200e\u200f"]
REFUSED += [*map(chr, range(0x202A, 0x202F)), *map(chr, range(0x2066, 0x206A))]
CONTROL_MESSAGE = (
    "The name has a control character, such as a tab, a line break or a text direction mark."
)
# half a UTF-16 surrogate pair, which a JSON escape can carry and UTF-8 cannot encode
LONE = [chr(0xD800), chr(0xDFFF)]
NAME_LONE = "The name has a lone surrogate (U+D800 to U+DFFF), which is not a character."
CHANNEL_LONE = "A channel name has a lone surrogate (U+D800 to U+DFFF), which is not a character."
JSON = {"content-type": "application/json"}


@pytest.fixture(scope="module")
def less_202(tmp_path_factory) -> Path:
    """202's recorded events without its last channel, FJComp-Spark Blue-A: another dataset."""
    import flowio

    path = tmp_path_factory.mktemp("less") / "less.fcs"
    with np.load(FLOW / "202.npz") as gate, np.load(FLOW / "202_fluor.npz") as fluor:
        events = np.column_stack((gate["fsc"], gate["ssc"], fluor["fluor"][:, :2]))
        names = ["FSC-A", "SSC-A", *fluor["pnn"].tolist()[:2]]
    with path.open("wb") as handle:
        flowio.create_fcs(handle, events.ravel(), names)
    return path


def name(client, channels, text):
    return client.post(f"{API}/datasets", json={"channels": channels, "name": text})


def named(client, channels, text) -> list[dict]:
    r = name(client, channels, text)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"datasets"}
    return r.json()["datasets"]


def listed(client) -> list[dict]:
    return client.get(f"{API}/workspace").json()["datasets"]


def test_a_name_is_kept_with_its_channels_sorted(make_client):
    c = make_client()
    assert listed(c) == []
    got = named(c, [SPARK, AF700, BV510], "PBMC panel")
    assert got == [{"id": "d1", "channels": PANEL, "name": "PBMC panel"}]
    assert listed(c) == got
    assert named(c, [AF700], "One")[-1] == {"id": "d2", "channels": [AF700], "name": "One"}


def test_a_known_set_in_any_order_has_its_name_replaced(make_client):
    c = make_client()
    named(c, PANEL, "PBMC panel")
    got = named(c, [BV510, SPARK, AF700], "  Panel B  ")
    assert got == [{"id": "d1", "channels": PANEL, "name": "Panel B"}]  # trimmed, one record
    got = named(c, [AF700, BV510], "Two")  # a subset is another set
    assert [(d["id"], d["name"]) for d in got] == [("d1", "Panel B"), ("d2", "Two")]


def test_a_blank_name_removes_the_record_and_its_id_is_not_used_again(make_client):
    c = make_client()
    named(c, PANEL, "PBMC panel")
    rest = named(c, MORE, "More")[1:]
    assert named(c, [SPARK, BV510, AF700], " \t ") == rest == listed(c)
    assert named(c, PANEL, "") == rest  # a set with no name: nothing to remove
    assert named(c, PANEL, "Again")[-1] == {"id": "d3", "channels": PANEL, "name": "Again"}


def test_the_answer_is_read_before_the_workspace_lock_is_let_go(make_client):
    """POST /datasets lists the names as it left them, under the workspace's lock, so another
    request's thread cannot add or remove one while they are read."""
    c = make_client()
    records = watch(c.app.state.dn.workspaces.local(), "datasets")
    named(c, PANEL, "PBMC panel")
    assert records.free and not any(records.free), records.free


def test_the_longest_name_and_channel_name_are_kept(make_client):
    c = make_client()
    text, channel = "N" * DATASET_NAME_MAX, LONG[:-1]
    assert named(c, [channel], f" {text} ") == [{"id": "d1", "channels": [channel], "name": text}]


def test_the_longest_channel_list_is_kept(make_client):
    """DATASET_CHANNELS_BYTES bounds the list as json.dumps writes it, each character outside
    ASCII as an escape, so the records meta.json is rewritten with on every change stay small.
    Fifty channels named like 202's take under 2,000 bytes."""
    channels = channel_list(DATASET_CHANNELS_BYTES)
    assert named(make_client(), channels, "Wide")[0]["channels"] == sorted(channels)
    assert len(json.dumps([f"{AF700[:-2]} {i}-A" for i in range(50)])) < 2_000


def test_a_channel_name_is_kept_as_an_upload_has_it(make_client, fcs_202, tmp_path):
    """flowio reads a TEXT segment that is not UTF-8 as ISO-8859-1, so a $PnN written in
    Windows-1252 with an en dash (0x96) holds U+0096, a control character. The upload keeps it,
    the page sends it with the dataset's other colour channels, and its name is kept. Any
    character a name may not hold is kept in a channel name, so long as it is a character."""
    raw = fcs_202.read_bytes()
    assert raw.count(BV510.encode()) == 1
    path = tmp_path / "cp1252.fcs"
    path.write_bytes(raw.replace(BV510.encode(), b"FJComp\x96BV510-A"))
    c = make_client()
    r = upload(c, path)
    assert r.status_code == 201, r.text
    channels = colour_set(r.json())
    assert channels == sorted([AF700, "FJComp\x96BV510-A", SPARK])
    assert named(c, channels, "Panel") == [{"id": "d1", "channels": channels, "name": "Panel"}]
    odd = [f"FJComp-BV{ch}510-A" for ch in REFUSED]
    assert named(c, odd, "Odd")[-1]["channels"] == sorted(odd)


def test_a_name_keeps_other_format_characters_and_loses_separators_at_its_ends(make_client):
    """str.strip() trims a line or paragraph separator at either end; a zero-width joiner, as in
    an emoji sequence, is no control character."""
    got = named(make_client(), PANEL, "\u2028Panel\u200dB\u2029")
    assert got[0]["name"] == "Panel\u200dB"


@pytest.mark.parametrize(
    ("body", "param", "message"),
    [
        ({"channels": [], "name": "x"}, "channels", "List at least one channel."),
        (
            {"channels": [AF700] * (DATASET_CHANNELS_MAX + 1), "name": "x"},
            "channels",
            (
                f"channels is {DATASET_CHANNELS_MAX + 1}; this server allows at most "
                f"{DATASET_CHANNELS_MAX}."
            ),
        ),
        ({"channels": [AF700, ""], "name": "x"}, "channels", "A channel name cannot be empty."),
        (
            {"channels": [AF700, LONG], "name": "x"},
            "channels",
            (
                f"A channel name is {DATASET_CHANNEL_CHARS + 1} characters long; this server "
                f"allows at most {DATASET_CHANNEL_CHARS}."
            ),
        ),
        *(
            ({"channels": [AF700, f"FJComp-BV{ch}510-A"], "name": "x"}, "channels", CHANNEL_LONE)
            for ch in LONE
        ),
        ({"channels": [AF700, BV510, AF700], "name": "x"}, "channels", "List each channel once."),
        (
            {"channels": channel_list(DATASET_CHANNELS_BYTES + 1), "name": "x"},
            "channels",
            (
                f"The channel list is {DATASET_CHANNELS_BYTES + 1} bytes as JSON; this server "
                f"allows at most {DATASET_CHANNELS_BYTES}."
            ),
        ),
        (
            {"channels": PANEL, "name": "N" * (DATASET_NAME_MAX + 1)},
            "name",
            (
                f"The name is {DATASET_NAME_MAX + 1} characters long; a dataset name is at most "
                f"{DATASET_NAME_MAX}."
            ),
        ),
        *(({"channels": PANEL, "name": f"Panel{ch}B"}, "name", CONTROL_MESSAGE) for ch in REFUSED),
        ({"channels": PANEL, "name": "\u200ePanel"}, "name", CONTROL_MESSAGE),  # not trimmed
        *(({"channels": PANEL, "name": f"Panel{ch}B"}, "name", NAME_LONE) for ch in LONE),
        ({"channels": PANEL}, "name", None),
        ({"channels": PANEL, "name": None}, "name", None),
        ({"channels": AF700, "name": "x"}, "channels", None),
        ({"channels": [AF700, 7], "name": "x"}, "channels", None),
        # the body is exactly {channels, name}: an unknown field is named, a non-object is not
        ({"channels": PANEL, "name": "x", "colour": "red"}, "colour", None),
        *(
            ({"channels": PANEL, "name": "x", k: 1}, k, f"{k}: Extra inputs are not permitted")
            for k in ("body", "query", "path")
        ),
        ([PANEL, "x"], None, None),
        ("x", None, None),
    ],
)
def test_a_bad_request_is_refused_and_changes_nothing(make_client, body, param, message):
    """The body goes as json.dumps writes it, so a lone surrogate goes as the escape a client's
    JSON can carry. A refused body leaves the names, and GET /workspace, as they were."""
    c = make_client()
    kept = named(c, PANEL, "Kept")
    sent = c.post(f"{API}/datasets", content=json.dumps(body), headers=JSON)
    err = assert_error(sent, 422, "invalid_setting", param)
    if message is not None:
        assert err["message"] == message
    assert listed(c) == kept


def test_a_workspace_keeps_at_most_datasets_max_names(make_client):
    """Here no upload has any of the sets, so the name past the cap makes room by removing them
    all; a known set is still renamed at the cap."""
    c = make_client()
    channels = [*PANEL, *MORE]
    sets = [list(s) for n in range(1, len(channels) + 1) for s in combinations(channels, n)]
    assert len(sets) > DATASETS_MAX
    for s in sets[:DATASETS_MAX]:
        assert name(c, s, "x").status_code == 200
    assert len(listed(c)) == DATASETS_MAX
    assert named(c, sets[0], "Renamed")[0]["name"] == "Renamed"
    last = sorted(sets[DATASETS_MAX])
    got = named(c, last, "One more")
    assert got == [{"id": f"d{DATASETS_MAX + 1}", "channels": last, "name": "One more"}]


def test_at_the_cap_the_names_of_sets_no_upload_has_go_first(
    make_client, fcs_202, less_202, monkeypatch
):
    """At DATASETS_MAX a new name first removes the names of the sets no FCS upload has, which
    the page never shows, and is refused only when every name left is an upload's set. A refusal
    removes nothing, and once an upload is deleted its set's name is one that can go."""
    from dnapp.features.datasets import service

    monkeypatch.setattr(service, "DATASETS_MAX", 2)
    c = make_client()
    ids = [upload(c, path).json()["id"] for path in (fcs_202, less_202)]
    named(c, [MORE[0]], "Nobody's")
    named(c, PANEL, "202")
    got = named(c, PANEL[:2], "Less")  # less.fcs's set; Nobody's goes
    assert [(d["id"], d["name"]) for d in got] == [("d2", "202"), ("d3", "Less")]
    err = assert_error(name(c, MORE, "More"), 422, "invalid_setting", "name")
    assert err["message"] == (
        "This workspace holds 2 dataset names, the most it can; remove one first."
    )
    assert listed(c) == got
    assert c.delete(f"{API}/uploads/{ids[1]}").status_code == 204
    got = named(c, MORE, "More")
    assert [(d["id"], d["name"]) for d in got] == [("d2", "202"), ("d4", "More")]


def test_names_survive_a_local_restart(make_client):
    got = named(make_client("local", sub="same"), PANEL, "PBMC panel")
    assert listed(make_client("local", sub="same")) == got


def test_a_trial_workspace_has_its_own_names(make_client):
    c = make_client("trial")
    assert_error(name(c, PANEL, "Mine"), 401, "no_workspace")
    c.get(f"{API}/workspace")
    assert named(c, PANEL, "Mine")[0]["name"] == "Mine"
    c.cookies.clear()
    assert c.get(f"{API}/workspace").json()["datasets"] == []  # a new workspace


def test_delete_workspace_clears_the_names(make_client):
    c = make_client()
    named(c, PANEL, "PBMC panel")
    assert c.delete(f"{API}/workspace").status_code == 204
    assert listed(c) == []
    assert named(c, PANEL, "PBMC panel")[0]["id"] == "d2"  # ids are never reused


def test_a_meta_json_from_before_datasets_reads_as_no_names(make_client):
    path = make_client(sub="old").app.state.dn.workspaces.local().path / META
    meta = json.loads(path.read_text(encoding="utf-8"))
    assert meta["datasets"] == {}
    del meta["datasets"]
    path.write_text(json.dumps(meta), encoding="utf-8")
    c = make_client(sub="old")
    assert listed(c) == []
    assert named(c, PANEL, "PBMC panel")[0]["id"] == "d1"
