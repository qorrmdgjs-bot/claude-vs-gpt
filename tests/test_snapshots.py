from pathlib import Path
import os
import tempfile
import unittest

from review_loop.core import Contract, Evidence, Run
from review_loop.snapshots import capture, changes, decide_current, validate_paths
from review_loop.cli import main


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "작업"
        self.root.mkdir()
        (self.root / "a.txt").write_text("before", encoding="utf-8")
        self.contract = Contract("goal", ("c",), ("test",))

    def snap(self, paths=("a.txt",), **kwargs):
        return capture(self.root, paths, self.contract.fingerprint, **kwargs)

    def test_identity_and_copy_are_content_based(self):
        old = self.snap(destination=self.base / "saved")
        os.utime(self.root / "a.txt", None)
        self.assertEqual(old.snapshot_id, self.snap().snapshot_id)
        (self.root / "a.txt").write_text("after", encoding="utf-8")
        self.assertEqual((self.base / "saved/files/a.txt").read_text(), "before")
        self.assertNotEqual(old.snapshot_id, self.snap().snapshot_id)
        with self.assertRaises(ValueError):
            self.snap(destination=self.base / "saved")

    def test_diff_add_modify_delete(self):
        old = self.snap()
        (self.root / "a.txt").write_text("changed")
        (self.root / "b.txt").write_text("new")
        new = self.snap(("a.txt", "b.txt"))
        self.assertEqual(changes(old, new), {"added": ["b.txt"], "deleted": [], "modified": ["a.txt"]})
        self.assertEqual(changes(new, self.snap(("b.txt",)))["deleted"], ["a.txt"])

    def test_unsafe_and_ambiguous_paths(self):
        for paths in [("../escape",), ("/absolute",), ("a/./b",), ("a//b",),
                      ("C:/file",), ("a\\b",), (".git/config",), ("A", "a"), ()]:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                validate_paths(paths)

    def test_links_are_rejected(self):
        for target in (self.root / "a.txt", self.base):
            link = self.root / "link"
            try:
                link.symlink_to(target, target_is_directory=target.is_dir())
            except OSError:
                self.skipTest("Symlink creation not permitted")
            try:
                with self.assertRaises(ValueError):
                    self.snap(("link/a.txt",) if target.is_dir() else ("link",))
            finally:
                link.unlink()

    def test_hardlink_rejected(self):
        os.link(self.root / "a.txt", self.root / "hard")
        with self.assertRaises(ValueError):
            self.snap()

    def test_missing_oversized_and_inside_destination(self):
        with self.assertRaises(OSError):
            self.snap(("missing",))
        with self.assertRaises(ValueError):
            self.snap(max_bytes=1)
        with self.assertRaises(ValueError):
            self.snap(destination=self.root / "snapshot")

    def test_file_change_invalidates_completion(self):
        old = self.snap()
        e = Evidence(old.snapshot_id, old.snapshot_id, old.snapshot_id,
                     passed_checks=["test"], met_criteria=["c"], review="pass", audit="complete")
        run = Run.start("r", self.contract, 0)
        decide_current(run, self.contract, e, 1, self.root, ["a.txt"])
        self.assertEqual(run.state, "COMPLETED")
        (self.root / "a.txt").write_text("changed")
        decide_current(run, self.contract, e, 2, self.root, ["a.txt"])
        self.assertEqual((run.state, run.reason), ("STOPPED", "workspace_changed"))

    def test_deleted_file_blocks_decision(self):
        old = self.snap()
        (self.root / "a.txt").unlink()
        run = Run.start("r", self.contract, 0)
        e = Evidence(old.snapshot_id, old.snapshot_id, old.snapshot_id)
        decide_current(run, self.contract, e, 1, self.root, ["a.txt"])
        self.assertEqual(run.reason, "workspace_unverifiable")

    def test_snapshot_cli(self):
        target = self.base / "cli-copy"
        self.assertEqual(main(["snapshot", "--workspace", str(self.root), "--file", "a.txt", "--output", str(target)]), 0)
        self.assertEqual((target / "files/a.txt").read_text(), "before")


if __name__ == "__main__":
    unittest.main()
