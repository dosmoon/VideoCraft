"""Background download manager: queue + source fallback + disk preflight.

Single worker thread processes a FIFO queue of DownloadJob. Each job
walks its file list; for each file it tries `sources` in order, calling
the resumable downloader. A job's progress is the sum across files.

UI consumers subscribe via `on_event(callback)` and receive snapshots
of all jobs whenever state changes (queued / running / done / failed /
cancelled) or when progress ticks. The callback runs on the worker
thread — UI code MUST marshal to the Tk main thread itself
(typical pattern: `tk_widget.after(0, lambda: ...)`).

There is exactly one manager instance per process — `core.models.manager`
exposes it as `manager`. Multiple windows can subscribe; jobs persist for
the process lifetime so a window reopened mid-download sees state intact.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from core.models.catalog import CATALOG, ModelSpec, get
from core.models.downloader import (
    DownloadProgress, CancelToken, DownloadError, download_file, verify_file,
)
from core.models.registry import disk_free_bytes


# Job states
JOB_QUEUED    = "queued"
JOB_RUNNING   = "running"
JOB_DONE      = "done"
JOB_FAILED    = "failed"
JOB_CANCELLED = "cancelled"


@dataclass
class DownloadJob:
    """One model-bundle download (one or more files, multi-source per file)."""
    job_id: str
    model_id: str
    spec: ModelSpec

    state: str = JOB_QUEUED
    bytes_done: int = 0
    bytes_total: int = 0
    bytes_per_sec: float = 0.0
    eta_sec: float | None = None
    current_file: str = ""        # relpath of file in flight
    current_url: str = ""         # source url currently attempted
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    cancel_token: CancelToken = field(default_factory=CancelToken)

    @property
    def fraction(self) -> float:
        if self.bytes_total <= 0:
            return 0.0
        return min(1.0, self.bytes_done / self.bytes_total)


EventCallback = Callable[[list["DownloadJob"]], None]


class DownloadManager:
    """Process-wide singleton. Thread-safe enqueue / cancel / subscribe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: list[DownloadJob] = []
        self._subscribers: list[EventCallback] = []
        self._worker: threading.Thread | None = None
        self._wake = threading.Event()
        self._next_id = 1

    # ── Public API ─────────────────────────────────────────────────────────

    def enqueue(self, model_id: str) -> str:
        """Add a download to the queue. Returns the job_id.

        If a non-finished job for the same model already exists, returns its
        id instead (no duplicates in flight). Existing files that already
        verify are not re-downloaded — the job lands in JOB_DONE immediately.
        """
        if model_id not in CATALOG:
            raise KeyError(f"Unknown model_id: {model_id!r}")
        with self._lock:
            for j in self._jobs:
                if j.model_id == model_id and j.state in (JOB_QUEUED, JOB_RUNNING):
                    return j.job_id
            spec = get(model_id)
            job = DownloadJob(
                job_id=f"job-{self._next_id}",
                model_id=model_id,
                spec=spec,
                bytes_total=spec.total_bytes,
            )
            self._next_id += 1
            self._jobs.append(job)
            self._ensure_worker()
        self._wake.set()
        self._notify()
        return job.job_id

    def enqueue_many(self, model_ids: list[str]) -> list[str]:
        return [self.enqueue(mid) for mid in model_ids]

    def cancel(self, job_id: str) -> None:
        with self._lock:
            for j in self._jobs:
                if j.job_id == job_id and j.state in (JOB_QUEUED, JOB_RUNNING):
                    j.cancel_token.cancel()
                    if j.state == JOB_QUEUED:
                        j.state = JOB_CANCELLED
                        j.finished_at = time.time()
        self._notify()

    def cancel_all(self) -> None:
        with self._lock:
            for j in self._jobs:
                if j.state in (JOB_QUEUED, JOB_RUNNING):
                    j.cancel_token.cancel()
                    if j.state == JOB_QUEUED:
                        j.state = JOB_CANCELLED
                        j.finished_at = time.time()
        self._notify()

    def clear_finished(self) -> None:
        """Drop done/failed/cancelled jobs from the visible queue."""
        with self._lock:
            self._jobs = [j for j in self._jobs
                          if j.state in (JOB_QUEUED, JOB_RUNNING)]
        self._notify()

    def list_jobs(self) -> list[DownloadJob]:
        with self._lock:
            return list(self._jobs)

    def on_event(self, callback: EventCallback) -> Callable[[], None]:
        """Subscribe to state-change snapshots. Returns an unsubscribe fn."""
        with self._lock:
            self._subscribers.append(callback)
        def _unsub() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)
        return _unsub

    @staticmethod
    def preflight_disk(model_ids: list[str]) -> tuple[bool, int, int, str]:
        """Check whether the target volume has room.

        Returns (ok, needed_bytes, free_bytes, target_dir). `ok` is True when
        free >= 1.2 × sum(spec.total_bytes), giving a headroom buffer. UI
        layer warns the user when False; doesn't refuse the enqueue, since a
        user might be deleting files in parallel.
        """
        from core.paths import models_dir
        needed = sum(get(mid).total_bytes for mid in model_ids if mid in CATALOG)
        target = models_dir()
        free = disk_free_bytes(target)
        ok = free >= int(needed * 1.2)
        return ok, needed, free, target

    # ── Worker ─────────────────────────────────────────────────────────────

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        t = threading.Thread(target=self._run, name="ModelDownloader",
                             daemon=True)
        self._worker = t
        t.start()

    def _next_job(self) -> DownloadJob | None:
        with self._lock:
            for j in self._jobs:
                if j.state == JOB_QUEUED:
                    return j
        return None

    def _run(self) -> None:
        while True:
            job = self._next_job()
            if job is None:
                # Idle — sleep until enqueue() pokes us, then re-check.
                self._wake.clear()
                # Cap idle wait so a forgotten event doesn't deadlock.
                self._wake.wait(timeout=30.0)
                # If still nothing after a long idle, exit and let the next
                # enqueue spin up a fresh worker.
                if self._next_job() is None:
                    with self._lock:
                        self._worker = None
                    return
                continue
            self._execute(job)

    def _execute(self, job: DownloadJob) -> None:
        with self._lock:
            job.state = JOB_RUNNING
            job.started_at = time.time()
        self._notify()

        try:
            for f in job.spec.files:
                if job.cancel_token.cancelled:
                    raise DownloadError("cancelled", "Cancelled by user")
                target = job.spec.file_path(f.relpath)

                # Skip files already complete (re-enqueue idempotency).
                if verify_file(target, expected_sha256=f.sha256,
                               expected_size=f.size_bytes):
                    with self._lock:
                        job.bytes_done += f.size_bytes
                        job.current_file = f.relpath
                    self._notify()
                    continue

                with self._lock:
                    job.current_file = f.relpath
                file_started_done = job.bytes_done

                last_err: DownloadError | None = None
                file_complete = False
                for url in f.sources:
                    if job.cancel_token.cancelled:
                        raise DownloadError("cancelled", "Cancelled by user")
                    with self._lock:
                        job.current_url = url
                    try:
                        download_file(
                            url, target,
                            expected_size=f.size_bytes,
                            expected_sha256=f.sha256,
                            on_progress=lambda p, fs=file_started_done, j=job:
                                self._on_file_progress(j, fs, p),
                            cancel_token=job.cancel_token,
                        )
                        file_complete = True
                        with self._lock:
                            # Reconcile to expected size: file is complete now.
                            job.bytes_done = fs_total = file_started_done + f.size_bytes
                            _ = fs_total
                        break  # next file
                    except DownloadError as e:
                        last_err = e
                        if e.kind == "cancelled":
                            raise
                        # Otherwise try the next source.
                        continue

                if not file_complete:
                    msg = (last_err.args[0] if last_err and last_err.args
                           else "all sources failed")
                    raise DownloadError(
                        last_err.kind if last_err else "network",
                        f"{f.relpath}: {msg}",
                    )

            with self._lock:
                job.state = JOB_DONE
                job.finished_at = time.time()
                job.bytes_done = job.bytes_total
                job.current_file = ""
                job.current_url = ""

        except DownloadError as e:
            with self._lock:
                if e.kind == "cancelled":
                    job.state = JOB_CANCELLED
                else:
                    job.state = JOB_FAILED
                    job.error = str(e)
                job.finished_at = time.time()
        except Exception as e:  # noqa: BLE001 — last-ditch safety net for the worker thread
            with self._lock:
                job.state = JOB_FAILED
                job.error = f"Unexpected: {e!r}"
                job.finished_at = time.time()
        finally:
            self._notify()

    def _on_file_progress(self, job: DownloadJob, file_baseline: int,
                          p: DownloadProgress) -> None:
        """Translate per-file progress into job-level totals."""
        with self._lock:
            # bytes_done = sum of fully-completed prior files + this file's
            # current bytes. Reset to file_baseline + p.bytes_done.
            job.bytes_done = file_baseline + p.bytes_done
            job.bytes_per_sec = p.bytes_per_sec
            # ETA across remaining job bytes:
            remaining = max(0, job.bytes_total - job.bytes_done)
            job.eta_sec = (remaining / p.bytes_per_sec) if p.bytes_per_sec > 0 else None
        self._notify()

    def _notify(self) -> None:
        # Snapshot subscribers under lock; invoke outside to avoid holding
        # the lock during user code (which may take the Tk main-loop lock).
        with self._lock:
            subs = list(self._subscribers)
            jobs = list(self._jobs)
        for cb in subs:
            try:
                cb(jobs)
            except Exception:
                # Subscribers must not crash the worker thread. Swallow.
                pass


# Process-wide singleton.
manager = DownloadManager()
