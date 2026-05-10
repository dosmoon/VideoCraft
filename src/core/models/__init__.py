"""Embedded-AI model lifecycle: catalog, install state, download manager.

Layers:
  catalog.py    — declarative spec (id / repo / filenames). No sizes here.
  hf_api.py     — fetch real metadata from HuggingFace, cached on disk
  downloader.py — single-file Range-resume HTTP downloader with sha256
  registry.py   — scan <models>/, report installed / partial / missing /
                  unresolved per spec
  manager.py    — queue + worker thread + multi-source fallback, fed to UI

Owned by core/. UI lives in tools/models/. Per architecture rule, only
infrastructure-tier tools (AI Console, Model Manager) import this directly.
"""

from core.models.catalog import (
    CATALOG, ModelSpec,
    get, by_capability, by_tier,
    CAP_ASR, CAP_TTS, CAP_LLM, CAP_VAD,
    TIER_FIRST, TIER_RECOMMENDED, TIER_PREMIUM,
)
from core.models.hf_api import (
    ResolvedFile, resolve_files, repo_listing, invalidate_all,
    cache_age_sec, ResolveError,
)
from core.models.downloader import (
    DownloadProgress, CancelToken, download_file, DownloadError,
)
from core.models.registry import (
    InstalledStatus, FileStatus, scan, status_for, remove, reveal_in_explorer,
)
from core.models.manager import (
    DownloadJob, DownloadManager, manager,
)

__all__ = [
    "CATALOG", "ModelSpec",
    "get", "by_capability", "by_tier",
    "CAP_ASR", "CAP_TTS", "CAP_LLM", "CAP_VAD",
    "TIER_FIRST", "TIER_RECOMMENDED", "TIER_PREMIUM",
    "ResolvedFile", "resolve_files", "repo_listing", "invalidate_all",
    "cache_age_sec", "ResolveError",
    "DownloadProgress", "CancelToken", "download_file", "DownloadError",
    "InstalledStatus", "FileStatus", "scan", "status_for", "remove",
    "reveal_in_explorer",
    "DownloadJob", "DownloadManager", "manager",
]
