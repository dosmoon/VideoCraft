"""Install / uninstall the CUDA runtime wheels for embedded ASR/LLM.

faster-whisper (CTranslate2 CUDA build) and llama-cpp-python (CUDA build)
both look for CUDA + cuDNN DLLs at load time.  We get those DLLs from
the `nvidia-*-cu12` pip packages — see core/gpu.py for the runtime path
setup.  This module is the install side: a single entry point for the
Model Manager UI to download those wheels into the same site-packages
as the running interpreter (portable Python or dev venv alike).

~1.5 GB total on disk; opt-in.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable

# Packages pip will resolve when CUDA is enabled.  The first four are the
# top-level deps faster-whisper / llama-cpp-python need; pip will pull in
# nvidia-cuda-nvrtc-cu12 and nvidia-nvjitlink-cu12 as transitive deps.
_TOP_LEVEL = [
    "nvidia-cublas-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cufft-cu12",
]

# All packages we remove on uninstall — includes the transitives so the
# user gets a clean rollback (pip won't auto-remove deps).
_ALL_PACKAGES = _TOP_LEVEL + [
    "nvidia-cuda-nvrtc-cu12",
    "nvidia-nvjitlink-cu12",
]


def is_installed() -> bool:
    """True when the four top-level CUDA wheels are present in site-packages.

    Mirrors core.gpu.ensure_cuda_dlls()'s detection: presence of
    `site-packages/nvidia/<lib>/bin/` is what the providers actually rely on.
    """
    nvidia_root = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    if not os.path.isdir(nvidia_root):
        return False
    # All four top-level packages drop their own subdir under nvidia/.
    expected = {"cublas", "cuda_runtime", "cudnn", "cufft"}
    present = set(os.listdir(nvidia_root))
    return expected.issubset(present)


def install(on_line: Callable[[str], None] | None = None,
            cancel_token=None) -> int:
    """Run `pip install` for the CUDA runtime wheels into the current interpreter.

    Args:
        on_line: called with each line of pip's combined stdout/stderr.
        cancel_token: object with a `cancelled` attribute; checked between
            line reads. When truthy, the subprocess is terminated.

    Returns:
        pip's exit code (0 on success).
    """
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        *_TOP_LEVEL,
    ]
    return _stream(cmd, on_line, cancel_token)


def uninstall(on_line: Callable[[str], None] | None = None,
              cancel_token=None) -> int:
    """Run `pip uninstall -y` for the CUDA runtime wheels.

    Includes transitives so the rollback is clean (otherwise pip leaves
    nvidia-cuda-nvrtc-cu12 / nvidia-nvjitlink-cu12 behind).
    """
    cmd = [
        sys.executable, "-m", "pip", "uninstall",
        "--disable-pip-version-check",
        "-y",
        *_ALL_PACKAGES,
    ]
    return _stream(cmd, on_line, cancel_token)


def _stream(cmd: list[str], on_line, cancel_token) -> int:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        # Suppress the console window when launched from a Tk app on Windows.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_line is not None:
                try:
                    on_line(line.rstrip())
                except Exception:
                    pass
            if cancel_token is not None and getattr(cancel_token, "cancelled", False):
                proc.terminate()
                break
        return proc.wait()
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


def run_in_background(action: str,
                      on_line: Callable[[str], None],
                      on_done: Callable[[int], None]) -> threading.Thread:
    """Run install/uninstall on a worker thread.  Returns the thread."""
    assert action in ("install", "uninstall")
    fn = install if action == "install" else uninstall

    def _worker():
        try:
            rc = fn(on_line=on_line)
        except Exception as e:  # noqa: BLE001
            on_line(f"[error] {e!r}")
            rc = -1
        try:
            on_done(rc)
        except Exception:
            pass

    t = threading.Thread(target=_worker,
                         name=f"CudaRuntime-{action}",
                         daemon=True)
    t.start()
    return t
