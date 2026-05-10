"""HuggingFace Hub metadata resolver — never guess sizes or hashes.

Catalog entries declare (repo, revision, filenames). Real size / sha256 /
URLs come from the HF tree API at runtime, cached to disk so offline use
keeps working.

API shape (HF returns this for each file):
    {
      "type": "file",
      "path": "small-encoder.int8.onnx",
      "size": 112442483,
      "lfs": {
        "oid": "<sha256 hex>",
        "size": 112442483,
        ...
      }
    }

LFS files (>10 MB usually) carry a real sha256 in `lfs.oid`. Tiny non-LFS
files have only a git blob oid — irrelevant for integrity, fine to leave
as None and rely on the size check.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests

from core.paths import models_dir


_CACHE_FILENAME = ".catalog_cache.json"
_CACHE_TTL_SEC  = 7 * 24 * 3600   # 7 days; user can force-refresh via UI
_TIMEOUT        = (10.0, 30.0)


@dataclass(frozen=True)
class ResolvedFile:
    """One file's metadata after the catalog spec was resolved against HF."""
    repo: str
    revision: str
    path: str               # basename inside the repo (and locally)
    size: int               # exact byte count from HF
    sha256: str | None      # from lfs.oid, or None for tiny non-LFS files
    urls: tuple[str, ...]   # download URLs ranked: hf-mirror, HF official


# ── In-process + on-disk cache ───────────────────────────────────────────────

_MEM_CACHE: dict[str, dict] = {}     # key = "repo@revision"


def _cache_path() -> str:
    return os.path.join(models_dir(), _CACHE_FILENAME)


def _load_disk_cache() -> dict[str, dict]:
    path = _cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_disk_cache(cache: dict[str, dict]) -> None:
    path = _cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _ensure_mem_cache() -> None:
    if not _MEM_CACHE:
        _MEM_CACHE.update(_load_disk_cache())


# ── Public API ───────────────────────────────────────────────────────────────

def resolve_files(repo: str, revision: str, filenames: list[str],
                  *, force: bool = False) -> list[ResolvedFile]:
    """Return ResolvedFile for each requested filename.

    Hits HF tree API (1 request per repo, regardless of file count).
    Cache hit: returns cached metadata. Cache miss / stale / force=True:
    refetches and writes back. Network failure with no cache: raises
    ResolveError so the manager can surface it; cached fallback returns
    stale metadata silently.
    """
    _ensure_mem_cache()
    key = f"{repo}@{revision}"
    entry = _MEM_CACHE.get(key)
    fresh = (
        entry is not None
        and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SEC
    )

    if force or not fresh:
        try:
            entry = _fetch_repo_tree(repo, revision)
            _MEM_CACHE[key] = entry
            _save_disk_cache(_MEM_CACHE)
        except ResolveError:
            if entry is None:
                raise
            # Have stale cache — use it. UI should still show the freshness
            # warning, but downloads can proceed.

    files_by_path = {f["path"]: f for f in entry["files"]}
    out: list[ResolvedFile] = []
    for name in filenames:
        meta = files_by_path.get(name)
        if meta is None:
            raise ResolveError(
                f"File {name!r} not found in {repo}@{revision} "
                f"(repo has {len(files_by_path)} files; check basename)."
            )
        out.append(ResolvedFile(
            repo=repo,
            revision=revision,
            path=meta["path"],
            size=int(meta.get("size", 0)),
            sha256=meta.get("sha256"),
            urls=_build_urls(repo, revision, meta["path"]),
        ))
    return out


def repo_listing(repo: str, revision: str = "main",
                 *, force: bool = False) -> list[dict]:
    """Return the cached file list for a repo (raw HF metadata, dicts).

    Useful for UI features that want to show "all available quants" picker.
    """
    _ensure_mem_cache()
    key = f"{repo}@{revision}"
    entry = _MEM_CACHE.get(key)
    fresh = entry and (time.time() - entry.get("fetched_at", 0)) < _CACHE_TTL_SEC
    if force or not fresh:
        entry = _fetch_repo_tree(repo, revision)
        _MEM_CACHE[key] = entry
        _save_disk_cache(_MEM_CACHE)
    return list(entry["files"])


def invalidate_all() -> None:
    """Drop both in-memory and on-disk cache; next resolve hits HF."""
    _MEM_CACHE.clear()
    try:
        os.remove(_cache_path())
    except OSError:
        pass


def cache_age_sec(repo: str, revision: str) -> float | None:
    """Seconds since this repo's metadata was last fetched, or None if absent."""
    _ensure_mem_cache()
    entry = _MEM_CACHE.get(f"{repo}@{revision}")
    if entry is None:
        return None
    return max(0.0, time.time() - entry.get("fetched_at", 0))


# ── Internals ────────────────────────────────────────────────────────────────

class ResolveError(Exception):
    """HF API returned an error or the network is down."""


def _fetch_repo_tree(repo: str, revision: str) -> dict:
    """One GET against HF tree API. Returns slimmed cache entry."""
    url = (f"https://huggingface.co/api/models/{repo}/tree/{revision}"
           f"?recursive=true")
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ResolveError(f"HF API unreachable ({repo}@{revision}): {e}") from e

    if resp.status_code == 401 or resp.status_code == 403:
        raise ResolveError(
            f"HF returned {resp.status_code} for {repo}@{revision} "
            "— repo may be gated or private."
        )
    if resp.status_code == 404:
        raise ResolveError(f"HF repo not found: {repo}@{revision}")
    if resp.status_code >= 400:
        raise ResolveError(
            f"HF API error {resp.status_code} for {repo}@{revision}: "
            f"{resp.text[:200]}"
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise ResolveError(f"HF API returned non-JSON: {e}") from e

    if not isinstance(data, list):
        raise ResolveError(f"Unexpected HF API shape: {type(data).__name__}")

    files = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        files.append({
            "path": item.get("path", ""),
            "size": int(item.get("size", 0)),
            # lfs.oid is the real sha256 (HF's storage convention).
            "sha256": (item.get("lfs") or {}).get("oid"),
        })

    return {
        "repo": repo,
        "revision": revision,
        "fetched_at": time.time(),
        "files": files,
    }


def _build_urls(repo: str, revision: str, path: str) -> tuple[str, ...]:
    """Construct download URLs ranked by preference.

    hf-mirror first (China-friendly, identical path scheme), HF official as
    canonical fallback. ModelScope is intentionally NOT included by default
    — the org/repo namespaces don't mirror 1:1, and a blind URL just wastes
    one fallback attempt with a 404. Per-spec ModelScope override TBD.
    """
    return (
        f"https://hf-mirror.com/{repo}/resolve/{revision}/{path}",
        f"https://huggingface.co/{repo}/resolve/{revision}/{path}",
    )
