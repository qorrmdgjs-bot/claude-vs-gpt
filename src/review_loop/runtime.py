"""Bounded CLI loop for small, trusted scratch tasks; not a company-data sandbox."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from uuid import uuid4

from .core import Contract, Evidence, Run, digest
from .processes import run_bounded
from .providers import CLIProviders, validate_judgment
from .snapshots import capture, decide_current, validate_paths
from .storage import atomic_write, locked


SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b")


def load_task(path):
    task = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(task, dict) or set(task) != {"goal", "criteria", "instructions", "files", "checks"}:
        raise ValueError("Task requires goal, criteria, instructions, files and checks")
    if not isinstance(task["goal"], str) or not task["goal"].strip():
        raise ValueError("Goal required")
    if not isinstance(task["files"], dict):
        raise ValueError("Files must map relative paths to initial UTF-8 text")
    validate_paths(list(task["files"]))
    for name, content in task["files"].items():
        if any(part.startswith(".") for part in name.split("/")) or Path(name).suffix.lower() not in (".py", ".txt", ".md", ".json", ".csv"):
            raise ValueError("Only nonhidden scratch source/data files are accepted")
        if not isinstance(content, str) or SECRET.search(content):
            raise ValueError("Invalid content or suspected secret")
    if len(json.dumps(task).encode()) > 500_000 or SECRET.search(json.dumps(task)):
        raise ValueError("Task too large or suspected secret")
    if not isinstance(task["checks"], list) or not task["checks"]:
        raise ValueError("Checks required")
    check_ids = []
    for check in task["checks"]:
        if not isinstance(check, dict) or set(check) != {"id", "argv"}:
            raise ValueError("Check requires id and argv")
        if not isinstance(check["argv"], list) or not check["argv"] or any(not isinstance(x, str) or not x for x in check["argv"]):
            raise ValueError("Check argv must be an argument array")
        check_ids.append(check["id"])
    criterion_ids = []
    for c in task["criteria"]:
        if not isinstance(c, dict) or set(c) != {"id", "description", "checks"} or not isinstance(c["description"], str) or not c["description"].strip():
            raise ValueError("Criterion requires id, description and check IDs")
        if not c["checks"] or not set(c["checks"]) <= set(check_ids):
            raise ValueError("Every criterion needs known checks")
        criterion_ids.append(c["id"])
    contract = Contract(task["goal"], tuple(criterion_ids), tuple(check_ids))
    if not isinstance(task["instructions"], list) or not 1 <= len(task["instructions"]) <= 2 or any(not isinstance(x, str) or not x.strip() for x in task["instructions"]):
        raise ValueError("One or two initial instructions required")
    return task, contract


def inventory(workspace, names):
    found = []
    for root, dirs, files in os.walk(workspace, followlinks=False):
        for name in dirs:
            path = Path(root) / name
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Workspace links forbidden")
        for name in files:
            found.append((Path(root) / name).relative_to(workspace).as_posix())
    if set(found) != set(names):
        raise ValueError("Workspace file allowlist changed")
    return capture(workspace, names, "inventory")


class Cancel:
    def __init__(self, path, event=None):
        self.path, self.event = path, event

    def is_set(self):
        return self.path.exists() or (self.event is not None and self.event.is_set())


def persist(directory, run, task, history, calls):
    payload = {"schema_version": 2, "mode": "cli", "task": task, "task_hash": digest(task),
               "run": asdict(run), "history": history, "calls": calls}
    atomic_write(directory / "state.json", json.dumps(payload, ensure_ascii=False, indent=2))
    text = ("# CLI 실행 보고서\n\n- 상태: " + run.state + "\n- 이유: " + run.reason
            + "\n- 검토 주기: " + str(run.cycle) + "\n- AI 호출: " + str(calls)
            + "\n- 연속 무진전: " + str(run.stalled)
            + "\n\n결과 파일: workspace/\n\n이 실행은 신뢰된 가상 작업용입니다. OS 보안 격리·회사 데이터 보호를 보장하지 않습니다. 원본 CLI 출력은 보관하지 않습니다.\n")
    atomic_write(directory / "REPORT.md", text)


def run_live(task_path, directory, resume=False, provider=None, cancel_event=None):
    """Explicit opt-in is enforced by CLI. Returns terminal run; never publishes."""
    directory = Path(directory).resolve()
    if any((p / ".git").exists() for p in (directory, *directory.parents)):
        raise ValueError("Run data must be outside Git repositories")
    if not resume and directory.exists() and any(directory.iterdir()):
        raise ValueError("New empty run directory required")
    with locked(directory):
        if resume:
            saved = json.loads((directory / "state.json").read_text(encoding="utf-8"))
            if saved.get("schema_version") != 2 or saved.get("mode") != "cli":
                raise ValueError("Not a resumable CLI run")
            task = saved["task"]
            # Revalidate task using the same parser and immutable contract copy.
            task_path = directory / "contract.json"
            if json.loads(task_path.read_text(encoding="utf-8")) != task or digest(task) != saved["task_hash"]:
                raise ValueError("Contract mismatch")
            task, contract = load_task(task_path)
            run = Run(**saved["run"])
            if run.deadline != run.started + 14400:
                raise ValueError("Invalid persisted deadline")
            history, calls = saved["history"], saved["calls"]
            # Manager crash is an unclean stop. No automatic relaunch.
            if (directory / "active.json").exists():
                raise ValueError("Unclean exit: inspect process ownership before clearing active.json")
            if run.state not in ("STOPPED",):
                raise ValueError("Only stopped runs can resume")
            run.resume(contract, time.time(), approved=True, cause_resolved=True)
            if run.state == "STOPPED":
                persist(directory, run, task, history, calls)
                return run
        else:
            task, contract = load_task(task_path)
            run = Run.start(str(uuid4()), contract, time.time())
            run.instructions = task["instructions"]
            history, calls = [], 0
            atomic_write(directory / "contract.json", json.dumps(task, ensure_ascii=False, indent=2))
            (directory / "workspace").mkdir()
            for name, content in task["files"].items():
                target = directory / "workspace" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        workspace = directory / "workspace"
        names = list(task["files"])
        cancel = Cancel(directory / "cancel.request", cancel_event)
        # Explicit resume clears the prior request, but cannot renew the deadline.
        if resume and cancel.path.exists():
            cancel.path.unlink()
        wall_start, mono_start = time.time(), time.monotonic()

        def now():
            expected = wall_start + time.monotonic() - mono_start
            if time.time() < expected - 5:
                raise ValueError("System clock moved backwards")
            return max(expected, time.time())

        def remaining():
            value = max(0, run.deadline - now())
            if value <= 0:
                raise ValueError("Total time limit reached")
            if cancel.is_set():
                raise ValueError("Cancelled")
            return value

        def checkpoint(stage):
            run.state = stage
            remaining()
            persist(directory, run, task, history, calls)

        def ai_call(method, *args):
            nonlocal calls
            remaining()
            if calls >= 30:
                raise ValueError("AI call limit reached")
            calls += 1
            persist(directory, run, task, history, calls)
            atomic_write(directory / "active.json", json.dumps({"manager_pid": os.getpid(), "stage": run.state}))
            try:
                return method(*args, remaining(), cancel)
            except ValueError as exc:
                if "cleanup=False" in str(exc):
                    raise RuntimeError("Unconfirmed process cleanup; active marker retained") from exc
                raise
            finally:
                # RuntimeError deliberately leaves the marker for ownership inspection.
                if sys.exc_info()[0] is not RuntimeError:
                    (directory / "active.json").unlink(missing_ok=True)

        def snapshot(label):
            inventory(workspace, names)
            if sum((workspace / name).stat().st_size for name in names) > 500_000:
                raise ValueError("Workspace exceeds small-task size limit")
            for name in names:
                content = (workspace / name).read_text(encoding="utf-8")
                protected = {arg for check in task["checks"] for arg in check["argv"] if arg in names}
                if name in protected and content != task["files"][name]:
                    raise ValueError("Protected check file was modified")
                if SECRET.search(content):
                    raise ValueError("Suspected secret in workspace")
            return capture(workspace, names, contract.fingerprint,
                           destination=directory / "snapshots" / label)

        def checks(snap, label):
            results = []
            with tempfile.TemporaryDirectory(prefix="review-loop-check-") as temp:
                copied = Path(temp).resolve() / "files"
                shutil.copytree(directory / "snapshots" / label / "files", copied)
                for check in task["checks"]:
                    budget = remaining()
                    atomic_write(directory / "active.json", json.dumps({"manager_pid": os.getpid(), "stage": "CHECKING"}))
                    try:
                        command = [sys.executable if x == "{python}" else x for x in check["argv"]]
                        result = run_bounded(command, copied, min(600, budget), budget,
                                             cancel=cancel, grace=60, env={"PYTHONDONTWRITEBYTECODE": "1"})
                    finally:
                        (directory / "active.json").unlink(missing_ok=True)
                    if not result.cleanup_confirmed or result.reason != "exited":
                        raise ValueError("Check interrupted: " + result.reason)
                    if capture(copied, names, contract.fingerprint).snapshot_id != snap.snapshot_id:
                        raise ValueError("Check modified input files")
                    inventory(copied, names)
                    results.append({"id": check["id"], "exit_code": result.returncode, "snapshot_id": snap.snapshot_id})
            return results

        try:
            provider = provider or CLIProviders()
            # Baseline prevents pre-existing passing checks from counting as new progress.
            if not history:
                checkpoint("CHECKING")
                baseline = snapshot("baseline")
                baseline_checks = checks(baseline, "baseline")
                run.seen_progress = ["check:" + x["id"] for x in baseline_checks if x["exit_code"] == 0]
                history.append({"kind": "baseline", "checks": baseline_checks})
            first = True
            while remaining():
                # A resumed run revalidates existing files before allowing more edits.
                if not (resume and first):
                    checkpoint("IMPLEMENTING")
                    ai_call(provider.implement, workspace, task["goal"], run.instructions or task["instructions"])
                first = False
                label = "cycle-" + str(run.cycle + 1) + "-" + uuid4().hex[:8]
                checkpoint("SNAPSHOTTING")
                snap = snapshot(label)
                checkpoint("CHECKING")
                results = checks(snap, label)
                packet = {"goal": task["goal"], "criteria": task["criteria"], "snapshot_id": snap.snapshot_id,
                          "files": {n: (directory / "snapshots" / label / "files" / n).read_text(encoding="utf-8") for n in names},
                          "checks": results, "history": history[-8:]}
                checkpoint("REVIEWING")
                review = ai_call(provider.judge, "code reviewer", packet, directory)
                validate_judgment(review, packet)
                checkpoint("AUDITING")
                audit_packet = dict(packet, review=review)
                audit = ai_call(provider.judge, "process and evidence auditor", audit_packet, directory)
                validate_judgment(audit, packet)
                passed = {x["id"] for x in results if x["exit_code"] == 0}
                met = [c["id"] for c in task["criteria"] if c["id"] in review["criteria_met"]
                       and c["id"] in audit["criteria_met"] and set(c["checks"]) <= passed]
                candidates = audit["next_instructions"] or review["next_instructions"]
                evidence = Evidence(snap.snapshot_id, review["snapshot_id"], audit["snapshot_id"],
                    passed_checks=sorted(passed), met_criteria=met, review=review["verdict"],
                    audit="complete" if audit["verdict"] == "pass" else "stop" if audit["verdict"] == "inconclusive" else "continue",
                    blocking_findings=review["blocking_findings"] + audit["blocking_findings"],
                    instructions=[x["action"] for x in candidates])
                checkpoint("DECIDING")
                inventory(workspace, names)
                decide_current(run, contract, evidence, now(), workspace, names)
                history.append({"snapshot_id": snap.snapshot_id, "checks": results,
                                "review": review, "audit": audit, "decision": run.reason})
                persist(directory, run, task, history, calls)
                if run.state in ("COMPLETED", "STOPPED"):
                    break
        except KeyboardInterrupt:
            run.stop("cancelled")
        except (ValueError, OSError, UnicodeError, TypeError, KeyError, RuntimeError) as exc:
            reason = "time_limit" if time.time() >= run.deadline else "cancelled" if cancel.is_set() else "runtime_error"
            run.stop(reason)
            # Only controlled error descriptions, not raw CLI output, are retained.
            history.append({"error": str(exc)[:500]})
        finally:
            persist(directory, run, task, history, calls)
        return run
