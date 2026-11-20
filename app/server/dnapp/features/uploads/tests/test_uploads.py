"""Uploads: FCS files streamed to disk with server-made ids and names, their column stats and
ranges, and every refusal: 411, 413, 415, 422 and 507, all on the 202 FCS file."""

from __future__ import annotations

import httpx
import numpy as np

from testkit import API, FLOW, assert_error, upload, watch

UPLOAD_KEYS = {"id", "name", "kind", "bytes", "rows", "columns", "created", "demo"}
COLUMN_KEYS = {"name", "label", "numeric", "min", "max", "mean", "missing", "range"}


def test_fcs_upload(make_client, fcs_202):
    c = make_client()
    r = upload(c, fcs_202)
    assert r.status_code == 201, r.text
    u = r.json()
    assert set(u) == UPLOAD_KEYS
    assert u["id"] == "u1" and u["name"] == "202.fcs" and u["kind"] == "fcs"
    assert u["bytes"] == fcs_202.stat().st_size and u["rows"] == 50_000 and u["demo"] is None
    names = [col["name"] for col in u["columns"]]
    assert names[:2] == ["FSC-A", "SSC-A"] and len(names) == 5
    with np.load(FLOW / "202.npz") as g, np.load(FLOW / "202_fluor.npz") as f:
        fsc = g["fsc"].astype(float)
        pns = f["pns"].tolist()
    assert [col["label"] for col in u["columns"]] == ["", "", *pns]
    assert u["columns"][0]["max"] == float(f"{fsc.max():.4g}")
    assert all(col["missing"] == 0 and col["numeric"] for col in u["columns"])
    # each column has its $PnR range too (flowio writes 262144), unrounded
    assert all(set(col) == COLUMN_KEYS for col in u["columns"])
    assert [col["range"] for col in u["columns"]] == [262144.0] * 5
    assert c.get(f"{API}/uploads/u1").json() == u
    assert c.get(f"{API}/uploads").json() == {"uploads": [u]}
    # the CSV row pages left with CSV uploads; the route is now just an unknown one
    assert_error(c.get(f"{API}/uploads/u1/rows"), 404, "not_found")


def test_fcs_upload_ranges_from_the_header(make_client, fcs_202, tmp_path):
    """range is $PnR as the package's read_ranges decodes it: the header's number, with None
    for a channel whose $PnR is not a usable range (0 here, which a linear channel's events
    still read with)."""
    raw = bytearray(fcs_202.read_bytes())
    at = raw.index(b"$P3R")
    end = raw.index(raw[at - 1 : at], at + 4)  # the TEXT delimiter after the keyword
    stop = raw.index(raw[at - 1 : at], end + 1)
    raw[end + 1 : stop] = b"0" * (stop - end - 1)  # same length, so the offsets still hold
    broken = tmp_path / "pnr.fcs"
    broken.write_bytes(bytes(raw))
    u = upload(make_client(), broken).json()
    assert [col["range"] for col in u["columns"]] == [262144.0, 262144.0, None, 262144.0, 262144.0]


def test_safe_names_are_server_made_and_unique(make_client, fcs_202):
    c = make_client()
    a = upload(c, fcs_202, name="../../evil name.fcs").json()
    b = upload(c, fcs_202, name="../../evil name.fcs").json()
    d = upload(c, fcs_202, name=".hidden.fcs").json()
    assert a["name"] == "evil_name.fcs" and b["name"] == "evil_name-2.fcs"
    assert d["name"] == "hidden.fcs"
    assert a["id"] == "u1" and b["id"] == "u2"


def test_an_upload_reads_the_uploads_under_the_workspace_lock(make_client, fcs_202):
    """An upload goes over the uploads for their names and, with a workspace cap, their demo
    bytes, beside a delete or a DELETE /workspace in the threadpool, so it holds the workspace's
    lock while it does."""
    c = make_client("trial")
    c.get(f"{API}/workspace")
    (ws,) = c.app.state.dn.workspaces.all()
    assert c.app.state.dn.settings.caps.workspace_bytes is not None
    records = watch(ws, "uploads")
    for _ in range(2):
        assert upload(c, fcs_202).status_code == 201
    assert records.free and not any(records.free), records.free


def test_refusals(make_client, fcs_202, tmp_path):
    c = make_client()
    # a CSV is refused like any other type that is not FCS
    for name in ("202.txt", "iris.csv", "202.CSV"):
        err = assert_error(upload(c, fcs_202, name=name), 415, "unsupported_type")
        assert err["message"] == "Upload an .fcs file.", name
    fake = tmp_path / "fake.fcs"
    fake.write_bytes(b"NOTFCS" + b"\0" * 100)
    assert_error(upload(c, fake), 415, "unsupported_type")
    empty = tmp_path / "empty.fcs"
    empty.write_bytes(b"")
    assert_error(upload(c, empty), 415, "unsupported_type")  # too short to hold the magic
    r = c.post(f"{API}/uploads", content=b"x", headers={"content-type": "text/plain"})
    assert_error(r, 415, "unsupported_type")
    r = c.post(f"{API}/uploads", files={"other": ("a.fcs", fcs_202.read_bytes())})
    assert_error(r, 422, "invalid_setting", "file")
    # nothing half-written is left behind
    ws = c.app.state.dn.workspaces.local()
    assert [p.name for p in ws.dir("uploads").iterdir()] == []
    # the magic passes, so this one is stored before the reader refuses it; the test below
    # checks it is removed
    assert_error(upload(c, _unreadable_fcs(tmp_path)), 422, "unreadable_file")


def _unreadable_fcs(tmp_path):
    broken = tmp_path / "broken.fcs"
    broken.write_bytes(b"FCS3.1" + b"\0" * 100)  # the magic, then no header to read
    return broken


def test_an_unreadable_fcs_file_is_removed(make_client, tmp_path):
    """A file the reader refuses after it was stored goes with its folder, as one the receiver
    refuses does."""
    c = make_client()
    assert_error(upload(c, _unreadable_fcs(tmp_path)), 422, "unreadable_file")
    ws = c.app.state.dn.workspaces.local()
    assert [p.name for p in ws.dir("uploads").iterdir()] == []


def _no_length_request(client, body: bytes, boundary: str):
    def gen():
        yield body

    return client.post(
        f"{API}/uploads",
        content=gen(),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )


def _multipart(name: str, data: bytes) -> tuple[bytes, str]:
    req = httpx.Request("POST", "http://x/", files={"file": (name, data)})
    body = req.read()
    return body, req.headers["content-type"].split("boundary=")[1]


def test_trial_needs_content_length(make_client, fcs_202):
    c = make_client("trial")
    c.get(f"{API}/workspace")
    body, boundary = _multipart("202.fcs", fcs_202.read_bytes())
    assert_error(_no_length_request(c, body, boundary), 411, "length_required")
    local = make_client("local", sub="l")
    assert _no_length_request(local, body, boundary).status_code == 201


def test_trial_size_caps(make_client, fcs_202):
    c = make_client("trial", caps={"upload_fcs_bytes": 1000})
    c.get(f"{API}/workspace")
    err = assert_error(upload(c, fcs_202), 413, "too_large")
    assert err["message"] == "FCS uploads are limited to 1 KB."  # not "0 MB"
    ws = c.app.state.dn.workspaces.all()[0]
    assert list(ws.dir("uploads").iterdir()) == []  # refused on its length, before a folder
    events = make_client("trial", caps={"fcs_events": 100}, sub="e")
    events.get(f"{API}/workspace")
    assert_error(upload(events, fcs_202), 413, "too_large")
    ws = events.app.state.dn.workspaces.all()[0]
    assert list(ws.dir("uploads").iterdir()) == []  # stored, read, then removed
    # room for the first file but not for a second
    full = make_client("trial", caps={"workspace_bytes": fcs_202.stat().st_size * 3 // 2}, sub="w")
    full.get(f"{API}/workspace")
    assert upload(full, fcs_202).status_code == 201
    assert_error(upload(full, fcs_202), 413, "too_large")
    local = make_client("local", sub="loc")
    for _ in range(3):
        assert upload(local, fcs_202).status_code == 201


def test_the_size_cap_message_names_the_cap(make_client, fcs_202):
    """The Content-Length check refuses before reading the body, naming the cap in MB from 1 MB
    up and in KB below it, to one decimal place."""
    body, boundary = _multipart("202.fcs", fcs_202.read_bytes())
    big = str(250 * 1_000_000)
    for sub, caps, said in (
        ("d", None, "200 MB"),  # the trial default
        ("f", {"upload_fcs_bytes": 1_500_000}, "1.5 MB"),
        ("r", {"upload_fcs_bytes": 1_234_567}, "1.2 MB"),
        ("k", {"upload_fcs_bytes": 500}, "0.5 KB"),
        ("n", {"upload_fcs_bytes": 999_701}, "999.7 KB"),
    ):
        c = make_client("trial", sub=sub, caps=caps)
        c.get(f"{API}/workspace")
        r = c.post(
            f"{API}/uploads",
            content=body,
            headers={
                "content-type": f"multipart/form-data; boundary={boundary}",
                "content-length": big,
            },
        )
        assert assert_error(r, 413, "too_large")["message"] == f"FCS uploads are limited to {said}."


def test_streamed_size_check_without_trusting_length(make_client, fcs_202):
    """The Content-Length check allows 64 KB for the multipart framing around the file, so a
    file a little over the cap passes it and is still cut off while streaming, with the same
    message."""
    cap = fcs_202.stat().st_size - 1000
    c = make_client("trial", caps={"upload_fcs_bytes": cap})
    c.get(f"{API}/workspace")
    body, boundary = _multipart("202.fcs", fcs_202.read_bytes())
    assert len(body) <= cap + 64 * 1024  # so the Content-Length check lets it through
    r = c.post(
        f"{API}/uploads",
        content=body,
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "content-length": str(len(body)),
        },
    )
    err = assert_error(r, 413, "too_large")
    assert err["message"] == "FCS uploads are limited to 999.7 KB."
    ws = c.app.state.dn.workspaces.all()[0]
    assert list(ws.dir("uploads").iterdir()) == []  # the partial file is deleted


def test_low_disk_gives_507(make_client, fcs_202):
    c = make_client("trial", free_bytes=lambda p: 10)
    c.get(f"{API}/workspace")
    assert_error(upload(c, fcs_202), 507, "out_of_space")


def test_delete_upload(make_client, fcs_202):
    c = make_client()
    upload(c, fcs_202)
    assert c.delete(f"{API}/uploads/u1").status_code == 204
    assert_error(c.get(f"{API}/uploads/u1"), 404, "not_found")
    assert_error(c.delete(f"{API}/uploads/u1"), 404, "not_found")
