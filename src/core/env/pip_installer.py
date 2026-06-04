"""pip install / upgrade helpers for env components.

Routes through core.runtime_extras so installs work in a frozen build too: a
plain `sys.executable -m pip` there re-spawns the frozen sidecar and hangs
(packaging-design.md §5.3). The package lands in user_data/runtimes/py-extra and
shadows any copy frozen into the base bundle — e.g. lets the user upgrade a stale
bundled yt-dlp to keep up with YouTube changes.
"""

from __future__ import annotations

from typing import Callable

from core import runtime_extras


def install_pip(package: str):
    """Return an install function that installs/upgrades `package` into py-extra."""
    def _do(on_log: Callable[[str], None]) -> None:
        rc = runtime_extras.install([package], on_line=on_log)
        if rc != 0:
            raise RuntimeError(f"pip exited with code {rc}")
    return _do


# upgrade is the same operation: runtime_extras.install always passes --upgrade,
# which is the right semantics for these tool packages (track latest).
upgrade_pip = install_pip
