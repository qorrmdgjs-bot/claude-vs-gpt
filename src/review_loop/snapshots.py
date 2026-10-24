"""Explicit-file snapshots for quiescent workspaces, not an OS security boundary."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import unicodedata

from .core import digest


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    contract_hash: str
    files: tuple

    @property
    def manifest(self):
        return dict(self.files)


def validate_paths(paths):
    if not paths:
        raise ValueError("Explicit nonempty file allowlist required")
    result, names = [], set()
    for name in paths:
        if not isinstance(name, str) or not name or "\\" in name or ":" in name:
            raise ValueError("Use portable relative POSIX file paths")
        p = PurePosixPath(name)
        if p.is_absolute() or any(x in ("", ".", "..") for x in name.split("/")):
            raise ValueError("Unsafe file path")
        normalized = unicodedata.normalize("NFC", name).casefold()
        if normalized in names:
            raise ValueError("Duplicate or cross-platform ambiguous paths")
        if any(x.casefold() == ".git" for x in p.parts):
            raise ValueError("Git metadata cannot be snapshotted")
        names.add(normalized)
        result.append(name)
    return sorted(result)


def read_regular(root, name, max_bytes):
    path = root
    for component in PurePosixPath(name).parts:
        path = path / component
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Links and Windows reparse points are forbidden")
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Only regular, non-hardlinked files are supported")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(str(path), flags)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("File changed during capture")
        if (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino):
            raise ValueError("File replaced during capture")
        content = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    if len(content) > max_bytes:
        raise ValueError("Snapshot file size limit exceeded")
    def signature(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if signature(before) != signature(after) or signature(after) != signature(path.lstat()):
        raise ValueError("File changed during capture")
    return content


def capture(root, paths, contract_hash, destination=None, max_bytes=10 * 1024 * 1024):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise ValueError("Workspace root must be a canonical, non-linked directory")
    names = validate_paths(paths)
    contents = {name: read_regular(root, name, max_bytes) for name in names}
    # Second pass catches ordinary edits between individual file reads.
    if any(read_regular(root, n, max_bytes) != contents[n] for n in names):
        raise ValueError("Workspace changed during capture")
    files = tuple((n, sha256(contents[n]).hexdigest()) for n in names)
    snapshot = Snapshot(digest({"contract": contract_hash, "files": files}), contract_hash, files)
    if destination is not None:
        target = Path(destination).resolve()
        if target == root or root in target.parents:
            raise ValueError("Snapshot destination must be outside workspace")
        if target.exists():
            raise ValueError("Snapshot destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=str(target.parent)))
        try:
            for name, content in contents.items():
                out = staging / "files" / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(content)
            (staging / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "snapshot_id": snapshot.snapshot_id,
                "contract_hash": contract_hash, "files": dict(files)
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            # A unique destination is required; callers must serialize capture operations.
            if target.exists():
                raise ValueError("Snapshot destination already exists")
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return snapshot


def changes(old, new):
    a, b = old.manifest, new.manifest
    return {"added": sorted(b.keys() - a.keys()), "deleted": sorted(a.keys() - b.keys()),
            "modified": sorted(n for n in a.keys() & b.keys() if a[n] != b[n])}


def decide_current(run, contract, evidence, now, root, paths):
    """Recheck allowed inputs immediately before pure decision, including completed runs."""
    try:
        current = capture(root, paths, contract.fingerprint)
    except (OSError, ValueError):
        run.stop("workspace_unverifiable")
        return
    if current.snapshot_id != evidence.snapshot:
        run.stop("workspace_changed")
        return
    run.decide(contract, evidence, now)
