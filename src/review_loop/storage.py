"""Atomic local writes. Callers must use a private directory outside repositories."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager


@contextmanager
def locked(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".lock"
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Run directory is locked; inspect owner before removing a stale lock")
    try:
        os.close(fd)
        yield directory
    finally:
        path.unlink()


def atomic_write(path, text):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".pending-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(directory, run, contract):
    payload = {"schema_version": 1, "mode": "simulation", "contract": asdict(contract), "run": asdict(run)}
    atomic_write(Path(directory) / "state.json", json.dumps(payload, ensure_ascii=False, indent=2))
    atomic_write(Path(directory) / "REPORT.md", report(run))


def report(run):
    return ("# 로컬 검증 결과\n\n실제 AI는 호출하지 않았습니다. fixture 모드의 작업·검사는 고정된 가짜 예제입니다.\n\n"
            + "- 상태: " + run.state + "\n- 원인: " + run.reason
            + "\n- 검토 주기: " + str(run.cycle) + "\n- 연속 무진전: " + str(run.stalled)
            + "\n- 모의 시작: " + str(run.started) + "\n- 고정 마감: " + str(run.deadline) + "\n")
