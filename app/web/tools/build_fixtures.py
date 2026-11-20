"""Build app/web/fixtures from real datanuggets outputs on public data.

Every number in a fixture is read from a real run of the datanuggets CLIs, or computed here from
those outputs and the public input files they read (four PBMC FCS files from Zenodo record
22079206, CC BY 4.0). Nothing is typed in. Where the phase-2 contract adds a table the old CLI did
not write yet (cells, cluster_markers, group tables, cluster colours), this script computes it
from the run's own CSVs and inputs with the contract's formula, and checks it against the run
where the run allows (projections equal the run's PCA scores, the direct per-cluster cell means
equal the weighted nugget-center means).

Group names are labels this script assigns to real files for the demo: 190.fcs and 193.fcs are
"Demo A", 199.fcs and 223.fcs are "Demo B". They are not biological conditions; the page says so.

The flow run r7 is made here by the server's own flow worker on the same gate with cofactor auto,
and its payloads come from the server's own readers, so the server's package must be importable:
run with the app's environment and with src and app/server on PYTHONPATH (not under -I, which
drops PYTHONPATH). r3's PCA and group tables, computed here, come out byte for byte only with
numpy 2.5.3 and pandas 3.0.6, the versions r3's run.json and the gate's gates.json record; under
the app's lock (numpy 2.5.4, pandas 3.1.0) their last digits differ. So the fixtures are built
with those two first on PYTHONPATH, and r7, which this script runs, records them too:

    python app/web/tools/build_fixtures.py \
        --mockup <folder with out/, fcs/, logs/, page/data.json> \
        --work <scratch folder for computed CSVs> --out app/web/fixtures

The /config and /health fixtures hold the package version, and nothing else in them comes from
a run. A version bump rewrites only those three files, from the app's own environment, and
leaves every other fixture as it is:

    uv run --project app python app/web/tools/build_fixtures.py \
        --config-only --out app/web/fixtures
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# python -I leaves this folder off sys.path; the parts live beside this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixturegen.common import iso, write_json
from fixturegen.config import write_config
from fixturegen.demos import write_demos
from fixturegen.gate import write_gate
from fixturegen.jobs import write_jobs
from fixturegen.livecells import write_livecells
from fixturegen.runs import run_payloads, write_runs
from fixturegen.uploads import write_uploads
from fixturegen.workspace import write_workspace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mockup", type=Path)
    ap.add_argument("--work", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--config-only",
        action="store_true",
        help="rewrite only the /config and /health fixtures in --out, as a version bump needs",
    )
    a = ap.parse_args()
    if a.config_only:
        write_config(a.out)
        print(f"wrote the /config and /health fixtures in {a.out}")
        return
    missing = [f"--{n}" for n in ("mockup", "work") if getattr(a, n) is None]
    if missing:
        ap.error(f"a full build needs {', '.join(missing)}")
    mock, out, work = a.mockup, a.out, a.work
    page = json.loads((mock / "page" / "data.json").read_text(encoding="utf-8"))["plots"]
    if out.exists():
        shutil.rmtree(out)
    (out / "png").mkdir(parents=True)
    work.mkdir(parents=True, exist_ok=True)

    gates = json.loads((mock / "out" / "flow-gates-1" / "gates.json").read_text(encoding="utf-8"))
    runs = run_payloads(mock, page, work, gates)

    t_gate = iso(gates["created"])
    t_ws = t_gate
    uploads, up_ids, by_name = write_uploads(out, mock, gates, t_ws)
    gate = write_gate(out, mock, gates, up_ids, by_name, t_gate)
    created, summaries, files_index = write_runs(out, work, runs, gates)
    jobs, t_last = write_jobs(out, mock, created, t_gate, runs["r7"]["log"])
    # Live cells on g1 with the pops the first flow run used, read back from its manifest.
    flow_rid = next(s["id"] for s in summaries if s["kind"] == "flow")
    flow_run = json.loads((out / f"GET__runs__{flow_rid}.json").read_text(encoding="utf-8"))
    write_livecells(out, mock, gate, flow_run["settings"]["pops"], t_last)
    write_config(out)
    write_demos(out, by_name, gates)
    write_workspace(out, t_ws, t_last, uploads, gate, summaries, jobs)
    # The page reads this list first, so a missing fixture is the API's not_found error without
    # a 404 request, and run-file links point only at the files copied above.
    names = sorted(p.name for p in out.glob("*.json"))
    write_json(out / "index.json", {"fixtures": names, "files": files_index})
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"wrote {sum(1 for _ in out.rglob('*.json'))} JSON fixtures, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
