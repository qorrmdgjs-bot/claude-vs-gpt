"""Bounded subprocess execution. POSIX groups supported; Windows backend pending."""
from dataclasses import dataclass
import math
import os
import signal
import subprocess
import time


@dataclass(frozen=True)
class ProcessResult:
    reason: str
    returncode: int
    duration: float
    cleanup_confirmed: bool


def _group_exists(group):
    try:
        os.killpg(group, 0)
        return True
    except ProcessLookupError:
        return False


def run_bounded(argv, cwd, timeout, remaining, cancel=None, grace=1.0,
                env=None, poll=0.02, input_stream=None, output_stream=None,
                output_limit=2 * 1024 * 1024):
    """No shell, inherited credentials, or captured raw logs by default.

    remaining is the caller's remaining total budget at launch, in seconds.
    Caller must quiesce all writers before snapshotting. This is not a sandbox.
    """
    if os.name == "nt":
        from .windows_process import run_windows
        return run_windows(argv, cwd, timeout, remaining, cancel, grace, env,
                           input_stream, output_stream, output_limit)
    if not isinstance(argv, (list, tuple)) or not argv or not argv[0] or not all(isinstance(x, str) for x in argv):
        raise ValueError("Nonempty argument array required")
    if any(not math.isfinite(x) or x < 0 for x in (timeout, remaining, grace)) or not math.isfinite(poll) or poll <= 0:
        raise ValueError("Invalid time limits")
    if remaining <= 0 or timeout <= 0:
        return ProcessResult("time_limit", -1, 0, True)
    if cancel is not None and cancel.is_set():
        return ProcessResult("cancelled", -1, 0, True)
    start = time.monotonic()
    # A deliberately minimal environment; explicit env must be approved by caller.
    clean_env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP") if key in os.environ}
    if env is not None:
        clean_env.update(env)
    process = subprocess.Popen(argv, cwd=cwd, env=clean_env,
                               stdin=input_stream if input_stream is not None else subprocess.DEVNULL,
                               stdout=output_stream if output_stream is not None else subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    group = process.pid
    reason = "exited"
    confirmed = False

    def send(sig):
        try:
            os.killpg(group, sig)
        except ProcessLookupError:
            pass

    try:
        while True:
            elapsed = time.monotonic() - start
            if output_stream is not None and os.fstat(output_stream.fileno()).st_size > output_limit:
                reason = "output_limit"
                break
            if cancel is not None and cancel.is_set():
                reason = "cancelled"
                break
            if elapsed >= min(timeout, remaining):
                reason = "total_time_limit" if remaining <= timeout else "timeout"
                break
            if process.poll() is not None:
                break
            time.sleep(min(poll, max(0, min(timeout, remaining) - elapsed)))
    finally:
        # Also terminate children left behind after the parent exits normally.
        process.poll()
        if _group_exists(group):
            send(signal.SIGTERM)
            end = time.monotonic() + grace
            while time.monotonic() < end:
                process.poll()
                if not _group_exists(group):
                    break
                time.sleep(poll)
            if _group_exists(group):
                send(signal.SIGKILL)
        try:
            process.wait(timeout=max(grace, 0.1))
        except subprocess.TimeoutExpired:
            send(signal.SIGKILL)
        end = time.monotonic() + max(grace, 0.1)
        while time.monotonic() < end:
            process.poll()
            if not _group_exists(group):
                confirmed = True
                break
            time.sleep(poll)
    return ProcessResult(reason, process.returncode if process.returncode is not None else -1,
                         time.monotonic() - start, confirmed)


def apply_process_result(run, result):
    """Uncertain cleanup forbids snapshots and review."""
    if not result.cleanup_confirmed:
        run.stop("process_cleanup_unconfirmed")
    elif result.reason in ("total_time_limit", "time_limit"):
        run.stop("time_limit")
    elif result.reason == "cancelled":
        run.stop("cancelled")
    elif result.reason == "output_limit":
        run.stop("output_limit")
    elif result.reason == "timeout":
        run.state, run.reason = "SNAPSHOTTING", "interrupted_work_requires_review"
    elif result.returncode != 0:
        run.stop("process_failed")
    else:
        run.state, run.reason = "SNAPSHOTTING", "work_exited"
