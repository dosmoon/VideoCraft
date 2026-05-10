"""On-disk registry of installed embedded-AI models.

Reads the catalog, scans <models_dir()>/<spec.target_subdir>/, reports
per-spec status: installed / partial / missing / extra. The "extra" case
catches files the user dropped manually that don't match any catalog entry —
shown in the manager UI so they aren't silently invisible.

No mutation here beyond `remove()` and the file-explorer reveal helper;
downloads and renames are the manager's job.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from core.models.catalog import CATALOG, ModelSpec, get
from core.models.downloader import verify_file


@dataclass
class FileStatus:
    relpath: str
    target_path: str
    expected_size: int
    bytes_on_disk: int       # 0 when file absent (final or .part)
    complete: bool           # final file present + size sane
    partial: bool            # only the .part exists (resumable)


@dataclass
class InstalledStatus:
    spec: ModelSpec
    files: list[FileStatus] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.files) and all(f.complete for f in self.files)

    @property
    def partial(self) -> bool:
        return any(f.partial for f in self.files) and not self.complete

    @property
    def missing(self) -> bool:
        return all(not f.complete and not f.partial for f in self.files)

    @property
    def bytes_on_disk(self) -> int:
        return sum(f.bytes_on_disk for f in self.files)


def status_for(model_id: str) -> InstalledStatus:
    spec = get(model_id)
    files = []
    for f in spec.files:
        target = spec.file_path(f.relpath)
        part = target + ".part"
        on_disk = 0
        complete = False
        partial = False
        if os.path.exists(target):
            try:
                on_disk = os.path.getsize(target)
            except OSError:
                on_disk = 0
            complete = verify_file(
                target,
                expected_sha256=f.sha256,
                expected_size=f.size_bytes,
            )
        elif os.path.exists(part):
            try:
                on_disk = os.path.getsize(part)
                partial = True
            except OSError:
                on_disk = 0
        files.append(FileStatus(
            relpath=f.relpath,
            target_path=target,
            expected_size=f.size_bytes,
            bytes_on_disk=on_disk,
            complete=complete,
            partial=partial,
        ))
    return InstalledStatus(spec=spec, files=files)


def scan() -> dict[str, InstalledStatus]:
    """Return per-spec status for every catalog entry."""
    return {mid: status_for(mid) for mid in CATALOG}


def remove(model_id: str) -> int:
    """Delete all files (final + .part) for a model. Returns bytes freed.

    Best-effort — missing files are skipped silently. After removal, if the
    spec's target_subdir is empty (no other models live there), the
    directory itself is removed too to avoid "ghost" empty folders in the
    user's models dir.
    """
    spec = get(model_id)
    freed = 0
    for f in spec.files:
        for path in (spec.file_path(f.relpath), spec.file_path(f.relpath) + ".part"):
            if os.path.exists(path):
                try:
                    freed += os.path.getsize(path)
                    os.remove(path)
                except OSError:
                    pass
    target = spec.target_dir()
    try:
        if os.path.isdir(target) and not os.listdir(target):
            os.rmdir(target)
    except OSError:
        pass
    return freed


def reveal_in_explorer(path: str) -> None:
    """Open the OS file manager focused on `path`. Best-effort — errors swallowed."""
    if not path:
        return
    try:
        if sys.platform == "win32":
            if os.path.isdir(path):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                # /select, highlights the file in Explorer
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if not os.path.isdir(path) else "", path])
        else:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(["xdg-open", target])
    except Exception:
        pass


def disk_free_bytes(path: str) -> int:
    """Free bytes on the volume containing `path`. Returns 0 on error."""
    try:
        # Walk up to the first existing ancestor (path may not exist yet).
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        return shutil.disk_usage(probe or os.getcwd()).free
    except OSError:
        return 0
