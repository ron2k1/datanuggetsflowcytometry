"""What runs inside a job's worker process (spawned, never forked): run_job wraps a kind's work
function (registered in main.py) with its reporting, cancelling and error handling. A job reports
through files in its workspace's jobs/ folder: <jid>.log gets its log lines, <jid>.progress one
JSON line per progress step, and a <jid>.cancel file asks it to stop at its next step. Nothing
crosses the process boundary but the job's arguments and its result dict."""

from __future__ import annotations

import json
import re
import shutil
import time
import traceback
import warnings
from pathlib import Path

from dnapp.core.config import PROGRESS_START
from dnapp.core.errors import Scrubber, internal_ref
from dnapp.core.package.errors import refusal
from dnapp.core.package.runtime import prepare_worker
from dnapp.core.protocols import Work


def init_worker() -> None:
    """Runs once in each worker: figures go to files, and labels are never read as math."""
    prepare_worker()


class Cancelled(Exception):
    pass


class Reporter:
    def __init__(self, jobs_dir: str, jid: str, roots: list[str]):
        d = Path(jobs_dir)
        self.log_path = d / f"{jid}.log"
        self.progress_path = d / f"{jid}.progress"
        self.cancel_path = d / f"{jid}.cancel"
        self.scrub = Scrubber(roots)
        self.p = 0.0

    def check(self) -> None:
        if self.cancel_path.exists():
            raise Cancelled()

    def log(self, text: str) -> None:
        lines = [self.scrub.text(line) for line in str(text).splitlines()]
        lines = [line for line in lines if line.strip()]
        if lines:
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

    def progress(self, p: float, stage: str | None, message: str | None = None) -> None:
        self.p = max(self.p, min(p, 0.99))  # never decreasing; 1.0 only when done (main sets it)
        rec = {"p": round(self.p, 4), "stage": stage, "message": message, "t": time.time()}
        if message:
            rec["message"] = self.scrub.text(message)
        with self.progress_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")


def _param_guess(message: str, names: set[str]) -> str | None:
    """A field the message names, as a --flag or by its own name; None when it names none."""
    for flag in re.findall(r"--([a-z][a-z0-9-]*)", message):
        name = flag.replace("-", "_")
        if name in names:
            return name
    for name in sorted(names, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", message):
            return name
    return None


def _error(code: str, message: str, param: str | None = None) -> dict:
    return {"code": code, "message": message, "param": param}


def run_job(kind: str, work: Work, spec: dict) -> dict:
    """Runs work(spec, reporter, out) for a job of kind. The job's result: {"status": "done"|"failed"|"cancelled", "error", "warnings", "info",
    "detail" (a traceback for the server log only)}."""
    rep = Reporter(spec["jobs_dir"], spec["jid"], spec["roots"])
    out = Path(spec["out"])
    caught: list[warnings.WarningMessage] = []
    result: dict = {"status": "done", "error": None, "warnings": [], "info": {}, "detail": None}
    try:
        rep.check()
        rep.progress(PROGRESS_START, kind, "Started")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            info = work(spec, rep, out)
        result["info"] = info or {}
    except Cancelled:
        shutil.rmtree(out, ignore_errors=True)
        rep.log("Cancelled.")
        result |= {"status": "cancelled", "error": _error("cancelled", "The job was cancelled.")}
    except Exception as e:  # noqa: BLE001 - every failure becomes the job error, not a dead worker
        shutil.rmtree(out, ignore_errors=True)
        result["status"] = "failed"
        result["error"] = _classify(e, spec, rep)
        if result["error"]["code"] == "internal":
            result["detail"] = rep.scrub.text(traceback.format_exc())
    seen = []
    for w in caught:
        text = rep.scrub.text(str(w.message))
        if text not in seen:
            seen.append(text)
    result["warnings"] = seen
    return result


def _classify(e: Exception, spec: dict, rep: Reporter) -> dict:
    refused = refusal(e)
    if refused is not None:
        msg = rep.scrub.text(refused.message)
        rep.log(f"Error: {msg}")
        return _error("invalid_setting", msg, refused.param)
    if isinstance(e, MemoryError):
        rep.log("Error: out of memory")
        return _error("out_of_memory", "The job ran out of memory; try fewer nuggets or cells.")
    if isinstance(e, (ValueError, UnicodeError)):
        msg = rep.scrub.text(str(e))
        rep.log(f"Error: {msg}")
        param = _param_guess(msg, set(spec.get("param_names", ())))
        code = "unreadable_file" if isinstance(e, UnicodeError) else "invalid_setting"
        return _error(code, msg, param)
    ref = internal_ref()
    spec["ref"] = ref
    rep.log(f"Error: something went wrong (ref {ref})")
    return _error("internal", f"Something went wrong (ref {ref})")
