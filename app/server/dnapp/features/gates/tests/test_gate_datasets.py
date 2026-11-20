"""A gate takes files from one dataset: uploads whose colour channels, the package's default
channels (the $PnN names that end in -A and aren't scatter), are the same set. POST /flow/gates
compares every file with the first and refuses the first that differs, before a job is queued.
The files are 202's recorded events (testkit's fcs_202) with a channel dropped, added from another
of its columns, moved or relabelled."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dnapp.core.datasets import channel_diff
from dnapp.core.package.flow import colour_channels, default_channels
from testkit import API, FLOW, assert_error, upload, wait_job

AF700, BV510, SPARK = "FJComp-Alexa Fluor 700-A", "FJComp-BV510-A", "FJComp-Spark Blue-A"
# four more colour channels of 202's panel, as the PBMC demo's 190.fcs in the fixtures names them
MORE = ["FJComp-BV421-A", "FJComp-BV480-A", "FJComp-BV570-A", "FJComp-FITC-A"]
TAIL = "A gate takes files from one dataset."


def columns_202() -> list[tuple[str, str, np.ndarray]]:
    """202's channels as (name, label, events): FSC-A, SSC-A and the three fluorescence ones."""
    with np.load(FLOW / "202.npz") as gate, np.load(FLOW / "202_fluor.npz") as fluor:
        cols = [("FSC-A", "", gate["fsc"]), ("SSC-A", "", gate["ssc"])]
        for j, (n, s) in enumerate(zip(fluor["pnn"].tolist(), fluor["pns"].tolist())):
            cols.append((n, s, fluor["fluor"][:, j]))
    return cols


def write_fcs(path: Path, cols: list[tuple[str, str, np.ndarray]]) -> Path:
    import flowio

    events = np.column_stack([c[2] for c in cols])
    names, labels = [c[0] for c in cols], [c[1] for c in cols]
    with path.open("wb") as handle:
        flowio.create_fcs(handle, events.ravel(), names, opt_channel_names=labels)
    return path


@pytest.fixture(scope="module")
def panels(tmp_path_factory) -> dict[str, Path]:
    """The files by name. An added channel holds the events of one of 202's own columns."""
    folder = tmp_path_factory.mktemp("panels")
    cols = columns_202()
    by = {c[0]: c for c in cols}
    fsc, ssc, af700, bv510, spark = cols

    def added(name: str, like: str):
        return (name, "", by[like][2])

    extra = [("FSC-H", "FSC-A"), ("SSC-B-A", "SSC-A"), ("Time", "FSC-A"), ("Zombie NIR-H", BV510)]
    files = {
        "202.fcs": cols,
        "moved.fcs": [spark, fsc, bv510, ssc, af700],
        "relabelled.fcs": [fsc, ssc, (AF700, "CD57", af700[2]), bv510, spark],
        "extra.fcs": [*cols, *(added(n, like) for n, like in extra)],
        "less.fcs": [fsc, ssc, af700, bv510],
        "more.fcs": [*cols, added(MORE[0], BV510)],
        "swapped.fcs": [fsc, ssc, af700, bv510, added(MORE[0], SPARK)],
        "wide.fcs": [*cols, *(added(n, c[0]) for n, c in zip(MORE, [af700, bv510, spark, af700]))],
        "one.fcs": [fsc, ssc, af700],
    }
    return {name: write_fcs(folder / name, c) for name, c in files.items()}


def uploaded(client, panels, *names: str) -> list[str]:
    ids = []
    for name in names:
        r = upload(client, panels[name])
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


def gate(client, uploads: list[str]):
    return client.post(f"{API}/flow/gates", json={"uploads": uploads, "settings": {}})


def refusal(then: str, first: str, diff: str) -> str:
    return f"{then} has different colour channels from {first} (it {diff}). {TAIL}"


def test_colour_channels_are_the_packages_default_channels_as_a_set():
    pnn = ["FSC-A", "SSC-A", SPARK, AF700, BV510]
    assert colour_channels(pnn) == [AF700, BV510, SPARK]
    assert colour_channels(pnn) == sorted(default_channels(pnn, [""] * 5, "202.fcs"))
    # scatter by its name, -H, -W and Time never count beside two -A channels, and a name
    # counts once
    other = ["FSC-H", "SSC-B-A", "SSC-W", "Time", "Zombie NIR-H", BV510]
    assert colour_channels([*other, BV510, AF700]) == [AF700, BV510]
    # with fewer, every channel but scatter and Time does, as on a mass cytometer
    assert colour_channels([*other, BV510]) == [BV510, "Zombie NIR-H"]
    assert colour_channels(["Time", "Ir193Di", "Ce140Di", "Ir191Di"]) == [
        "Ce140Di", "Ir191Di", "Ir193Di"
    ]  # fmt: skip
    assert colour_channels(["FSC-A", "SSC-A"]) == []


def test_the_diff_names_three_channels_then_counts():
    a = [AF700, BV510, SPARK]
    assert channel_diff(a, [AF700, BV510]) == f"lacks {SPARK}"
    assert channel_diff(a, [*a, MORE[0]]) == f"adds {MORE[0]}"
    assert channel_diff(a, [AF700, BV510, MORE[0]]) == f"lacks {SPARK}; adds {MORE[0]}"
    assert channel_diff(a, [AF700]) == f"lacks {BV510}, {SPARK}"
    assert channel_diff([], a) == f"adds {AF700}, {BV510}, {SPARK}"
    # in sorted order, whatever order they come in
    assert channel_diff([], [*a, *MORE[:2]]) == f"adds {AF700}, {MORE[0]}, {MORE[1]} and 2 more"
    assert channel_diff(MORE, []) == f"lacks {', '.join(MORE[:3])} and 1 more"


def test_files_of_one_dataset_are_gated(make_client, panels):
    """The order of the channels, their stains ($PnS), and scatter, -H and Time channels do not
    make another dataset."""
    c = make_client()
    first, *others = uploaded(c, panels, "202.fcs", "moved.fcs", "relabelled.fcs", "extra.fcs")
    for uid in others:
        r = gate(c, [first, uid])
        assert r.status_code == 202, (uid, r.text)
    assert gate(c, [*others, first]).status_code == 202


@pytest.mark.parametrize(
    ("first", "then", "diff"),
    [
        ("202.fcs", "less.fcs", f"lacks {SPARK}"),
        ("202.fcs", "more.fcs", f"adds {MORE[0]}"),
        ("202.fcs", "swapped.fcs", f"lacks {SPARK}; adds {MORE[0]}"),
        ("202.fcs", "wide.fcs", f"adds {MORE[0]}, {MORE[1]}, {MORE[2]} and 1 more"),
        ("wide.fcs", "202.fcs", f"lacks {MORE[0]}, {MORE[1]}, {MORE[2]} and 1 more"),
        ("moved.fcs", "one.fcs", f"lacks {BV510}, {SPARK}"),
    ],
)
def test_a_file_of_another_dataset_is_refused(make_client, panels, first, then, diff):
    c = make_client()
    err = assert_error(gate(c, uploaded(c, panels, first, then)), 422, "invalid_setting", "uploads")
    assert err["message"] == refusal(then, first, diff)
    body = c.get(f"{API}/workspace").json()
    assert body["gates"] == [] and body["jobs"] == []  # refused before a job was queued


def test_every_file_is_compared_with_the_first(make_client, panels):
    """The first file that differs from file 1 is named, though a later one differs more."""
    c = make_client()
    ids = uploaded(c, panels, "less.fcs", "202.fcs", "one.fcs", "less.fcs")
    err = assert_error(gate(c, ids), 422, "invalid_setting", "uploads")
    assert err["message"] == refusal("202.fcs", "less.fcs", f"adds {SPARK}")
    err = assert_error(gate(c, [ids[0], ids[3], ids[2]]), 422, "invalid_setting", "uploads")
    assert err["message"] == refusal("one.fcs", "less.fcs", f"lacks {BV510}")


def test_a_run_refuses_a_gate_whose_uploads_mix_datasets(make_client, panels, monkeypatch):
    """A gate made before POST /flow/gates checked its files, as a local workspace can keep one,
    may hold two datasets. POST /flow/runs refuses it in the gate refusal's form, param gate_id,
    before a job is queued."""
    from dnapp.features.gates import router

    monkeypatch.setattr(router, "check_one_dataset", lambda *args: None)  # as before the check
    c = make_client()
    r = gate(c, uploaded(c, panels, "202.fcs", "more.fcs"))
    assert r.status_code == 202, r.text
    assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
    jobs = c.get(f"{API}/workspace").json()["jobs"]
    run = {"gate_id": r.json()["gate_id"], "pops": [[1], [1]], "k": 2}
    err = assert_error(c.post(f"{API}/flow/runs", json=run), 422, "invalid_setting", "gate_id")
    assert err["message"] == (
        f"more.fcs has different colour channels from 202.fcs (it adds {MORE[0]}). A run takes "
        "files from one dataset."
    )
    body = c.get(f"{API}/workspace").json()
    assert body["runs"] == [] and body["jobs"] == jobs


def test_a_file_with_one_colour_channel_is_gated_and_the_cluster_step_refuses_it(
    make_client, panels
):
    """It is in one dataset with the files of its colour channel, here none other, and gates;
    clustering needs two channels, which the package checks in the run's job, as before."""
    c = make_client()
    r = gate(c, uploaded(c, panels, "one.fcs"))
    assert r.status_code == 202, r.text
    assert wait_job(c, r.json()["job"]["id"])["status"] == "done"
    r = c.post(f"{API}/flow/runs", json={"gate_id": r.json()["gate_id"], "pops": [[1]], "k": 2})
    assert r.status_code == 202, r.text
    job = wait_job(c, r.json()["job"]["id"])
    assert job["status"] == "failed" and job["error"]["param"] == "channels", job
