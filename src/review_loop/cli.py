import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from uuid import uuid4

from .core import Contract, Evidence, Run, digest
from .storage import locked, save
from .snapshots import capture


def simulate(scenario):
    contract = Contract("가상 계산기 구현", ("addition", "validation"), ("unit",))
    run = Run.start(str(uuid4()), contract, 0.0)
    for cycle in range(1, 6):
        now = 14400.0 if scenario == "timeout" else cycle * 3600.0
        snapshot = digest({"fake_cycle": cycle})
        complete = scenario == "success" and cycle == 2
        e = Evidence(snapshot, snapshot, snapshot,
                     passed_checks=["unit"] if complete else [],
                     met_criteria=list(contract.criteria) if complete else [],
                     review="pass" if complete else "changes_requested",
                     audit="complete" if complete else "continue",
                     instructions=["입력 검증을 구현하고 가상 검사 결과를 제공"])
        run.decide(contract, e, now)
        if run.state in ("STOPPED", "COMPLETED"):
            break
    return contract, run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local prototype: no AI; fixture mode runs fixed fake workers.")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("simulate")
    demo.add_argument("--scenario", choices=("success", "stalled", "timeout"), default="success")
    demo.add_argument("--output", required=True, type=Path, help="저장소 밖의 새 로컬 폴더")
    fixture = sub.add_parser("fixture", help="Real child processes with fake review/audit")
    fixture.add_argument("--scenario", choices=("success", "stalled", "timeout", "changed"), default="success")
    fixture.add_argument("--output", required=True, type=Path)
    live = sub.add_parser("run", help="Trusted scratch task with real CLI calls; never publishes")
    live.add_argument("--task", required=True, type=Path)
    live.add_argument("--output", required=True, type=Path)
    live.add_argument("--allow-live", action="store_true")
    resume = sub.add_parser("resume")
    resume.add_argument("directory", type=Path)
    resume.add_argument("--allow-live", action="store_true")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("directory", type=Path)
    sub.add_parser("doctor")
    status = sub.add_parser("status")
    status.add_argument("directory", type=Path)
    snap = sub.add_parser("snapshot", help="Explicit local files only; copies may contain sensitive data")
    snap.add_argument("--workspace", required=True, type=Path)
    snap.add_argument("--file", action="append", required=True)
    snap.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            import shutil, platform
            print(json.dumps({"python": platform.python_version(), "platform": platform.system(),
                "codex_installed": shutil.which("codex") is not None,
                "claude_installed": shutil.which("claude") is not None,
                "auth": "Run codex login status and claude auth status privately",
                "scope": "trusted scratch tasks; not a security sandbox"}, indent=2))
            return 0
        if args.command == "cancel":
            if not (args.directory / "state.json").is_file():
                raise ValueError("Run state not found")
            (args.directory / "cancel.request").touch(exist_ok=True)
            return 0
        if args.command in ("run", "resume"):
            if not args.allow_live:
                raise ValueError("Real CLI calls transmit task data; add --allow-live for an approved scratch task")
            from .runtime import run_live
            result = run_live(args.task if args.command == "run" else None,
                              args.output if args.command == "run" else args.directory,
                              resume=args.command == "resume")
            print(result.state + ": " + result.reason)
            return 0 if result.state == "COMPLETED" else 1
        if args.command == "snapshot":
            target = args.output.resolve()
            if any((p / ".git").exists() for p in (target, *target.parents)):
                raise ValueError("Snapshot output must be outside Git repositories")
            # Standalone demonstration context; cannot serve as a real run approval.
            result = capture(args.workspace.resolve(), args.file,
                             digest({"mode": "standalone_snapshot"}), destination=target)
            print(result.snapshot_id)
            return 0
        if args.command == "status":
            payload = json.loads((args.directory / "state.json").read_text(encoding="utf-8"))
            print(json.dumps(payload["run"], ensure_ascii=False, indent=2))
            return 0
        output = args.output.resolve()
        # Refuse any directory inside a Git checkout, or an existing nonempty directory.
        if any((p / ".git").exists() for p in (output, *output.parents)):
            raise ValueError("Output must be outside Git repositories")
        if output.exists() and any(output.iterdir()):
            raise ValueError("Output directory must be new or empty")
        with locked(output):
            if args.command == "fixture":
                from .orchestrator import run_fixture
                run_fixture(output, args.scenario, total_seconds=0.2 if args.scenario == "timeout" else 5)
            else:
                contract, run = simulate(args.scenario)
                save(output, run, contract)
        print(str(output / "REPORT.md"))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
