"""Use the interpreter recorded during skill installation, not the agent's PATH."""
import json
import os
from pathlib import Path
import sys

config = Path(__file__).resolve().parents[1] / "installation.json"
if not config.exists():
    raise SystemExit("Install this skill with scripts/install_skill.py after installing the Python package.")
python = json.loads(config.read_text(encoding="utf-8"))["python"]
os.execv(python, [python, "-m", "review_loop.cli", *sys.argv[1:]])
