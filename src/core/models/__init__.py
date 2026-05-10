"""Embedded-AI model lifecycle: catalog, install state, download manager.

Three layers:
  catalog.py    — declarative spec of known models (id / files / sources)
  downloader.py — single-file Range-resume HTTP downloader with sha256
  registry.py   — scan <models>/, report what's installed / partial / extra
  manager.py    — queue + multi-source fallback + disk preflight, fed to UI

Owned by core/ — UI lives in tools/models/. Per architecture rule, only the
"infrastructure" tools (AI Console / model manager) are allowed to import
this module directly.
"""

from core.models.catalog import (
    CATALOG, ModelSpec, ModelFile,
    get, by_capability, by_tier,
)
from core.models.downloader import (
    DownloadProgress, CancelToken, download_file, DownloadError,
)
from core.models.registry import (
    InstalledStatus, scan, status_for, remove, reveal_in_explorer,
)
from core.models.manager import (
    DownloadJob, DownloadManager, manager,
)

__all__ = [
    "CATALOG", "ModelSpec", "ModelFile",
    "get", "by_capability", "by_tier",
    "DownloadProgress", "CancelToken", "download_file", "DownloadError",
    "InstalledStatus", "scan", "status_for", "remove", "reveal_in_explorer",
    "DownloadJob", "DownloadManager", "manager",
]
