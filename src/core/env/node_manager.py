"""Managed Node.js install — download portable Node into user_data/runtimes/.

The install function is wired up in components.py for the 'node' component.
yt-dlp picks up the resolved path via detectors.detect_node() in this commit;
the actual download implementation lands in commit 3 of the rollout.
"""

from __future__ import annotations

import os
from typing import Callable

from core import user_data


# Pinned Node LTS for managed install. Bump deliberately; never auto-upgrade.
_NODE_VERSION = "22.11.0"
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


def install_managed_node(on_log: Callable[[str], None]) -> None:
    """Download and install Node {_NODE_VERSION} into user_data/runtimes/node/.

    Implementation lands in commit 3 of the rollout. Currently a stub that
    surfaces a clear NotImplementedError so the component registry can still
    be loaded in commit 2 without crashing.
    """
    raise NotImplementedError(
        "Managed Node install lands in the Node download commit "
        "(commit 3 of the env-dashboard rollout)."
    )
