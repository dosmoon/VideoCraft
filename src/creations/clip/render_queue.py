"""Off-thread render queue for the clip workbench.

Owns the threading + Tk-thread marshalling for a batch of clip renders.
Callbacks fire on the Tk thread; the worker thread only touches the
filesystem (stale-file cleanup) and the cancel flag.

The workbench keeps Tk widget state (progress bars, treeview, status
labels); this module is concerned solely with running renders one at a
time, cancelling cleanly, and surfacing per-clip success / failure.

The queue is one-shot: instantiate per render batch, call start(jobs),
let on_all_done fire, then drop it. cancel() requests an early exit
between jobs and after the current render's next progress tick.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from core.composition import CompositionRequest, render_composition


@dataclass
class RenderJob:
    """One unit of work for the render queue."""
    out_idx: int
    src_idx: int
    request: CompositionRequest


class RenderQueue:
    """Off-thread worker for sequential clip renders.

    Parameters
    ----------
    master :
        A Tk widget — the queue uses master.after(0, ...) to marshal
        callbacks onto the main thread.
    on_progress :
        Called as `(done, total, out_idx, pct)` whenever progress
        advances. `done` is the number of jobs FINISHED (not counting
        the in-flight one). Fired on the Tk thread.
    on_succeeded :
        Called as `(job, render_result)` after a job's
        render_composition returned. Workbench writes sidecars,
        updates bookkeeping. Fired on the Tk thread.
    on_failed :
        Called as `(job, error_msg)` when a job raised. Fired on the
        Tk thread.
    on_all_done :
        Called as `(last_error_msg_or_None)` after the loop exits
        (normal completion or cancel). Fired on the Tk thread.
    cleanup_stale_fn :
        Called as `(out_idx, new_basename)` BEFORE each job's render,
        on the WORKER thread. Workbench removes any prior paired files
        for the same `out_idx` whose basename differs from
        `new_basename` (handles hook edits that change filename).
    """

    def __init__(
        self,
        master,
        *,
        on_progress: Callable[[int, int, int, int], None],
        on_succeeded: Callable[[RenderJob, Any], None],
        on_failed: Callable[[RenderJob, str], None],
        on_all_done: Callable[[Optional[str]], None],
        cleanup_stale_fn: Callable[[int, str], None],
        render_fn: Callable[..., Any] = render_composition,
    ) -> None:
        self._master = master
        self._on_progress = on_progress
        self._on_succeeded = on_succeeded
        self._on_failed = on_failed
        self._on_all_done = on_all_done
        self._cleanup_stale_fn = cleanup_stale_fn
        self._render_fn = render_fn
        self._cancel_flag = False
        self._thread: Optional[threading.Thread] = None

    @property
    def is_busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def is_cancelled(self) -> bool:
        """True once cancel() has been called for this batch."""
        return self._cancel_flag

    def start(self, jobs: list[RenderJob]) -> None:
        """Spawn the worker thread. No-op if already running."""
        if self.is_busy:
            return
        self._cancel_flag = False
        self._thread = threading.Thread(
            target=self._run, args=(list(jobs),), daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Signal the worker to stop before its next job and to abort
        the in-flight render at its next cancel_check tick."""
        if self.is_busy:
            self._cancel_flag = True

    # ── internals ─────────────────────────────────────────────────────────

    def _run(self, jobs: list[RenderJob]) -> None:
        total = len(jobs)
        last_error: Optional[str] = None
        for done, job in enumerate(jobs, 1):
            if self._cancel_flag:
                break
            self._post(self._on_progress, done - 1, total, job.out_idx, 0)

            def _on_pct(_stage, pct, oi=job.out_idx, d=done, t=total):
                self._post(self._on_progress, d - 1, t, oi, pct)

            try:
                new_base = os.path.basename(
                    os.path.splitext(job.request.output_path)[0])
                self._cleanup_stale_fn(job.out_idx, new_base)
                result = self._render_fn(
                    job.request, on_progress=_on_pct,
                    cancel_check=lambda: self._cancel_flag)
                self._post(self._on_succeeded, job, result)
            except InterruptedError:
                break
            except Exception as e:                              # noqa: BLE001
                last_error = f"#{job.out_idx}: {e}"
                self._post(self._on_failed, job, str(e))

        self._post(self._on_all_done, last_error)

    def _post(self, fn: Callable, *args) -> None:
        """Marshal `fn(*args)` onto the Tk thread."""
        self._master.after(0, lambda: fn(*args))
