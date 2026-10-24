import json
from pathlib import Path
import tempfile
import unittest

from review_loop.runtime import run_live, load_task
from review_loop.providers import validate_judgment


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/calculator.json"


class FakeProvider:
    def __init__(self, stalled=False, tamper=False):
        self.roles = []
        self.stalled, self.tamper = stalled, tamper

    def implement(self, workspace, goal, instructions, remaining, cancel):
        if self.tamper:
            (workspace / "check.py").write_text("pass\n")
        elif not self.stalled:
            (workspace / "answer.py").write_text("def add(a,b):\n    return a+b\n")

    def judge(self, role, packet, cwd, remaining, cancel):
        self.roles.append(role)
        passed = all(c["exit_code"] == 0 for c in packet["checks"])
        return {"snapshot_id": packet["snapshot_id"], "verdict": "pass" if passed else "changes_requested",
                "criteria_met": ["addition"] if passed else [], "blocking_findings": [],
                "next_instructions": [] if passed else [{"criterion_id": "addition", "action": "Fix addition"}]}


class RuntimeTests(unittest.TestCase):
    def test_full_run_separate_judgments(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider()
            run = run_live(EXAMPLE, Path(temp) / "run", provider=provider)
            self.assertEqual(run.state, "COMPLETED")
            self.assertEqual(provider.roles, ["code reviewer", "process and evidence auditor"])
            saved = json.loads((Path(temp) / "run/state.json").read_text())
            self.assertEqual(saved["calls"], 3)
            self.assertEqual(saved["history"][0]["checks"][0]["exit_code"], 1)

    def test_stall_and_resume_preserve_deadline(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "run"
            run = run_live(EXAMPLE, directory, provider=FakeProvider(stalled=True))
            self.assertEqual(run.reason, "no_progress")
            deadline = run.deadline
            # Revalidation first; no implicit edit on resume.
            run = run_live(None, directory, resume=True, provider=FakeProvider(stalled=True))
            self.assertEqual(run.deadline, deadline)
            self.assertEqual(run.state, "STOPPED")

    def test_check_tampering_stops_before_review(self):
        with tempfile.TemporaryDirectory() as temp:
            provider = FakeProvider(tamper=True)
            run = run_live(EXAMPLE, Path(temp) / "run", provider=provider)
            self.assertEqual(run.state, "STOPPED")
            self.assertEqual(provider.roles, [])

    def test_invalid_model_output(self):
        packet = {"snapshot_id": "s", "criteria": [{"id": "c"}]}
        with self.assertRaises(ValueError):
            validate_judgment({"verdict": "pass"}, packet)

    def test_suspected_secret_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            task = json.loads(EXAMPLE.read_text())
            task["files"]["answer.py"] = "sk-" + "a" * 30
            path = Path(temp) / "task.json"
            path.write_text(json.dumps(task))
            with self.assertRaises(ValueError):
                load_task(path)
