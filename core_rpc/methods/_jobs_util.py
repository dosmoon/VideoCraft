"""Bridges between core_rpc Jobs and the core layer's cancel/progress contracts.

Material long-tasks (source acquire, ASR, translate, analysis, AI fill) reuse the
existing headless pipelines, which expect:
  - a cancel token (core.source_acquire.CancelToken OR core.ai.cancellation.
    CancellationToken) they poll cooperatively, and
  - a progress callback receiving the pipeline's own ProgressInfo dataclass.

A running Job (core_rpc.jobs) exposes `job.cancelled` + `job.progress(**fields)`
instead. These adapters duck-type the two cancel surfaces over the Job, and map
each pipeline's ProgressInfo onto `job.progress(...)`. Cancellation stays
cooperative (the pipelines poll); HTTP-abort teardown is not wired here, so a
cancel waits for the current chunk/call to finish (faithful to current behavior).
"""

from __future__ import annotations

from typing import Any, Callable


class AcquireCancelBridge:
    """Adapts a Job to core.source_acquire.CancelToken's polled surface."""

    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def cancelled(self) -> bool:
        return self._job.cancelled

    def cancel(self) -> None:
        self._job.cancel()


class AiCancelBridge:
    """Adapts a Job to core.ai.cancellation.CancellationToken's polled surface.

    The AI facade + subtitle pipelines poll `.cancelled` / `.throw_if_cancelled`
    at chunk boundaries. `register_abort` (HTTP teardown) is a no-op in the job
    path — cancel latency is bounded by the current call, not the request."""

    def __init__(self, job: Any) -> None:
        self._job = job

    @property
    def cancelled(self) -> bool:
        return self._job.cancelled

    def cancel(self) -> None:
        self._job.cancel()

    def throw_if_cancelled(self, provider: str = "") -> None:
        if self._job.cancelled:
            from core.ai.errors import AIError, Kind

            raise AIError(Kind.CANCELLED, provider or "—", "Cancelled by user")

    def register_abort(self, cb: Callable[[], None]) -> None:  # noqa: ARG002
        # No HTTP-abort wiring in the jobs path; cancellation stays cooperative.
        return None


def acquire_progress_to_job(job: Any) -> Callable[[Any], None]:
    """Map core.source_acquire.ProgressInfo → job.progress(...)."""

    def cb(info: Any) -> None:
        job.progress(
            phase=info.phase,
            pct=info.percent,
            speed_bps=info.speed_bps,
            eta_sec=info.eta_sec,
            done=info.downloaded_bytes,
            total=info.total_bytes,
            status_text=info.status_text,
        )

    return cb


def pipeline_progress_to_job(job: Any) -> Callable[[Any], None]:
    """Map core.subtitle_pipeline.ProgressInfo → job.progress(...)."""

    def cb(info: Any) -> None:
        job.progress(phase=info.phase, pct=info.percent, status_text=info.status_text)

    return cb
