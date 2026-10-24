import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from review_loop.orchestrator import run_fixture
from review_loop.storage import locked


@unittest.skipUnless(os.name == "posix", "POSIX process backend required")
class FixtureTests(unittest.TestCase):
    def execute(self, scenario, **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            with locked(temp):
                run = run_fixture(temp, scenario, **kwargs)
            saved = json.loads((Path(temp) / "state.json").read_text())
            trace = json.loads((Path(temp) / "trace.json").read_text())
            self.assertEqual(saved["run"]["state"], run.state)
            return run, trace

    def test_full_success_and_stage_order(self):
        run, trace = self.execute("success")
        self.assertEqual((run.state, run.cycle), ("COMPLETED", 2))
        states = [x["stage"] for x in trace if "stage" in x]
        self.assertEqual(states[:6], ["IMPLEMENTING", "SNAPSHOTTING", "CHECKING", "REVIEWING", "AUDITING", "DECIDING"])

    def test_stalled(self):
        run, _ = self.execute("stalled")
        self.assertEqual((run.reason, run.cycle), ("no_progress", 3))

    def test_timeout_prevents_review(self):
        run, trace = self.execute("timeout", total_seconds=0.15)
        self.assertEqual(run.reason, "time_limit")
        self.assertNotIn("REVIEWING", [x.get("stage") for x in trace])

    def test_change_invalidates_passing_evidence(self):
        run, _ = self.execute("changed")
        self.assertEqual(run.reason, "workspace_changed")

    def test_cancel_before_launch(self):
        cancel = threading.Event()
        cancel.set()
        run, _ = self.execute("success", cancel=cancel)
        self.assertEqual(run.reason, "cancelled")
