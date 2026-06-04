"""Install / uninstall the CUDA runtime wheels for embedded ASR/LLM.

faster-whisper (CTranslate2 CUDA build) and llama-cpp-python (CUDA build)
both look for CUDA + cuDNN DLLs at load time.  We get those DLLs from
the `nvidia-*-cu12` pip packages — see core/gpu.py for the runtime path
setup.  This module is the install side: a single entry point for the
Model Manager UI to download those wheels.

Install target is `user_data/runtimes/py-extra` (core.runtime_extras), NOT the
interpreter's own site-packages — the frozen sidecar's site-packages are sealed,
and `sys.executable -m pip` is the install-hang trap there (packaging-design.md
§5.3). The same py-extra path is used in dev for parity. gpu.py scans py-extra
for the nvidia/ DLL roots so the providers find them at load time.

~1.5 GB total on disk; opt-in.
"""

from __future__ import annotations

import threading
from typing import Callable

from core import runtime_extras

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
    """True when the four top-level CUDA wheels are present in py-extra.

    Mirrors core.gpu.ensure_cuda_dlls()'s detection: presence of
    `<root>/nvidia/<lib>/bin/` is what the providers actually rely on. Checks
    every candidate root gpu.py scans (py-extra + the dev venv site-packages).
    """
    import os
    from core import gpu

    # All four top-level packages drop their own subdir under nvidia/.
    expected = {"cublas", "cuda_runtime", "cudnn", "cufft"}
    for nvidia_root in gpu._nvidia_roots():
        present = set(os.listdir(nvidia_root))
        if expected.issubset(present):
            return True
    return False


def install(on_line: Callable[[str], None] | None = None,
            cancel_token=None) -> int:
    """Install the CUDA runtime wheels into user_data/runtimes/py-extra.

    Args:
        on_line: called with each line of pip's combined stdout/stderr.
        cancel_token: object with a `cancelled` attribute; checked between
            line reads. When truthy, the subprocess is terminated.

    Returns:
        pip's exit code (0 on success).
    """
    return runtime_extras.install(_TOP_LEVEL, on_line=on_line, cancel_token=cancel_token)


def uninstall(on_line: Callable[[str], None] | None = None,
              cancel_token=None) -> int:
    """Remove the CUDA runtime wheels from py-extra.

    Includes transitives so the rollback is clean (pip-style uninstall leaves
    nvidia-cuda-nvrtc-cu12 / nvidia-nvjitlink-cu12 behind otherwise).
    """
    return runtime_extras.uninstall(_ALL_PACKAGES, on_line=on_line)


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
