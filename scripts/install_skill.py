"""Run from source checkout after CLI installation; explicit destination is required."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from review_loop.installation import install_skill

parser = argparse.ArgumentParser()
parser.add_argument("--destination", required=True, type=Path,
                    help="Parent skills folder, e.g. ~/.agents/skills or ~/.claude/skills")
args = parser.parse_args()
print(install_skill(ROOT / "skills/review-loop", args.destination))
