"""GPU runtime detection + DLL path setup for embedded-AI providers.

faster-whisper (CTranslate2 CUDA build) and llama-cpp-python (CUDA build)
both expect `cublasLt64_12.dll`, `cudnn64_9.dll`, etc. on the OS DLL
search path at load time. We get those DLLs from the `nvidia-*-cu12` pip
packages, but pip drops them in `site-packages/nvidia/<lib>/bin/` which
isn't on PATH by default.

This module:
  - Adds those bin dirs to PATH **before** any ctranslate2 / llama_cpp
    import so the C++ side's LoadLibrary calls resolve cleanly.
  - Probes whether the CUDA runtime DLLs are present (the user may have
    only the CPU wheels installed).
  - Exposes `cuda_available()` so providers can flip their default
    config (faster_whisper.compute_type, llama_cpp.n_gpu_layers) accordingly.

Idempotent — `ensure_cuda_dlls()` is safe to call from multiple modules.
First call wins; subsequent calls are no-ops.
"""

from __future__ import annotations

import glob
import os
import sys
import subprocess

_DLL_DIRS_ADDED: bool = False
_CUDA_PROBE_RESULT: bool | None = None


def _nvidia_roots() -> list[str]:
    """Candidate ``nvidia/`` namespace dirs the CUDA wheels may live in.

    Two sites, in import-priority order:
      1. ``user_data/runtimes/py-extra/nvidia`` — where the runtime installer
         (core.gpu_install) puts the wheels under freeze, since the frozen
         sidecar's own site-packages are sealed (packaging-design.md §5.3).
      2. ``<sys.prefix>/Lib/site-packages/nvidia`` — the dev venv install site.
    Only dirs that actually exist are returned.
    """
    roots: list[str] = []
    try:
        from core.runtime_extras import py_extra_dir

        roots.append(os.path.join(py_extra_dir(), "nvidia"))
    except Exception:  # noqa: BLE001 — never let path resolution break detection
        pass
    roots.append(os.path.join(sys.prefix, "Lib", "site-packages", "nvidia"))
    return [r for r in roots if os.path.isdir(r)]


def _nvidia_bin_dirs() -> list[str]:
    """All ``nvidia/<lib>/bin`` dirs across the candidate roots, sorted."""
    bin_dirs: list[str] = []
    for root in _nvidia_roots():
        bin_dirs.extend(glob.glob(os.path.join(root, "*", "bin")))
    return sorted(bin_dirs)


def ensure_cuda_dlls() -> None:
    """Prepend NVIDIA pip-package bin dirs to PATH (Windows DLL search).

    No-op on non-Windows or if the nvidia/ namespace package isn't present
    (CPU-only install). Always called before importing CUDA-capable
    libraries from this codebase.
    """
    global _DLL_DIRS_ADDED
    if _DLL_DIRS_ADDED:
        return
    _DLL_DIRS_ADDED = True

    if sys.platform != "win32":
        return  # On Linux the wheels rely on rpath / LD_LIBRARY_PATH conventions
    bin_dirs = _nvidia_bin_dirs()
    if not bin_dirs:
        return
    # Prepend so we win over any older system-wide CUDA install on PATH.
    os.environ["PATH"] = os.pathsep.join(
        bin_dirs + [os.environ.get("PATH", "")]
    )
    # `add_dll_directory` improves resolution for python-side ctypes too,
    # belt-and-suspenders with the PATH change.
    for d in bin_dirs:
        try:
            os.add_dll_directory(d)
        except (FileNotFoundError, OSError):
            pass


def cuda_available() -> bool:
    """True when CUDA runtime DLLs for our embedded providers are present.

    Detection is metadata-based — we don't import any CUDA-using library
    here (would load DLLs into the process and risk init order conflicts
    with the providers themselves). Two checks:
        1. nvidia/<lib>/bin dirs exist (cublas + cudnn pip packages)
        2. nvidia-smi reports a usable GPU + driver

    Either alone gives a false positive (driver without runtime, or
    runtime wheels installed on a CPU-only host).
    """
    global _CUDA_PROBE_RESULT
    if _CUDA_PROBE_RESULT is not None:
        return _CUDA_PROBE_RESULT
    ensure_cuda_dlls()

    has_runtime = sys.platform == "win32" and bool(_nvidia_bin_dirs())

    has_driver = False
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=4.0,
        )
        has_driver = (r.returncode == 0 and bool(r.stdout.strip()))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    _CUDA_PROBE_RESULT = bool(has_runtime and has_driver)
    return _CUDA_PROBE_RESULT


def cuda_status() -> dict:
    """Diagnostic snapshot for the AI Console / Model Manager UI.

    Returns:
        {
          "available":   bool,
          "device_name": str (nvidia-smi readout, "" if unknown),
          "driver":      str,
          "vram_mb":     int,
          "wheel":       str  (faster-whisper version),
          "reason":      str  (short one-liner shown to user),
        }
    """
    ensure_cuda_dlls()
    out: dict = {
        "available": cuda_available(),
        "device_name": "",
        "driver": "",
        "vram_mb": 0,
        "wheel": "",
        "reason": "",
    }
    try:
        from importlib.metadata import version
        out["wheel"] = version("faster-whisper")
    except Exception:
        pass

    # nvidia-smi for human-readable hardware info; failure non-fatal.
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4.0,
        )
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                out["device_name"] = parts[0]
                out["driver"] = parts[1]
                try:
                    out["vram_mb"] = int(parts[2])
                except ValueError:
                    pass
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    if out["available"]:
        if out["device_name"]:
            out["reason"] = (
                f"{out['device_name']} ({out['vram_mb']} MiB), "
                f"driver {out['driver']}, faster-whisper {out['wheel']}"
            )
        else:
            out["reason"] = f"faster-whisper {out['wheel']} loaded"
    else:
        out["reason"] = (
            "CUDA runtime DLLs (nvidia-cublas-cu12 / nvidia-cudnn-cu12) "
            "or NVIDIA driver missing."
        )
    return out
