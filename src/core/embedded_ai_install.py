"""Install / uninstall the embedded-AI runtime (opt-in).

The embedded-AI providers — faster-whisper (CTranslate2 ASR) and llama-cpp-python
(local GGUF LLM) — are heavy native deps the base sidecar deliberately does NOT
freeze (requirements-base.txt excludes them). The user opts in from the Model
Manager; we install them at runtime into user_data/runtimes/py-extra via
core.runtime_extras (the only writable, frozen-safe install site — see
packaging-design.md §5.3). gpu_install adds the optional CUDA wheels on top.

CPU profile only here (mirrors requirements.txt's default profile). The GPU path
is the separate nvidia-*-cu12 wheels installed by core.gpu_install; CTranslate2
auto-selects fp16/CUDA at load time once those DLLs are present, and the CPU
llama-cpp-python wheel is replaced by the CUDA one when the user enables GPU.
"""

from __future__ import annotations

import threading
from typing import Callable

from core import runtime_extras

# Pins MUST stay in lockstep with requirements.txt (the default CPU profile).
_FASTER_WHISPER = "faster-whisper==1.2.1"
_LLAMA_CPP = "llama-cpp-python==0.3.22"

_PACKAGES = [_FASTER_WHISPER, _LLAMA_CPP]

# Top-level project names (for the py-extra uninstall, which removes by dist-info).
_DETECT = ["faster-whisper", "llama-cpp-python"]

# Import names of the two runtimes — what is_installed() actually probes.
_MODULES = ["faster_whisper", "llama_cpp"]

# llama-cpp-python wheels are published outside PyPI — building from source on
# Windows breaks (vendored llama.cpp paths exceed MAX_PATH). The CPU wheel index:
_LLAMA_CPU_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"


def is_installed() -> bool:
    """True when both embedded-AI runtimes are importable in this interpreter.

    Importability — NOT a py-extra dist-info check — is the right question, and
    mirrors gpu_install.is_installed() (which accepts either site):
      - dev: faster-whisper / llama-cpp live in the venv (full requirements.txt)
        → importable → "installed", so the UI never offers a redundant download.
      - packaged: the base freeze EXCLUDES them (requirements-base.txt), so they
        become importable ONLY after the opt-in install into py-extra (on sys.path
        via runtime_extras.ensure_on_sys_path). The frozen interpreter has no venv,
        so there is no false positive to worry about.
    """
    import importlib.util

    runtime_extras.ensure_on_sys_path()  # so a py-extra install is on the path
    return all(importlib.util.find_spec(m) is not None for m in _MODULES)


def install(on_line: Callable[[str], None] | None = None,
            cancel_token=None) -> int:
    """Install faster-whisper + llama-cpp-python (CPU) into py-extra.

    Args:
        on_line: called with each line of pip's combined stdout/stderr.
        cancel_token: object with a `cancelled` attribute; checked between
            line reads. When truthy, the subprocess is terminated.

    Returns:
        pip's exit code (0 on success).
    """
    return runtime_extras.install(
        _PACKAGES,
        on_line=on_line,
        cancel_token=cancel_token,
        # llama-cpp-python's CPU wheel lives on its own index; faster-whisper and
        # all transitives resolve from PyPI as usual.
        extra_args=["--extra-index-url", _LLAMA_CPU_INDEX],
    )


def uninstall(on_line: Callable[[str], None] | None = None,
              cancel_token=None) -> int:
    """Remove the embedded-AI runtimes from py-extra.

    Only the two top-level packages are removed; shared transitives (numpy,
    huggingface-hub, …) are left in place — they're cheap and may back other
    extras. A clean-slate user can delete user_data/runtimes/py-extra wholesale.
    """
    return runtime_extras.uninstall(_DETECT, on_line=on_line)


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
                         name=f"EmbeddedAI-{action}",
                         daemon=True)
    t.start()
    return t
