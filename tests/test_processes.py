import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

from review_loop.processes import run_bounded, apply_process_result, ProcessResult
from review_loop.core import Run, Contract


@unittest.skipUnless(os.name == "posix", "POSIX backend only; Windows refuses launch")
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_code(self, code, **kwargs):
        options = dict(timeout=2, remaining=3, grace=0.1)
        options.update(kwargs)
        return run_bounded([sys.executable, "-c", code], self.temp.name, **options)

    def test_exit_code(self):
        result = self.run_code("raise SystemExit(7)")
        self.assertEqual((result.reason, result.returncode, result.cleanup_confirmed), ("exited", 7, True))

    def test_cleanup_gate(self):
        for result, state, reason in [
            (ProcessResult("exited", 0, 1, False), "STOPPED", "process_cleanup_unconfirmed"),
            (ProcessResult("total_time_limit", -15, 1, True), "STOPPED", "time_limit"),
            (ProcessResult("timeout", -15, 1, True), "SNAPSHOTTING", "interrupted_work_requires_review"),
            (ProcessResult("cancelled", -15, 1, True), "STOPPED", "cancelled")]:
            run = Run.start("r", Contract("goal", ("c",), ("t",)), 0)
            apply_process_result(run, result)
            self.assertEqual((run.state, run.reason), (state, reason))

    def test_timeout_and_total_limit(self):
        for timeout, remaining, reason in [(0.1, 2, "timeout"), (2, 0.1, "total_time_limit")]:
            result = self.run_code("import time; time.sleep(30)", timeout=timeout, remaining=remaining)
            self.assertEqual(result.reason, reason)
            self.assertTrue(result.cleanup_confirmed)
            self.assertLess(result.duration, 2)

    def test_cancel(self):
        cancel = threading.Event()
        timer = threading.Timer(0.1, cancel.set)
        timer.start()
        self.addCleanup(timer.cancel)
        result = self.run_code("import time; time.sleep(30)", cancel=cancel)
        self.assertEqual(result.reason, "cancelled")
        self.assertTrue(result.cleanup_confirmed)

    def test_no_budget_does_not_launch(self):
        marker = Path(self.temp.name) / "should-not-exist"
        result = self.run_code("from pathlib import Path; Path('should-not-exist').touch()", remaining=0)
        self.assertEqual(result.reason, "time_limit")
        self.assertFalse(marker.exists())

    def test_credentials_not_inherited(self):
        os.environ["REVIEW_LOOP_TEST_SECRET"] = "fake-test-value"
        self.addCleanup(os.environ.pop, "REVIEW_LOOP_TEST_SECRET", None)
        result = self.run_code("import os; assert 'REVIEW_LOOP_TEST_SECRET' not in os.environ")
        self.assertEqual(result.returncode, 0)

    def test_ignoring_term_is_killed(self):
        result = self.run_code("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)", timeout=0.2)
        self.assertTrue(result.cleanup_confirmed)
        self.assertNotEqual(result.returncode, 0)

    def test_child_writer_stops(self):
        child_code = "import time\nfrom pathlib import Path\np=Path('heartbeat')\nwhile True:\n p.write_text(str(time.time()))\n time.sleep(0.01)\n"
        code = "import subprocess,sys,time,signal\nchild = subprocess.Popen([sys.executable, '-c', " + repr(child_code) + "])\n" + """
def finish(*args):
    try: child.wait(timeout=1)
    except subprocess.TimeoutExpired: child.kill(); child.wait()
    raise SystemExit(0)
signal.signal(signal.SIGTERM, finish)
time.sleep(30)
"""
        result = self.run_code(code, timeout=0.3, grace=1)
        marker = Path(self.temp.name) / "heartbeat"
        self.assertTrue(marker.exists())
        before = marker.read_bytes()
        time.sleep(0.1)
        self.assertEqual(marker.read_bytes(), before)
        self.assertTrue(result.cleanup_confirmed)


if __name__ == "__main__":
    unittest.main()
