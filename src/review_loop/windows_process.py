"""Windows Job Object backend. Bootstrap waits until job assignment before launch."""
import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def run_windows(argv, cwd, timeout, remaining, cancel, grace, env,
                input_stream, output_stream, output_limit):
    from .processes import ProcessResult
    if not isinstance(argv, (list, tuple)) or not argv or not argv[0] or not all(isinstance(x, str) for x in argv):
        raise ValueError("Argument array required")
    if any(not math.isfinite(x) or x < 0 for x in (timeout, remaining, grace)):
        raise ValueError("Invalid time limit")
    if min(timeout, remaining) <= 0:
        return ProcessResult("time_limit", -1, 0, True)
    if cancel is not None and cancel.is_set():
        return ProcessResult("cancelled", -1, 0, True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k.AssignProcessToJobObject.restype = wintypes.BOOL
    k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateJobObject.restype = wintypes.BOOL
    k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    k.QueryInformationJobObject.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetInformationJobObject.restype = wintypes.BOOL
    class Limits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active_limit", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes")]
    class Extended(ctypes.Structure):
        _fields_ = [("basic", Limits), ("io", IO), ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
    class Accounting(ctypes.Structure):
        _fields_ = [(x, ctypes.c_longlong) for x in ("user", "kernel", "period_user", "period_kernel")] + [(x, wintypes.DWORD) for x in ("faults", "total", "active", "terminated")]
    job = k.CreateJobObjectW(None, None)
    if not job:
        raise OSError("Cannot create Windows job")
    limits = Extended()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        k.CloseHandle(job)
        raise OSError("Cannot configure Windows job; launch refused")
    process = None
    start = time.monotonic()
    reason, confirmed = "exited", False
    # Gate path is private; no credentials/prompt are passed as command arguments.
    with tempfile.TemporaryDirectory(prefix="review-loop-gate-") as temp:
        gate = Path(temp) / "ready"
        bootstrap = ("import pathlib,time,subprocess,sys,json; "
                     "gate=pathlib.Path(sys.argv[1]); "
                     "exec('while not gate.exists():\\n time.sleep(0.01)'); "
                     "raise SystemExit(subprocess.call(json.loads(sys.argv[2]),stdin=sys.stdin.buffer))")
        clean = {x: os.environ[x] for x in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if x in os.environ}
        clean.update(env or {})
        try:
            process = subprocess.Popen([sys.executable, "-c", bootstrap, str(gate), json.dumps(argv)],
                cwd=cwd, env=clean, stdin=input_stream if input_stream is not None else subprocess.DEVNULL,
                stdout=output_stream if output_stream is not None else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            if not k.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
                process.kill()
                process.wait()
                raise OSError("Job assignment failed; command was not released")
            gate.touch()
            while True:
                elapsed = time.monotonic() - start
                if cancel is not None and cancel.is_set():
                    reason = "cancelled"
                    break
                if output_stream is not None and os.fstat(output_stream.fileno()).st_size > output_limit:
                    reason = "output_limit"
                    break
                if elapsed >= min(timeout, remaining):
                    reason = "total_time_limit" if remaining <= timeout else "timeout"
                    break
                if process.poll() is not None:
                    break
                time.sleep(0.02)
        finally:
            # Job termination covers descendants; a console signal alone cannot guarantee this.
            k.TerminateJobObject(job, 1)
            if process is not None:
                try:
                    process.wait(timeout=max(1, grace))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            end = time.monotonic() + max(1, grace)
            while time.monotonic() < end:
                accounting = Accounting()
                if k.QueryInformationJobObject(job, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None) and accounting.active == 0:
                    confirmed = True
                    break
                time.sleep(0.02)
            k.CloseHandle(job)
    return ProcessResult(reason, process.returncode if process is not None else -1,
                         time.monotonic() - start, confirmed)
