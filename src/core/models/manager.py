"""Background download manager: queue + source fallback + disk preflight.

Single worker thread processes a FIFO queue. Each job's spec is resolved
against HF API at enqueue (so size/sha256/URLs are known truth, not
guesses). Resolution failure short-circuits the job to FAILED with the
HF error attached.

UI consumers subscribe via `on_event(callback)` and receive snapshots
of all jobs. The callback runs on the worker thread — UI code must
marshal to the Tk main thread itself (`master.after(0, lambda: ...)`).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from core.models.catalog import CATALOG, ModelSpec, get
from core.models.downloader import (
    DownloadProgress, CancelToken, DownloadError, download_file, verify_file,
)
from core.models.hf_api import (
    ResolvedFile, resolve_files, ResolveError,
)
from core.models.registry import disk_free_bytes


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
    current_file: str = ""
    current_url: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    cancel_token: CancelToken = field(default_factory=CancelToken)
    resolved_files: list[ResolvedFile] = field(default_factory=list)

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

        Resolution against HF happens at enqueue time so we know real
        bytes_total before the job starts. If HF is unreachable AND we
        have no cached metadata, the job is created in FAILED state with
        the error attached — the user sees something in the queue rather
        than a silent no-op.
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
            )
            self._next_id += 1
            self._jobs.append(job)

        # Resolve outside the lock — HF API call may block on network.
        try:
            resolved = resolve_files(
                spec.repo, spec.revision, list(spec.filenames),
            )
            with self._lock:
                job.resolved_files = resolved
                job.bytes_total = sum(rf.size for rf in resolved)
            self._ensure_worker()
            self._wake.set()
        except ResolveError as e:
            with self._lock:
                job.state = JOB_FAILED
                job.error = f"Could not fetch HF metadata: {e}"
                job.finished_at = time.time()

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
        with self._lock:
            self._jobs = [j for j in self._jobs
                          if j.state in (JOB_QUEUED, JOB_RUNNING)]
        self._notify()

    def list_jobs(self) -> list[DownloadJob]:
        with self._lock:
            return list(self._jobs)

    def on_event(self, callback: EventCallback) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)
        def _unsub() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)
        return _unsub

    @staticmethod
    def preflight_disk(model_ids: list[str]) -> tuple[bool, int, int, str]:
        """(ok, needed_bytes, free_bytes, target_dir).

        Resolves each spec to compute exact needed bytes. Resolve failure
        contributes 0 — preflight is best-effort, not a gate.
        """
        from core.paths import models_dir
        needed = 0
        for mid in model_ids:
            if mid not in CATALOG:
                continue
            spec = get(mid)
            try:
                files = resolve_files(spec.repo, spec.revision,
                                       list(spec.filenames))
                needed += sum(rf.size for rf in files)
            except ResolveError:
                pass
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
                self._wake.clear()
                self._wake.wait(timeout=30.0)
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
            for rf in job.resolved_files:
                if job.cancel_token.cancelled:
                    raise DownloadError("cancelled", "Cancelled by user")
                target = job.spec.file_path(rf.path)

                # Skip files already complete (re-enqueue idempotency).
                if verify_file(target, expected_sha256=rf.sha256,
                               expected_size=rf.size):
                    with self._lock:
                        job.bytes_done += rf.size
                        job.current_file = rf.path
                    self._notify()
                    continue

                with self._lock:
                    job.current_file = rf.path
                file_baseline = job.bytes_done

                last_err: DownloadError | None = None
                file_complete = False
                for url in rf.urls:
                    if job.cancel_token.cancelled:
                        raise DownloadError("cancelled", "Cancelled by user")
                    with self._lock:
                        job.current_url = url
                    try:
                        download_file(
                            url, target,
                            expected_size=rf.size,
                            expected_sha256=rf.sha256,
                            on_progress=lambda p, fb=file_baseline, j=job:
                                self._on_file_progress(j, fb, p),
                            cancel_token=job.cancel_token,
                        )
                        file_complete = True
                        with self._lock:
                            job.bytes_done = file_baseline + rf.size
                        break
                    except DownloadError as e:
                        last_err = e
                        if e.kind == "cancelled":
                            raise
                        continue

                if not file_complete:
                    msg = (last_err.args[0] if last_err and last_err.args
                           else "all sources failed")
                    raise DownloadError(
                        last_err.kind if last_err else "network",
                        f"{rf.path}: {msg}",
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
        except Exception as e:  # noqa: BLE001
            with self._lock:
                job.state = JOB_FAILED
                job.error = f"Unexpected: {e!r}"
                job.finished_at = time.time()
        finally:
            self._notify()

    def _on_file_progress(self, job: DownloadJob, file_baseline: int,
                          p: DownloadProgress) -> None:
        with self._lock:
            job.bytes_done = file_baseline + p.bytes_done
            job.bytes_per_sec = p.bytes_per_sec
            remaining = max(0, job.bytes_total - job.bytes_done)
            job.eta_sec = (remaining / p.bytes_per_sec) if p.bytes_per_sec > 0 else None
        self._notify()

    def _notify(self) -> None:
        with self._lock:
            subs = list(self._subscribers)
            jobs = list(self._jobs)
        for cb in subs:
            try:
                cb(jobs)
            except Exception:
                pass


manager = DownloadManager()
