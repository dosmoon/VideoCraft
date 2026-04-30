"""pip install / upgrade helpers with streaming log callbacks."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable


def _run_pip(args: list[str], on_log: Callable[[str], None]) -> None:
    """Run pip with stdout streamed line-by-line to on_log. Raises on failure."""
    cmd = [sys.executable, "-m", "pip"] + args + [
        "--no-warn-script-location",
        "--disable-pip-version-check",
    ]
    on_log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for line in proc.stdout:
        on_log(line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"pip exited with code {proc.returncode}")


def install_pip(package: str):
    """Return an install function that runs `pip install <package>`."""
    def _do(on_log: Callable[[str], None]) -> None:
        _run_pip(["install", package], on_log)
    return _do


def upgrade_pip(package: str):
    """Return an install function that runs `pip install --upgrade <package>`."""
    def _do(on_log: Callable[[str], None]) -> None:
        _run_pip(["install", "--upgrade", package], on_log)
    return _do
