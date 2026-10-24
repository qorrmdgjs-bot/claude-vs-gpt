from pathlib import Path
import tempfile
import unittest
import json

from review_loop.installation import install_skill


class InstallationTests(unittest.TestCase):
    def test_install_and_refuse_overwrite(self):
        source = Path(__file__).resolve().parents[1] / "skills/review-loop"
        with tempfile.TemporaryDirectory() as temp:
            installed = install_skill(source, Path(temp) / "skills")
            original = (installed / "SKILL.md").read_bytes()
            with self.assertRaises(FileExistsError):
                install_skill(source, Path(temp) / "skills")
            self.assertEqual((installed / "SKILL.md").read_bytes(), original)

    def test_preserve_virtual_environment_interpreter(self):
        source = Path(__file__).resolve().parents[1] / "skills/review-loop"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "venv/bin/python"
            installed = install_skill(source, Path(temp) / "skills", python=path)
            self.assertEqual(json.loads((installed / "installation.json").read_text())["python"], str(path.absolute()))
