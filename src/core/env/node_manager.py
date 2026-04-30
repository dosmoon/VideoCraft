"""Managed Node.js install — download portable Node into user_data/runtimes/.

Downloads the official node-v{X}-win-x64.zip from nodejs.org, verifies
SHA256 against the published SHASUMS256.txt, extracts to a tmp dir, and
atomic-renames to the final location. Failures clean up; nothing partial
is left behind.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
import zipfile
from typing import Callable

from core import user_data


# Pinned Node LTS for managed install. Bump deliberately; never auto-upgrade.
_NODE_VERSION = "22.11.0"
_NODE_PLATFORM = "win-x64"
_NODE_ZIP_BASENAME = f"node-v{_NODE_VERSION}-{_NODE_PLATFORM}"
_NODE_DIST_BASE = "https://nodejs.org/dist"


def _runtimes_root() -> str:
    """Return <user_data>/runtimes/, creating it on demand."""
    path = user_data.path("runtimes")
    os.makedirs(path, exist_ok=True)
    return path


def _managed_node_dir() -> str:
    """Return the directory where a managed Node install lives (may not exist)."""
    return os.path.join(_runtimes_root(), "node")


def managed_node_path() -> str | None:
    """Return path to managed Node executable, or None if not installed."""
    exe = os.path.join(_managed_node_dir(), "node.exe")
    return exe if os.path.isfile(exe) else None


# ── Download / install internals ─────────────────────────────────────────────


def _stream_download(url: str, dest: str, on_log: Callable[[str], None]) -> None:
    """Download URL → dest, logging progress every ~1 MB."""
    on_log(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        next_log_threshold = 1024 * 1024  # log every 1 MB
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_log_threshold:
                    if total:
                        pct = (downloaded / total) * 100
                        on_log(f"  {downloaded // (1024*1024)} / {total // (1024*1024)} MB  ({pct:.1f}%)")
                    else:
                        on_log(f"  {downloaded // (1024*1024)} MB")
                    next_log_threshold += 1024 * 1024


def _fetch_expected_sha256(zip_filename: str, on_log: Callable[[str], None]) -> str:
    """Pull SHASUMS256.txt from nodejs.org, find the row for our zip."""
    sha_url = f"{_NODE_DIST_BASE}/v{_NODE_VERSION}/SHASUMS256.txt"
    on_log(f"Fetching {sha_url}")
    with urllib.request.urlopen(sha_url, timeout=30) as resp:
        body = resp.read().decode("utf-8", "replace")
    for line in body.splitlines():
        # Format: "<sha>  <filename>"
        parts = line.split()
        if len(parts) == 2 and parts[1] == zip_filename:
            return parts[0]
    raise RuntimeError(f"SHA256 entry for {zip_filename} not found in SHASUMS256.txt")


def _verify_sha256(path: str, expected: str, on_log: Callable[[str], None]) -> None:
    on_log("Verifying SHA256...")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(f"SHA256 mismatch: expected {expected}, got {actual}")
    on_log("  ✓ SHA256 ok")


def _extract_zip(zip_path: str, dest_parent: str, on_log: Callable[[str], None]) -> str:
    """Extract zip into dest_parent, return path to the extracted top-level dir."""
    on_log(f"Extracting to {dest_parent}")
    with zipfile.ZipFile(zip_path) as zf:
        # The zip wraps everything in a single top-level dir like 'node-v22.11.0-win-x64/'
        top_dirs = {n.split("/", 1)[0] for n in zf.namelist() if "/" in n}
        if len(top_dirs) != 1:
            raise RuntimeError(f"Unexpected zip layout, top-level dirs: {top_dirs}")
        zf.extractall(dest_parent)
    return os.path.join(dest_parent, next(iter(top_dirs)))


def install_managed_node(on_log: Callable[[str], None]) -> None:
    """Download and install Node {_NODE_VERSION} into user_data/runtimes/node/.

    Idempotent: if a managed install already exists, it's removed first so
    this can also act as a re-install. Failures clean up the tmp working dir.
    """
    runtimes = _runtimes_root()
    dst_dir = _managed_node_dir()
    zip_name = f"{_NODE_ZIP_BASENAME}.zip"
    zip_url = f"{_NODE_DIST_BASE}/v{_NODE_VERSION}/{zip_name}"

    on_log(f"Installing Node.js v{_NODE_VERSION} (managed)")

    # Use a tmp dir under runtimes/ so the rename at the end stays on-fs.
    tmp_root = tempfile.mkdtemp(prefix="node-install-", dir=runtimes)
    try:
        zip_path = os.path.join(tmp_root, zip_name)
        _stream_download(zip_url, zip_path, on_log)

        expected_sha = _fetch_expected_sha256(zip_name, on_log)
        _verify_sha256(zip_path, expected_sha, on_log)

        extracted_top = _extract_zip(zip_path, tmp_root, on_log)
        if not os.path.isfile(os.path.join(extracted_top, "node.exe")):
            raise RuntimeError(f"node.exe not found in extracted dir {extracted_top}")

        # Atomic-ish swap: remove old, move new into place.
        if os.path.isdir(dst_dir):
            on_log(f"Removing previous managed install at {dst_dir}")
            shutil.rmtree(dst_dir)
        shutil.move(extracted_top, dst_dir)
        on_log(f"✓ Installed to {dst_dir}")
    finally:
        # Best-effort cleanup of the tmp working dir (may already be empty
        # after move).
        try:
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass


def remove_managed_node() -> None:
    """Delete the managed Node install. Idempotent."""
    dst_dir = _managed_node_dir()
    if os.path.isdir(dst_dir):
        shutil.rmtree(dst_dir)
