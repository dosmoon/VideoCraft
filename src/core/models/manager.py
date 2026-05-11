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

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from core.models.catalog import CATALOG, ModelSpec, get
from core.models.downloader import (
    DownloadProgress, CancelToken, DownloadError, download_file, verify_file,
)
from core.models.hf_api import (
    ResolvedFile, resolve_files, resolve_all_files, ResolveError,
)
from core.models.registry import disk_free_bytes


JOB_QUEUED    = "queued"
JOB_RUNNING   = "running"
JOB_DONE      = "done"
JOB_FAILED    = "failed"
JOB_CANCELLED = "cancelled"

# Per-job parallel downloader thread pool size. Tuned for Kokoro-style
# many-tiny-files repos (375 files, avg 0.5 MB) where per-file TCP
# roundtrip dominates wall time. Big single-file models (Qwen, Whisper)
# don't benefit — they saturate bandwidth on one connection anyway,
# but a few workers doing nothing is harmless.
_MAX_PARALLEL_FILES = 8


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
            recycled = None
            for j in self._jobs:
                if j.model_id != model_id:
                    continue
                if j.state in (JOB_QUEUED, JOB_RUNNING):
                    # Already in flight — dedup.
                    return j.job_id
                if j.state in (JOB_CANCELLED, JOB_FAILED, JOB_DONE):
                    # Reuse the row so the UI doesn't sprout a duplicate.
                    # `.part` on disk drives the actual byte-level resume;
                    # the row recycle is purely cosmetic.
                    recycled = j
                    break
            spec = get(model_id)
            if recycled is not None:
                recycled.state = JOB_QUEUED
                recycled.bytes_done = 0
                recycled.bytes_per_sec = 0.0
                recycled.eta_sec = None
                recycled.current_file = ""
                recycled.current_url = ""
                recycled.error = ""
                recycled.started_at = 0.0
                recycled.finished_at = 0.0
                recycled.cancel_token = CancelToken()
                recycled.resolved_files = []
                job = recycled
            else:
                job = DownloadJob(
                    job_id=f"job-{self._next_id}",
                    model_id=model_id,
                    spec=spec,
                )
                self._next_id += 1
                self._jobs.append(job)

        # Resolve outside the lock — HF API call may block on network.
        try:
            if spec.download_all:
                resolved = resolve_all_files(spec.repo, spec.revision)
            else:
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
                if spec.download_all:
                    files = resolve_all_files(spec.repo, spec.revision)
                else:
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
            # Triage: separate already-complete files (skip) from pending.
            # Files complete on disk count toward the start baseline so the
            # progress bar reflects them immediately on a re-enqueued job.
            pending: list[tuple] = []  # (rf, target_path)
            baseline_done = 0
            for rf in job.resolved_files:
                if job.cancel_token.cancelled:
                    raise DownloadError("cancelled", "Cancelled by user")
                target = job.spec.file_path(rf.path)
                if verify_file(target, expected_sha256=rf.sha256,
                               expected_size=rf.size):
                    baseline_done += rf.size
                    continue
                pending.append((rf, target))

            with self._lock:
                job.bytes_done = baseline_done
            self._notify()

            if not pending:
                # All files were already on disk.
                with self._lock:
                    job.state = JOB_DONE
                    job.finished_at = time.time()
                    job.bytes_done = job.bytes_total
                    job.current_file = ""
                    job.current_url = ""
                return

            # Parallel per-file download. Per-file progress is tracked in
            # `file_bytes` (path → last reported in-flight bytes) and
            # aggregated into job.bytes_done on every progress emit. Cancel
            # token is shared across workers — flipping it stops them all
            # at the next chunk boundary.
            file_bytes: dict[str, int] = {}
            file_bytes_lock = threading.Lock()
            # Local monotonic clock for speed/ETA. job.started_at uses
            # wall clock for human display; mixing the two clocks here
            # gave bogus GB/s readings on the first emit.
            exec_started = time.monotonic()

            def _emit_aggregate(notify_after: bool = True) -> None:
                with file_bytes_lock:
                    in_flight = sum(file_bytes.values())
                elapsed = max(time.monotonic() - exec_started, 1e-3)
                with self._lock:
                    job.bytes_done = baseline_done + in_flight
                    rate = (job.bytes_done - baseline_done) / elapsed
                    job.bytes_per_sec = rate
                    remaining = max(0, job.bytes_total - job.bytes_done)
                    job.eta_sec = (remaining / rate) if rate > 0 else None
                if notify_after:
                    self._notify()

            def _on_file_progress(rf, p: DownloadProgress) -> None:
                with file_bytes_lock:
                    file_bytes[rf.path] = p.bytes_done
                with self._lock:
                    # Last writer wins for current_file label; that's
                    # acceptable since UI is just showing "what's active".
                    job.current_file = rf.path
                    job.current_url = p.url
                _emit_aggregate()

            def _download_one(rf, target: str) -> None:
                """Try each source URL in order; raise on total failure."""
                # Pre-seed with .part size (resumable from a prior run)
                # so the per-file accounting is accurate from the start.
                part_path = target + ".part"
                part_existing = 0
                if os.path.exists(part_path):
                    try:
                        part_existing = os.path.getsize(part_path)
                    except OSError:
                        part_existing = 0
                with file_bytes_lock:
                    file_bytes[rf.path] = part_existing

                last_err: DownloadError | None = None
                for url in rf.urls:
                    if job.cancel_token.cancelled:
                        raise DownloadError("cancelled", "Cancelled by user")
                    try:
                        download_file(
                            url, target,
                            expected_size=rf.size,
                            expected_sha256=rf.sha256,
                            on_progress=lambda p, r=rf: _on_file_progress(r, p),
                            cancel_token=job.cancel_token,
                        )
                        with file_bytes_lock:
                            file_bytes[rf.path] = rf.size
                        return
                    except DownloadError as e:
                        last_err = e
                        if e.kind == "cancelled":
                            raise
                        continue
                msg = (last_err.args[0] if last_err and last_err.args
                       else "all sources failed")
                raise DownloadError(
                    last_err.kind if last_err else "network",
                    f"{rf.path}: {msg}",
                )

            # Cap workers at min(_MAX_PARALLEL_FILES, len(pending)) so a
            # 1-file job spawns 1 worker (no overhead) and a 375-file job
            # uses 8 (saturating ~typical hf-mirror per-IP slot count).
            worker_count = min(_MAX_PARALLEL_FILES, len(pending))
            with ThreadPoolExecutor(max_workers=worker_count,
                                     thread_name_prefix="ModelDL") as ex:
                futures = [ex.submit(_download_one, rf, target)
                           for rf, target in pending]
                for f in as_completed(futures):
                    # First exception wins; cancel remaining workers via
                    # the shared cancel_token so the pool drains quickly.
                    try:
                        f.result()
                    except DownloadError as e:
                        if e.kind != "cancelled":
                            job.cancel_token.cancel()
                        raise

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
