import json
from pathlib import Path
import tempfile
import unittest

from review_loop.core import Contract, Evidence, Run, review_due
from review_loop.cli import main, simulate
from review_loop.storage import locked, save


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.contract = Contract("goal", ("c1", "c2"), ("test",))
        self.run = Run.start("test-run", self.contract, 0)

    def evidence(self, **kwargs):
        args = dict(snapshot="s", review_snapshot="s", audit_snapshot="s", instructions=["fix"])
        args.update(kwargs)
        return Evidence(**args)

    def test_completion_requires_all_evidence(self):
        self.run.decide(self.contract, self.evidence(review="pass", audit="complete", met_criteria=["c1", "c2"]), 1)
        self.assertEqual(self.run.state, "IMPLEMENTING")
        self.run.decide(self.contract, self.evidence(review="pass", audit="complete", met_criteria=["c1", "c2"], passed_checks=["test"]), 2)
        self.assertEqual(self.run.state, "COMPLETED")

    def test_regression_does_not_count_again(self):
        self.run.decide(self.contract, self.evidence(met_criteria=["c1"], resolved_findings=["stable-id"]), 1)
        for now, criteria in ((2, []), (3, ["c1"]), (4, [])):
            self.run.decide(self.contract, self.evidence(met_criteria=criteria, resolved_findings=["stable-id"]), now)
        self.assertEqual((self.run.reason, self.run.stalled), ("no_progress", 3))

    def test_stale_approval_is_rejected(self):
        self.run.decide(self.contract, self.evidence(review_snapshot="old"), 1)
        self.assertEqual(self.run.reason, "stale_evidence")

    def test_instruction_limit(self):
        self.run.decide(self.contract, self.evidence(instructions=["a", "b", "c"]), 1)
        self.assertEqual(self.run.reason, "invalid_instructions")

    def test_deadline_wins_over_completion(self):
        self.run.decide(self.contract, self.evidence(review="pass", audit="complete", met_criteria=["c1", "c2"], passed_checks=["test"]), 14400)
        self.assertEqual(self.run.reason, "time_limit")

    def test_resume_keeps_deadline_and_requires_revalidation(self):
        self.run.stop("cancelled")
        self.run.resume(self.contract, 20, approved=True, cause_resolved=True)
        self.assertEqual((self.run.state, self.run.deadline), ("CHECKING", 14400))
        self.run.stop("cancelled")
        self.run.resume(self.contract, 14401, approved=True, cause_resolved=True)
        self.assertEqual(self.run.reason, "time_limit")

    def test_resume_requires_approval(self):
        self.run.stop("cancelled")
        with self.assertRaises(ValueError):
            self.run.resume(self.contract, 1)

    def test_changed_goal_and_clock_rollback_stop(self):
        changed = Contract("different", ("c1", "c2"), ("test",))
        self.run.decide(changed, self.evidence(), 1)
        self.assertEqual(self.run.reason, "contract_changed")
        run = Run.start("other", self.contract, 10)
        run.decide(self.contract, self.evidence(), 9)
        self.assertEqual(run.reason, "clock_invalid")

    def test_unknown_check_and_inconclusive_stop(self):
        for e, reason in [(self.evidence(passed_checks=["invented"]), "unknown_evidence"),
                          (self.evidence(review="inconclusive"), "review_or_audit_stop")]:
            run = Run.start("r", self.contract, 0)
            run.decide(self.contract, e, 1)
            self.assertEqual(run.reason, reason)

    def test_review_boundary(self):
        self.assertFalse(review_due(0, 3599))
        self.assertTrue(review_due(0, 3600))
        self.assertTrue(review_due(0, 1, instruction_done=True))


class LocalTests(unittest.TestCase):
    def test_three_scenarios(self):
        for scenario, expected in [("success", "all_evidence_passed"), ("stalled", "no_progress"), ("timeout", "time_limit")]:
            _, run = simulate(scenario)
            self.assertEqual(run.reason, expected)

    def test_atomic_save_and_lock(self):
        with tempfile.TemporaryDirectory(prefix="검증-") as temp:
            with locked(temp):
                with self.assertRaises(ValueError):
                    with locked(temp):
                        pass
                contract, run = simulate("success")
                save(temp, run, contract)
            saved = json.loads((Path(temp) / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["run"]["deadline"], 14400)
            self.assertFalse((Path(temp) / ".lock").exists())

    def test_cli_output_and_overwrite_refusal(self):
        with tempfile.TemporaryDirectory() as parent:
            path = Path(parent) / "한글 결과"
            self.assertEqual(main(["simulate", "--output", str(path)]), 0)
            before = (path / "state.json").read_bytes()
            self.assertEqual(main(["simulate", "--output", str(path)]), 2)
            self.assertEqual(before, (path / "state.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
