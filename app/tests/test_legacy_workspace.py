"""A local workspace from before the app was flow-only: a CSV upload and a general run with its
done job, written to disk as the earlier server wrote them, then read by a server started on that
folder. It lists them, serves the run's files and deletes both, keeps the job listed until DELETE
/workspace, and refuses to read the general run as it reads a flow run (409, as /compare already
did) or to gate the CSV (422)."""

from __future__ import annotations

import io
import json
import zipfile

from dnapp.core.workspace import Workspaces, write_json
from testkit import API, Clock, assert_error, make_settings, new_client

CREATED = "2026-10-01T12:00:00Z"
CSV = "a,b\n1.5,2.5\n2.5,0.5\n"
NUGGETS = "nugget0,weight,feature:a,feature:b,kmeans_cluster\n0,1,1.5,2.5,0\n1,1,2.5,0.5,1\n"
COLORS = "method,cluster,parent,color\nkmeans,0,0,#1f77b4\nkmeans,1,1,#ff7f0e\n"
RUN_JSON = {"schema_version": 1, "complete": True, "input": {"name": "legacy.csv"},
            "features": ["a", "b"], "analyses": ["kmeans"]}  # fmt: skip


def seed(settings) -> None:
    """Upload u1 (a CSV), run r1 (general, from u1) and its job j1, done."""
    ws = Workspaces(settings, Clock()).local()
    column = {"label": "", "numeric": True, "missing": 0}
    (ws.dir("uploads") / "u1").mkdir()
    (ws.dir("uploads") / "u1" / "legacy.csv").write_text(CSV, encoding="utf-8")
    ws.records("uploads")["u1"] = {
        "id": "u1", "name": "legacy.csv", "kind": "csv", "bytes": len(CSV), "rows": 2,
        "columns": [{"name": "a", "min": 1.5, "max": 2.5, "mean": 2.0, **column},
                    {"name": "b", "min": 0.5, "max": 2.5, "mean": 1.5, **column}],
        "preview": {"header": ["a", "b"], "rows": [["1.5", "2.5"], ["2.5", "0.5"]]},
        "created": CREATED, "demo": None, "path": "uploads/u1/legacy.csv",
    }  # fmt: skip
    out = ws.dir("runs") / "r1"
    out.mkdir()
    (out / "run.json").write_text(json.dumps(RUN_JSON, indent=2) + "\n", encoding="utf-8")
    (out / "nuggets.csv").write_text(NUGGETS, encoding="utf-8")
    (out / "cluster_colors.csv").write_text(COLORS, encoding="utf-8")
    ws.records("runs")["r1"] = {
        "id": "r1", "kind": "general", "created": CREATED, "title": "legacy.csv", "source": "u1",
        "settings": {"upload": "u1", "columns": ["a", "b"], "analysis": ["kmeans"],
                     "clusters": 2},
        "job": "j1",
    }  # fmt: skip
    write_json(
        ws.dir("jobs") / "j1.json",
        {
            "id": "j1", "kind": "general", "status": "done", "progress": 1.0, "stage": "done",
            "message": "", "log_tail": [], "created": CREATED, "started": CREATED,
            "finished": CREATED, "run_id": "r1", "gate_id": None, "error": None,
            "_warnings": [], "_info": {},
        },
    )  # fmt: skip
    ws.meta["counters"].update(uploads=1, runs=1, jobs=1)
    ws.save()


def test_a_legacy_workspace_keeps_its_csv_upload_and_general_run(tmp_path):
    settings = make_settings(tmp_path)
    seed(settings)
    ws = settings.data_dir / "ws" / "local"
    with new_client(settings) as c:
        body = c.get(f"{API}/workspace").json()
        assert [(u["id"], u["kind"]) for u in body["uploads"]] == [("u1", "csv")]
        assert "preview" not in body["uploads"][0]  # kept on disk, no longer sent
        assert "preview" not in c.get(f"{API}/uploads/u1").json()
        assert_error(c.get(f"{API}/uploads/u1/rows"), 404, "not_found")
        # nor can the CSV be gated: the gate's kind check keeps it from the FCS reader
        r = c.post(f"{API}/flow/gates", json={"uploads": ["u1"], "settings": {}})
        assert assert_error(r, 422, "invalid_setting", "uploads")["message"] == (
            "u1 is not an FCS upload in this workspace."
        )
        assert [(r["id"], r["kind"], r["status"]) for r in body["runs"]] == [
            ("r1", "general", "done")
        ]
        assert [(j["id"], j["kind"]) for j in body["jobs"]] == [("j1", "general")]
        # the app reads flow runs only: a general run is refused as /compare refuses it
        for part in ("", "/plot", "/cells", "/compare"):
            err = assert_error(c.get(f"{API}/runs/r1{part}"), 409, "wrong_state")
            assert err["message"].endswith("are for flow runs."), (part, err)
        # its files still download, alone and zipped
        r = c.get(f"{API}/runs/r1/files/nuggets.csv")
        assert r.status_code == 200 and r.text == NUGGETS
        assert json.loads(c.get(f"{API}/runs/r1/files/run.json").text) == RUN_JSON
        z = zipfile.ZipFile(io.BytesIO(c.get(f"{API}/runs/r1/download.zip").content))
        assert sorted(z.namelist()) == ["cluster_colors.csv", "nuggets.csv", "run.json"]
        assert z.read("nuggets.csv").decode() == NUGGETS
        # and both go, files and all
        assert c.delete(f"{API}/runs/r1").status_code == 204
        assert c.delete(f"{API}/uploads/u1").status_code == 204
        body = c.get(f"{API}/workspace").json()
        assert body["uploads"] == [] and body["runs"] == []
        assert not (ws / "runs" / "r1").exists() and not (ws / "uploads" / "u1").exists()
        # no route deletes a job: the general job stays listed until the workspace goes
        assert [(j["id"], j["kind"]) for j in body["jobs"]] == [("j1", "general")]
        assert c.get(f"{API}/jobs/j1").json()["kind"] == "general"
        assert c.delete(f"{API}/workspace").status_code == 204
        assert c.get(f"{API}/jobs").json() == {"jobs": []}
