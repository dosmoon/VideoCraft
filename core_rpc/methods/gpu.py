"""GPU runtime RPC (P1-d) — CUDA-wheel detect + install / uninstall.

Wraps core.gpu (nvidia-smi probe) + core.gpu_install (the nvidia-*-cu12 pip
wheels that give faster-whisper / llama_cpp their GPU path). Both shell out, so
all three methods are jobs. install/uninstall stream pip output line-by-line via
`progress.gpu.<action>` (field `line`) and reset the CUDA probe cache before the
terminal status, so the freshly-changed state is reported.
"""

from __future__ import annotations

from typing import Any

from ..registry import Context, rpc_method


def _status() -> dict[str, Any]:
    from core import gpu, gpu_install

    s = dict(gpu.cuda_status())
    s["installed"] = gpu_install.is_installed()
    return s


class _JobCancel:
    """Adapts a core_rpc Job's cancellation to the `.cancelled` token the pip
    installer polls between output lines."""

    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def cancelled(self) -> bool:
        return bool(self._job.cancelled)


@rpc_method("gpu.status")
def status(ctx: Context) -> dict[str, Any]:
    """Detect CUDA + GPU (job — nvidia-smi). Terminal result:
    {installed, available, device_name, driver, vram_mb, wheel, reason}."""

    def work(_job: Any) -> dict[str, Any]:
        return _status()

    return {"job_id": ctx.jobs.start("gpu.status", work)}


def _run_pip(ctx: Context, action: str) -> dict[str, Any]:
    def work(job: Any) -> dict[str, Any]:
        from core import gpu, gpu_install

        fn = gpu_install.install if action == "install" else gpu_install.uninstall
        rc = fn(on_line=lambda line: job.progress(line=line), cancel_token=_JobCancel(job))
        gpu._CUDA_PROBE_RESULT = None  # force a fresh probe now the wheels changed
        if rc != 0 and not job.cancelled:
            raise RuntimeError(f"{action} failed (pip exit {rc})")
        return _status()

    return {"job_id": ctx.jobs.start(f"gpu.{action}", work)}


@rpc_method("gpu.install")
def install(ctx: Context) -> dict[str, Any]:
    """Install the CUDA-runtime pip wheels (job — streams pip log, ~1.5 GB)."""
    return _run_pip(ctx, "install")


@rpc_method("gpu.uninstall")
def uninstall(ctx: Context) -> dict[str, Any]:
    """Remove the CUDA-runtime pip wheels (job — streams pip log)."""
    return _run_pip(ctx, "uninstall")
