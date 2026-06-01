"""Local model manager RPC (P1-d) — catalog + download/install/remove.

Bridges the existing core.models stack (catalog + range-resume downloader +
DownloadManager) onto the RPC channel so the Electron shell can install the
embedded-AI models (faster-whisper / Qwen3 GGUF) without the Tk app. The
DownloadManager runs its own worker thread and fires on_event(jobs) on any
state change; we subscribe once and forward each update as an `event.models`
notification (the renderer re-renders the jobs + re-scans the catalog).

Installed-state is a cheap disk check against the catalog's declared filenames
(no network); downloading resolves exact sizes from HuggingFace itself.

Deferred (still Tk-only): CUDA-wheel GPU dialog, change-models-dir, tier-batch
download, the environment dashboard.
"""

from __future__ import annotations

import os
from typing import Any

from ..registry import Context, rpc_method

# Process-wide guard so we attach the DownloadManager→RPC bridge exactly once.
_bridge = {"attached": False}


def _serialize_jobs(jobs: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "job_id": j.job_id,
            "model_id": j.model_id,
            "state": j.state,
            "bytes_done": j.bytes_done,
            "bytes_total": j.bytes_total,
            "fraction": j.fraction,
            "bytes_per_sec": j.bytes_per_sec,
            "eta_sec": j.eta_sec,
            "current_file": j.current_file,
            "error": j.error,
        }
        for j in jobs
    ]


def _ensure_bridge(ctx: Context) -> None:
    """Forward DownloadManager state changes to `event.models` (once). The
    callback fires on the manager's worker thread; ctx.emit is the same
    thread-safe queue the job path uses."""
    if _bridge["attached"]:
        return
    from core.models.manager import manager

    emit = ctx.emit

    def on_change(jobs: list[Any]) -> None:
        emit("event.models", {"jobs": _serialize_jobs(jobs)})

    manager.on_event(on_change)
    _bridge["attached"] = True


@rpc_method("models.catalog")
def catalog(ctx: Context) -> list[dict[str, Any]]:
    """The downloadable-model catalog with cheap disk-only installed state
    (no network — counts how many of each spec's declared files are present)."""
    from core.models.catalog import CATALOG

    out: list[dict[str, Any]] = []
    for mid, spec in CATALOG.items():
        target = spec.target_dir()
        present = sum(
            1 for fn in spec.filenames if os.path.exists(os.path.join(target, os.path.basename(fn)))
        )
        total = len(spec.filenames)
        out.append(
            {
                "id": mid,
                "name": spec.display_name,
                "capability": spec.capability,
                "tier": spec.tier,
                "recommended_for": spec.recommended_for,
                "description": spec.description,
                "dir": target,
                "installed": total > 0 and present == total,
                "present": present,
                "total": total,
            }
        )
    return out


@rpc_method("models.jobs")
def jobs(ctx: Context) -> list[dict[str, Any]]:
    """Snapshot of current download jobs (the renderer also gets live pushes via
    `event.models`)."""
    from core.models.manager import manager

    return _serialize_jobs(manager.list_jobs())


@rpc_method("models.download")
def download(ctx: Context, model_id: str) -> dict[str, Any]:
    """Enqueue a model download. Progress arrives via `event.models`."""
    from core.models.manager import manager

    _ensure_bridge(ctx)
    return {"job_id": manager.enqueue(model_id)}


@rpc_method("models.cancel")
def cancel(ctx: Context, job_id: str) -> dict[str, Any]:
    """Cancel a queued/running download job."""
    from core.models.manager import manager

    manager.cancel(job_id)
    return {"ok": True}


@rpc_method("models.remove")
def remove(ctx: Context, model_id: str) -> dict[str, Any]:
    """Delete an installed model's files from disk. Returns bytes freed."""
    from core.models import registry

    return {"freed": registry.remove(model_id)}
