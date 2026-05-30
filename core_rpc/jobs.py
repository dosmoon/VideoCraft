"""Long-task registry: job_id + progress/terminal notifications.

Long-running RPC methods (ASR, render, AI completion) must not block the
single stdio request loop. The pattern (migration doc §2.1):

  1. handler calls jobs.start(kind, work) → returns a job_id immediately
  2. `work(job)` runs on a worker thread; it calls job.progress(...) to push
     `progress.<kind>` notifications and may check job.cancelled
  3. on return / raise, a terminal `event.job` notification fires

The worker calls ctx.emit through the same off-thread writer queue the
sync responses use, so ordering with the channel is preserved.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# A notification sink: handler/job code calls it to push a server→client
# message (method, params). The transport binds the real queue-backed emit;
# tests bind a list collector. Defined here (not registry) to keep the
# registry→jobs import one-directional.
EmitFn = Callable[[str, Optional[dict[str, Any]]], None]


@dataclass
class Job:
    """A running long task. `progress`/cancellation are the worker's API."""

    id: str
    kind: str
    _emit: EmitFn
    _cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def progress(self, **fields: Any) -> None:
        """Push a `progress.<kind>` notification (e.g. done/total/pct)."""
        self._emit(f"progress.{self.kind}", {"job_id": self.id, **fields})


class JobRegistry:
    """Tracks live jobs and runs each on its own daemon thread."""

    def __init__(self, emit: EmitFn) -> None:
        self._emit = emit
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._seq = 0

    def _next_id(self) -> str:
        # Monotonic, process-local. Not random (Math.random()/uuid not needed —
        # ids only need to be unique within this sidecar's lifetime).
        with self._lock:
            self._seq += 1
            return f"job-{self._seq}"

    def start(self, kind: str, work: Callable[[Job], Any]) -> str:
        """Register a job, spawn its worker thread, return the job_id.

        `work(job)` runs off-thread. Its return value is attached to the
        terminal `event.job` notification as `result`; an exception becomes
        a `failed` status with the message.
        """
        job = Job(id=self._next_id(), kind=kind, _emit=self._emit)
        with self._lock:
            self._jobs[job.id] = job

        def runner() -> None:
            status = "succeeded"
            result: Any = None
            error: Optional[str] = None
            try:
                result = work(job)
                if job.cancelled:
                    status = "cancelled"
            except Exception as exc:  # noqa: BLE001 — surface to client, keep loop alive
                status = "failed"
                error = str(exc)
                # Tracebacks go to stderr (stdout is the JSON-RPC channel).
                traceback.print_exc()
            finally:
                with self._lock:
                    self._jobs.pop(job.id, None)
                payload: dict[str, Any] = {
                    "job_id": job.id,
                    "kind": kind,
                    "status": status,
                }
                if result is not None:
                    payload["result"] = result
                if error is not None:
                    payload["error"] = error
                self._emit("event.job", payload)

        t = threading.Thread(target=runner, name=f"rpc-{job.id}", daemon=True)
        t.start()
        return job.id

    def cancel(self, job_id: str) -> bool:
        """Signal cancellation. Returns False if the job is already gone."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel()
        return True

    def active_ids(self) -> list[str]:
        with self._lock:
            return list(self._jobs.keys())
