"""Embedded-AI runtime RPC (P3 §5.3) — opt-in faster-whisper / llama-cpp install.

Wraps core.embedded_ai_install: the heavy native ASR/LLM runtimes the base
sidecar does not freeze, installed on demand into user_data/runtimes/py-extra.
install/uninstall shell out (pip), so both are jobs and stream pip output
line-by-line via `progress.embedded_ai.<action>` (field `line`). Mirrors gpu.py.
"""

from __future__ import annotations

from typing import Any

from ..registry import Context, rpc_method


def _status() -> dict[str, Any]:
    from core import embedded_ai_install

    return {"installed": embedded_ai_install.is_installed()}


class _JobCancel:
    """Adapts a core_rpc Job's cancellation to the `.cancelled` token the
    installer polls between output lines."""

    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def cancelled(self) -> bool:
        return bool(self._job.cancelled)


@rpc_method("embedded_ai.status")
def status(ctx: Context) -> dict[str, Any]:
    """Report whether the embedded-AI runtime is installed. Terminal result:
    {installed}."""

    def work(_job: Any) -> dict[str, Any]:
        return _status()

    return {"job_id": ctx.jobs.start("embedded_ai.status", work)}


def _run(ctx: Context, action: str) -> dict[str, Any]:
    def work(job: Any) -> dict[str, Any]:
        from core import embedded_ai_install

        fn = (embedded_ai_install.install if action == "install"
              else embedded_ai_install.uninstall)
        rc = fn(on_line=lambda line: job.progress(line=line), cancel_token=_JobCancel(job))
        if rc != 0 and not job.cancelled:
            raise RuntimeError(f"{action} failed (pip exit {rc})")
        return _status()

    return {"job_id": ctx.jobs.start(f"embedded_ai.{action}", work)}


@rpc_method("embedded_ai.install")
def install(ctx: Context) -> dict[str, Any]:
    """Install faster-whisper + llama-cpp-python (CPU) into py-extra (job —
    streams pip log, ~hundreds of MB)."""
    return _run(ctx, "install")


@rpc_method("embedded_ai.uninstall")
def uninstall(ctx: Context) -> dict[str, Any]:
    """Remove the embedded-AI runtime from py-extra (job — streams log)."""
    return _run(ctx, "uninstall")
