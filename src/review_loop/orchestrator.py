"""End-to-end local fixture: real child process/files, fake provider judgments."""
import json
import math
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from .core import Contract, Evidence, Run
from .processes import run_bounded, apply_process_result
from .snapshots import capture, decide_current
from .storage import atomic_write, save


def run_fixture(directory, scenario="success", total_seconds=5.0, cancel=None):
    """Caller owns directory lock. No user code, credentials, or AI are loaded."""
    if scenario not in ("success", "stalled", "timeout", "changed"):
        raise ValueError("Unknown fixture scenario")
    if os.name != "posix":
        raise ValueError("Fixture process backend currently requires POSIX; Windows launch refused")
    if not math.isfinite(total_seconds) or total_seconds <= 0:
        raise ValueError("Positive demo time budget required")
    directory = Path(directory).resolve()
    workspace = directory / "workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("pending", encoding="utf-8")
    contract = Contract("Fixture: produce verified output", ("verified_output",), ("fixture_check",))
    run = Run.start(str(uuid4()), contract, 0.0)
    start = time.monotonic()
    trace = []

    def logical_now():
        return (time.monotonic() - start) * contract.max_seconds / total_seconds

    def stage(state):
        run.state = state
        trace.append({"stage": state, "cycle": run.cycle + 1, "at": logical_now()})
        save(directory, run, contract)

    def execute(code, timeout):
        return run_bounded([sys.executable, "-c", code], workspace,
                           timeout=timeout,
                           remaining=max(0, total_seconds - (time.monotonic() - start)),
                           grace=0.1, cancel=cancel)

    try:
        capture(workspace, ["result.txt"], contract.fingerprint,
                destination=directory / "snapshots" / "baseline")
        for cycle in range(1, 5):
            if not run.guard(contract, logical_now()):
                break
            stage("IMPLEMENTING")
            if scenario == "timeout":
                code = "import time; time.sleep(60)"
                limit = total_seconds + 1
            else:
                value = "verified" if scenario in ("success", "changed") and cycle >= 2 else "pending"
                code = "from pathlib import Path; Path('result.txt').write_text(" + repr(value) + ", encoding='utf-8')"
                limit = 1
            result = execute(code, limit)
            apply_process_result(run, result)
            trace.append({"process": "implementation", "reason": result.reason,
                          "cleanup_confirmed": result.cleanup_confirmed})
            if run.state == "STOPPED":
                break
            stage("SNAPSHOTTING")
            snap = capture(workspace, ["result.txt"], contract.fingerprint,
                           destination=directory / "snapshots" / str(cycle))
            stage("CHECKING")
            check = execute("from pathlib import Path; raise SystemExit(0 if Path('result.txt').read_text() == 'verified' else 1)", 1)
            if not check.cleanup_confirmed:
                run.stop("process_cleanup_unconfirmed")
                break
            if check.reason != "exited":
                apply_process_result(run, check)
                if run.state != "STOPPED":
                    run.stop("check_interrupted")
                break
            passed = check.returncode == 0
            stage("REVIEWING")
            # Deterministic stand-ins; these are never presented as actual AI opinions.
            review = {"provider": "fake", "snapshot": snap.snapshot_id,
                      "verdict": "pass" if passed else "changes_requested"}
            stage("AUDITING")
            audit = {"provider": "fake", "snapshot": snap.snapshot_id,
                     "recommendation": "complete" if passed else "continue"}
            atomic_write(directory / ("evidence-" + str(cycle) + ".json"), json.dumps({
                "mode": "fixture", "snapshot": snap.snapshot_id,
                "check_exit_code": check.returncode, "review": review, "audit": audit
            }, indent=2))
            evidence = Evidence(snap.snapshot_id, review["snapshot"], audit["snapshot"],
                                passed_checks=["fixture_check"] if passed else [],
                                met_criteria=["verified_output"] if passed else [],
                                review=review["verdict"], audit=audit["recommendation"],
                                instructions=["Produce verified output"])
            if scenario == "changed" and passed:
                (workspace / "result.txt").write_text("external change", encoding="utf-8")
            stage("DECIDING")
            decide_current(run, contract, evidence, logical_now(), workspace, ["result.txt"])
            save(directory, run, contract)
            if run.state in ("STOPPED", "COMPLETED"):
                break
        else:
            run.stop("fixture_cycle_limit")
    except (OSError, ValueError) as exc:
        run.stop("fixture_error")
        trace.append({"error_type": type(exc).__name__})
    finally:
        save(directory, run, contract)
        atomic_write(directory / "trace.json", json.dumps(trace, indent=2))
    return run
