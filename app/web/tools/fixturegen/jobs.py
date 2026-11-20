"""Jobs: the finished ones that made the runs, and the running ones the POST fixtures hand back."""

from __future__ import annotations

from pathlib import Path

from .common import log_lines, write_json


def job(
    jid,
    kind,
    status,
    created,
    *,
    run_id=None,
    gate_id=None,
    log=(),
    progress=None,
    stage=None,
    message=None,
):
    done = status == "done"
    return {
        "id": jid,
        "kind": kind,
        "status": status,
        "progress": 1.0 if done else (0.0 if progress is None else progress),
        "stage": stage,
        "message": message,
        "log_tail": list(log)[-50:],
        "created": created,
        "started": created if status != "queued" else None,
        "finished": created if status in ("done", "failed", "cancelled") else None,
        "run_id": run_id,
        "gate_id": gate_id,
        "error": None,
    }


def write_jobs(out: Path, mock: Path, created: dict, t_gate: str, auto_log: list[str]):
    """Writes every job fixture and the two POSTs that queue one; returns the done jobs and the last time.
    j10 made the cofactor-auto flow run r7, with the log its worker wrote; it takes the next job id
    after j9, the live-cells job. The ids keep their gaps, because the docs and tests name them."""
    # Jobs: the finished ones that made the runs, and running ones the POST fixtures hand back,
    # whose log tails are the first lines of a real run's own log.
    logs = mock / "logs"
    jobs = [
        job(
            "j1",
            "gate",
            "done",
            t_gate,
            gate_id="g1",
            log=log_lines(logs / "flow-gates-1.log"),
            stage="done",
        ),
        job(
            "j4",
            "flow",
            "done",
            created["r3"],
            run_id="r3",
            gate_id="g1",
            log=log_lines(logs / "flow-run-1.log"),
            stage="done",
        ),
        job(
            "j10",
            "flow",
            "done",
            created["r7"],
            run_id="r7",
            gate_id="g1",
            log=auto_log,
            stage="done",
        ),
    ]
    for j in jobs:
        write_json(out / f"GET__jobs__{j['id']}.json", j)
    write_json(out / "GET__jobs.json", {"jobs": jobs})
    t_last = max(created.values())
    running = []
    for jid, kind, src, stage, extra_ids in (
        ("j7", "gate", logs / "flow-gates-1.log", "gating", {"gate_id": "g2"}),
        ("j8", "flow", logs / "flow-run-1.log", "nuggets", {"run_id": "r6", "gate_id": "g1"}),
    ):
        lines = log_lines(src)
        shown = lines[: max(1, len(lines) // 2)]
        queued = job(jid, kind, "queued", t_last, **extra_ids)
        run_j = job(
            jid,
            kind,
            "running",
            t_last,
            log=shown,
            progress=round(len(shown) / len(lines), 2),
            stage=stage,
            message=shown[-1],
            **extra_ids,
        )
        cancelled = dict(
            run_j,
            status="cancelled",
            finished=t_last,
            error={"code": "cancelled", "message": "Cancelled.", "param": None},
        )
        write_json(out / f"GET__jobs__{jid}.json", run_j)
        write_json(out / f"POST__jobs__{jid}__cancel.json", cancelled)
        running.append((jid, queued))
    write_json(out / "POST__flow__gates.json", {"job": running[0][1], "gate_id": "g2"})
    write_json(out / "POST__flow__runs.json", {"job": running[1][1], "run_id": "r6"})

    return (jobs, t_last)
