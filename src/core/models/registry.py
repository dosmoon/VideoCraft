"""On-disk registry of installed embedded-AI models.

Resolves each catalog spec against HF API (cached) to learn the real file
sizes / hashes, then scans <models_dir()>/<spec.target_subdir>/ to report
status: complete / partial / missing / unresolved.

`unresolved` is the new state for "we couldn't reach HF and have no
cached metadata" — UI shows it as "click Refresh Metadata" rather than
silently mis-reporting.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from core.models.catalog import CATALOG, ModelSpec, get
from core.models.downloader import verify_file
from core.models.hf_api import (
    ResolvedFile, resolve_files, ResolveError,
)


@dataclass
class FileStatus:
    relpath: str
    target_path: str
    expected_size: int       # 0 when unresolved
    expected_sha256: str | None
    bytes_on_disk: int
    complete: bool
    partial: bool


@dataclass
class InstalledStatus:
    spec: ModelSpec
    files: list[FileStatus] = field(default_factory=list)
    resolved: bool = False                # False = no HF metadata yet
    resolve_error: str | None = None      # populated when resolved=False
    resolved_files: list[ResolvedFile] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(f.expected_size for f in self.files)

    @property
    def complete(self) -> bool:
        return self.resolved and bool(self.files) and all(f.complete for f in self.files)

    @property
    def partial(self) -> bool:
        if not self.resolved or not self.files:
            return False
        return any(f.partial for f in self.files) and not self.complete

    @property
    def missing(self) -> bool:
        if not self.resolved:
            return False
        return all(not f.complete and not f.partial for f in self.files)

    @property
    def bytes_on_disk(self) -> int:
        return sum(f.bytes_on_disk for f in self.files)


def status_for(model_id: str, *, force_refresh: bool = False) -> InstalledStatus:
    """Resolve + scan one spec.

    `force_refresh=True` re-fetches HF metadata even if cache is fresh.
    Resolve failure with no cache leaves `resolved=False` so UI can prompt.
    """
    spec = get(model_id)
    try:
        resolved = resolve_files(
            spec.repo, spec.revision, list(spec.filenames),
            force=force_refresh,
        )
    except ResolveError as e:
        return InstalledStatus(spec=spec, resolved=False,
                               resolve_error=str(e))

    files: list[FileStatus] = []
    for rf in resolved:
        target = spec.file_path(rf.path)
        part = target + ".part"
        on_disk = 0
        complete = False
        partial = False
        if os.path.exists(target):
            try:
                on_disk = os.path.getsize(target)
            except OSError:
                on_disk = 0
            # Scan-time check: size only, no sha256 hash. Hashing every
            # GB-scale model file on every 5 s rescan froze the manager
            # UI for ~10 s. The downloader still hashes on write (atomic
            # rename gates on it) so anything that came through our own
            # download path is already integrity-checked once.
            complete = verify_file(
                target,
                expected_sha256=rf.sha256,
                expected_size=rf.size,
                check_sha256=False,
            )
        elif os.path.exists(part):
            try:
                on_disk = os.path.getsize(part)
                partial = True
            except OSError:
                on_disk = 0
        files.append(FileStatus(
            relpath=rf.path,
            target_path=target,
            expected_size=rf.size,
            expected_sha256=rf.sha256,
            bytes_on_disk=on_disk,
            complete=complete,
            partial=partial,
        ))
    return InstalledStatus(
        spec=spec,
        files=files,
        resolved=True,
        resolved_files=resolved,
    )


def scan(*, force_refresh: bool = False) -> dict[str, InstalledStatus]:
    """Per-spec status for every catalog entry. Network-free when cache fresh."""
    return {mid: status_for(mid, force_refresh=force_refresh) for mid in CATALOG}


def remove(model_id: str) -> int:
    """Delete final + .part files for a model. Returns bytes freed.

    Uses the spec's declared filenames so this works even when the catalog
    has never been resolved against HF (offline removal).
    """
    spec = get(model_id)
    freed = 0
    for name in spec.filenames:
        for path in (spec.file_path(name), spec.file_path(name) + ".part"):
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
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        return shutil.disk_usage(probe or os.getcwd()).free
    except OSError:
        return 0
