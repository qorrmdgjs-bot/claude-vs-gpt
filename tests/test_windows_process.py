import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from review_loop.processes import run_bounded


@unittest.skipUnless(os.name == "nt", "Windows Job Object tests")
class WindowsProcessTests(unittest.TestCase):
    def test_exit_and_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            normal = run_bounded([sys.executable, "-c", "raise SystemExit(7)"], temp, 5, 10)
            self.assertEqual(normal.returncode, 7)
            self.assertTrue(normal.cleanup_confirmed)
            timeout = run_bounded([sys.executable, "-c", "import time;time.sleep(30)"], temp, 0.3, 10)
            self.assertEqual(timeout.reason, "timeout")
            self.assertTrue(timeout.cleanup_confirmed)

    def test_cancel_without_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            event = threading.Event()
            event.set()
            result = run_bounded([sys.executable, "-c", "raise Exception()"], temp, 5, 10, cancel=event)
            self.assertEqual(result.reason, "cancelled")
