"""Install only a packaged skill; never overwrite an existing skill."""
from pathlib import Path
import shutil
import json
import sys


def install_skill(source, parent, python=None):
    source, parent = Path(source).resolve(), Path(parent).expanduser()
    if not (source / "SKILL.md").is_file():
        raise ValueError("Skill source is missing SKILL.md")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / "review-loop"
    # mkdir is exclusive; no overwrite even in a concurrent install.
    destination.mkdir()
    try:
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ValueError("Skill source links are not supported")
            target = destination / item.relative_to(source)
            if item.is_dir():
                target.mkdir(exist_ok=True)
            else:
                shutil.copyfile(item, target)
        # Preserve venv symlinks: resolving them would silently select the system interpreter.
        (destination / "installation.json").write_text(json.dumps({"python": str(Path(python or sys.executable).absolute())}), encoding="utf-8")
    except Exception:
        shutil.rmtree(destination)
        raise
    return destination
