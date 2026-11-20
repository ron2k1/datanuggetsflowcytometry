"""Health and config (contract section 3.2), and the headers on the page and the API."""

from __future__ import annotations

from dnapp.core.config import Settings
from dnapp.core.http import CSP
from dnapp.core.package.runtime import package_version
from testkit import API, INDEX

CONFIG_KEYS = {
    "mode", "version", "package_version", "caps", "ttl", "defaults", "limits",
    "docker_command", "build_command", "build_run_command", "storage_note",
}  # fmt: skip


def test_health_and_page(make_client):
    c = make_client()
    r = c.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "mode", "version", "jobs"}
    assert body["status"] == "ok" and body["mode"] == "local"
    assert set(body["jobs"]) == {"running", "queued"}
    page = c.get("/")
    assert page.status_code == 200 and page.text == INDEX
    assert page.headers["content-security-policy"] == CSP
    assert "unsafe-eval" not in CSP
    for r in (page, c.get(f"{API}/health"), c.get(f"{API}/nope")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" not in c.get(f"{API}/health").headers


def test_config_local_and_trial(make_client):
    local = make_client().get(f"{API}/config").json()
    assert set(local) == CONFIG_KEYS
    assert local["caps"] is None and local["ttl"] is None
    assert local["storage_note"] == "Files stay on this computer."
    assert local["limits"] == {"k_max": 100}
    assert set(local["defaults"]) == {"gate", "cluster", "cofactor_auto"}
    assert "n_jobs" not in local["defaults"]["cluster"]
    assert local["defaults"]["cluster"]["standardize"] is True  # the Scale stage, on by default
    # the Transform stage's cofactor is picked per channel from the cells the run clusters unless
    # a number is sent, by the rule's floor and guard (literal here, so a change to the package's
    # shows); the header rule's numbers are gone
    assert local["defaults"]["cluster"]["cofactor"] == "auto"
    assert local["defaults"]["cofactor_auto"] == {
        "rule": "per_channel",
        "floor": 150.0,
        "min_negative_fraction": 0.01,
    }
    assert list(local["defaults"]["cofactor_auto"]) == ["rule", "floor", "min_negative_fraction"]
    # no channel name is assumed: the gate takes each first file's own (gate_channels)
    assert local["defaults"]["gate"]["fsc"] is None and local["defaults"]["gate"]["ssc"] is None
    assert local["defaults"]["gate"]["disc"] == "reference"  # the web's area rule options
    assert local["docker_command"].startswith("docker run")
    trial = make_client("trial", sub="t").get(f"{API}/config").json()
    assert trial["caps"]["k_max"] == 100 and trial["caps"]["upload_fcs_bytes"] == 200_000_000
    assert not any(key.startswith(("upload_csv", "csv_", "general_")) for key in trial["caps"])
    assert trial["ttl"] == {"idle_s": 21600, "max_s": 86400}
    assert trial["storage_note"].startswith("Files stay in a temporary workspace")
    assert "account" not in (str(trial) + str(local)).lower()


def test_run_it_locally_names_the_running_version(make_client):
    """R12: the published image and the source build are both pinned to the version that is
    running, and both bind the port to 127.0.0.1 only. The literals here are the commands the
    docs print, so a change to either shows."""
    v = package_version()
    cfg = make_client().get(f"{API}/config").json()
    assert cfg["package_version"] == v
    run = "docker run --rm -p 127.0.0.1:8000:8000 -v datanuggets-data:/data"
    assert cfg["docker_command"] == f"{run} ghcr.io/ron2k1/datanuggets-flow:{v}"
    assert cfg["build_command"] == (
        "docker build -t datanuggets-flow "
        f"https://github.com/ron2k1/datanuggetsflowcytometry.git#v{v}"
    )
    assert cfg["build_run_command"] == f"{run} datanuggets-flow"
    own = make_client(sub="own", docker_command="docker run --rm my/mirror").get(f"{API}/config")
    assert own.json()["docker_command"] == "docker run --rm my/mirror"
    assert Settings.from_env({"DN_DOCKER_COMMAND": ""}).docker_command is None


def test_package_version_is_the_flow_package_not_the_library(monkeypatch, make_client):
    """The image tag and the release tag in the commands are versions of datanuggets-flow. The
    library it depends on has its own version, so the two are given different ones here."""
    from dnapp.core.package import runtime

    versions = {"datanuggets-flow": "9.9.9", "datanuggets": "1.1.1"}
    monkeypatch.setattr(runtime, "version", versions.__getitem__)
    assert runtime.package_version() == "9.9.9"
    cfg = make_client().get(f"{API}/config").json()
    assert cfg["package_version"] == "9.9.9"
    assert cfg["docker_command"].endswith("ghcr.io/ron2k1/datanuggets-flow:9.9.9")
    assert cfg["build_command"].endswith("datanuggetsflowcytometry.git#v9.9.9")


def test_livecells_caps_are_the_amendments_table(make_client):
    """contract-livecells.md section 2.4: trial /config sends them; local mode keeps a cap with a
    Local value and switches the rest off."""
    from dnapp.core.config import LOCAL_CAPS

    trial = make_client("trial", sub="t").get(f"{API}/config").json()["caps"]
    table = {
        "livecells_channels_max": (8, None),
        "livecells_bins_min": (8, 8),
        "livecells_bins_max": (512, 512),
        "livecells_per_gate": (8, 8),
        "livecells_cells_max": (6_000_000, None),
        "livecells_filters_max": (16, None),
        "livecells_counts_per_ip_minute": (120, None),
        "livecells_memory_sets": (2, 2),
    }
    assert {k: v for k, v in trial.items() if k.startswith("livecells")} == {
        k: t for k, (t, _) in table.items()
    }
    assert {k: getattr(LOCAL_CAPS, k) for k in table} == {k: lo for k, (_, lo) in table.items()}
