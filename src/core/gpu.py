"""GPU runtime detection + DLL path setup for embedded-AI providers.

Sherpa-onnx (CUDA build) and llama-cpp-python (CUDA build) both expect
`cublasLt64_12.dll`, `cudnn64_9.dll`, etc. on the OS DLL search path at
load time. We get those DLLs from the `nvidia-*-cu12` pip packages
(installed alongside the CUDA wheels), but pip drops them in
`site-packages/nvidia/<lib>/bin/` which isn't on PATH by default.

This module:
  - Adds those bin dirs to PATH **before** any sherpa_onnx / llama_cpp
    import so the C++ side's LoadLibrary calls resolve cleanly.
  - Probes whether a CUDA-capable build is actually present (the user
    may have only the CPU wheels installed).
  - Exposes `cuda_available()` so providers can flip their default
    config (sherpa.provider, llama_cpp.n_gpu_layers) accordingly.

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
    nvidia_root = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    if not os.path.isdir(nvidia_root):
        return
    bin_dirs = sorted(glob.glob(os.path.join(nvidia_root, "*", "bin")))
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
    """True when CUDA-capable wheels for our embedded providers are installed.

    Detection is purely metadata-based — we DO NOT import onnxruntime here
    because doing so loads a separate copy of the CUDA DLLs into the
    process and conflicts with sherpa-onnx's bundled onnxruntime when it
    later tries to load its own (Error 1114: DLL_INIT_FAILED). Two checks:
        1. nvidia/<lib>/bin dirs exist (the runtime DLLs are pip-installed)
        2. sherpa-onnx wheel was built with CUDA (version string ends in +cuda...)

    Both conditions are necessary; either alone gives a false positive.
    """
    global _CUDA_PROBE_RESULT
    if _CUDA_PROBE_RESULT is not None:
        return _CUDA_PROBE_RESULT
    ensure_cuda_dlls()

    # 1. NVIDIA runtime DLLs present
    nvidia_root = os.path.join(sys.prefix, "Lib", "site-packages", "nvidia")
    has_runtime = (sys.platform == "win32" and os.path.isdir(nvidia_root)
                   and bool(glob.glob(os.path.join(nvidia_root, "*", "bin"))))

    # 2. sherpa-onnx wheel has CUDA build. We import the metadata only;
    # the heavy C++ side gets touched lazily by the providers themselves.
    has_cuda_wheel = False
    try:
        from importlib.metadata import version
        v = version("sherpa-onnx")
        has_cuda_wheel = "+cuda" in v
    except Exception:
        pass

    _CUDA_PROBE_RESULT = bool(has_runtime and has_cuda_wheel)
    return _CUDA_PROBE_RESULT


def cuda_status() -> dict:
    """Diagnostic snapshot for the AI Console / Model Manager UI.

    Returns:
        {
          "available":   bool,
          "device_name": str (nvidia-smi readout, "" if unknown),
          "driver":      str,
          "vram_mb":     int,
          "wheel":       str  (sherpa-onnx version, e.g. "1.13.0+cuda12.cudnn9"),
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
        out["wheel"] = version("sherpa-onnx")
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
                f"driver {out['driver']}, wheel {out['wheel']}"
            )
        else:
            out["reason"] = f"CUDA wheel {out['wheel']} loaded"
    else:
        if not out["wheel"] or "+cuda" not in out["wheel"]:
            out["reason"] = (
                f"CPU-only sherpa wheel installed ({out['wheel']}). "
                "Install +cuda wheel to enable GPU."
            )
        else:
            out["reason"] = "CUDA runtime DLLs (nvidia-* pip packages) missing."
    return out
