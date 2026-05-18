"""creations/clip/render_queue.py — off-thread batch render orchestrator."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from core.composition import CompositionRequest
from creations.clip.render_queue import RenderJob, RenderQueue


# ── Test doubles ─────────────────────────────────────────────────────────────

class _FakeMaster:
    """Tk-master double — runs scheduled callbacks synchronously to keep
    tests single-threaded and deterministic."""
    def after(self, _delay_ms, fn):
        fn()


@dataclass
class _FakeResult:
    duration_sec: float


def _make_req(out_idx: int) -> CompositionRequest:
    """Minimal CompositionRequest stub — render_fn is mocked, so only
    output_path needs to be populated (for cleanup_stale basename calc)."""
    return CompositionRequest(
        source_video="/tmp/v.mp4",
        start_sec=0.0, end_sec=1.0,
        output_path=f"/tmp/clip_{out_idx:03d}.mp4",
        output_geometry=None,            # type: ignore[arg-type]
        encode_preset=None,              # type: ignore[arg-type]
        timeline=None,                   # type: ignore[arg-type]
    )


def _make_jobs(n: int) -> list[RenderJob]:
    return [RenderJob(out_idx=i + 1, src_idx=i, request=_make_req(i + 1))
            for i in range(n)]


@dataclass
class _Calls:
    """Capture all callbacks the queue fires, in order."""
    progress: list = None  # type: ignore[assignment]
    succeeded: list = None  # type: ignore[assignment]
    failed: list = None  # type: ignore[assignment]
    all_done: list = None  # type: ignore[assignment]
    cleanup: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.progress is None:
            self.progress = []
        if self.succeeded is None:
            self.succeeded = []
        if self.failed is None:
            self.failed = []
        if self.all_done is None:
            self.all_done = []
        if self.cleanup is None:
            self.cleanup = []


def _make_queue(render_fn: Callable, *, master=None,
                  calls: _Calls = None) -> tuple[RenderQueue, _Calls]:
    """Build a RenderQueue plumbed through a Calls capture."""
    if calls is None:
        calls = _Calls()
    if master is None:
        master = _FakeMaster()
    q = RenderQueue(
        master,
        on_progress=lambda *a: calls.progress.append(a),
        on_succeeded=lambda *a: calls.succeeded.append(a),
        on_failed=lambda *a: calls.failed.append(a),
        on_all_done=lambda *a: calls.all_done.append(a),
        cleanup_stale_fn=lambda *a: calls.cleanup.append(a),
        render_fn=render_fn,
    )
    return q, calls


def _join(q: RenderQueue, timeout: float = 5.0) -> None:
    """Wait for the background thread to finish."""
    if q._thread is not None:
        q._thread.join(timeout=timeout)


# ── happy path ──────────────────────────────────────────────────────────────

def test_start_runs_all_jobs_in_order():
    """All jobs render; on_succeeded fires once per job; on_all_done
    fires last with last_error=None."""
    rendered: list[int] = []

    def fake_render(req, *, on_progress, cancel_check):
        rendered.append(int(req.output_path.split("_")[-1].split(".")[0]))
        return _FakeResult(duration_sec=10.0)

    q, calls = _make_queue(fake_render)
    q.start(_make_jobs(3))
    _join(q)

    assert rendered == [1, 2, 3]
    assert len(calls.succeeded) == 3
    assert calls.all_done == [(None,)]
    assert len(calls.failed) == 0


def test_each_job_cleanup_fires_before_render():
    """cleanup_stale_fn must run for each job before its render starts,
    using the upcoming basename."""
    order: list[str] = []

    def fake_render(req, *, on_progress, cancel_check):
        order.append(f"render:{req.output_path}")
        return _FakeResult(duration_sec=1.0)

    calls = _Calls()
    calls.cleanup = []  # we'll watch order via wrapper
    q = RenderQueue(
        _FakeMaster(),
        on_progress=lambda *a: None,
        on_succeeded=lambda *a: None,
        on_failed=lambda *a: None,
        on_all_done=lambda *a: None,
        cleanup_stale_fn=lambda oi, base: order.append(f"cleanup:{oi}:{base}"),
        render_fn=fake_render,
    )
    q.start(_make_jobs(2))
    _join(q)

    assert order == [
        "cleanup:1:clip_001",
        "render:/tmp/clip_001.mp4",
        "cleanup:2:clip_002",
        "render:/tmp/clip_002.mp4",
    ]


def test_progress_callback_marshalled_through_master():
    """The render_fn's on_progress arg, when called, must marshal a
    progress callback onto master.after."""
    posts: list = []

    class _RecordingMaster:
        def after(self, _delay, fn):
            posts.append(fn)
            fn()

    def fake_render(req, *, on_progress, cancel_check):
        on_progress("stage", 50)
        on_progress("stage", 100)
        return _FakeResult(duration_sec=1.0)

    q, calls = _make_queue(fake_render, master=_RecordingMaster())
    q.start(_make_jobs(1))
    _join(q)

    # 1 start-of-clip progress (0%) + 2 fake on_progress + 1 succeeded + 1 all_done
    assert len(posts) >= 4
    # Progress payloads: (done, total, out_idx, pct)
    pcts = [a[3] for a in calls.progress]
    assert 0 in pcts and 50 in pcts and 100 in pcts


# ── failure ─────────────────────────────────────────────────────────────────

def test_exception_fires_on_failed_then_continues():
    """A raised exception must surface via on_failed and NOT stop the
    queue — remaining jobs still run."""
    def fake_render(req, *, on_progress, cancel_check):
        if "002" in req.output_path:
            raise RuntimeError("boom")
        return _FakeResult(duration_sec=1.0)

    q, calls = _make_queue(fake_render)
    q.start(_make_jobs(3))
    _join(q)

    assert len(calls.succeeded) == 2   # clips 1 and 3
    assert len(calls.failed) == 1
    failed_job, msg = calls.failed[0]
    assert failed_job.out_idx == 2
    assert "boom" in msg
    # last_error reflects the failure
    assert calls.all_done == [("#2: boom",)]


def test_interrupted_error_stops_loop_silently():
    """An InterruptedError (libass / ffmpeg signal of user cancel) ends
    the batch without firing on_failed for that job."""
    def fake_render(req, *, on_progress, cancel_check):
        if "002" in req.output_path:
            raise InterruptedError()
        return _FakeResult(duration_sec=1.0)

    q, calls = _make_queue(fake_render)
    q.start(_make_jobs(3))
    _join(q)

    assert len(calls.succeeded) == 1   # only clip 1
    assert len(calls.failed) == 0
    assert calls.all_done == [(None,)]


# ── cancellation ────────────────────────────────────────────────────────────

def test_cancel_skips_remaining_jobs():
    """Calling cancel() before the next job starts must abort the
    remaining loop."""
    counter = {"n": 0}

    def fake_render(req, *, on_progress, cancel_check):
        counter["n"] += 1
        if counter["n"] == 1:
            # Simulate the user clicking cancel between jobs 1 and 2
            q.cancel()
        return _FakeResult(duration_sec=1.0)

    q, calls = _make_queue(fake_render)
    q.start(_make_jobs(3))
    _join(q)

    assert counter["n"] == 1
    assert q.is_cancelled is True


def test_is_busy_during_render():
    """is_busy must be True while a render is in flight, False after."""
    started = threading.Event()
    release = threading.Event()

    def fake_render(req, *, on_progress, cancel_check):
        started.set()
        release.wait(timeout=2.0)
        return _FakeResult(duration_sec=1.0)

    # Need a master that schedules callbacks on a worker thread to
    # avoid blocking the test; use _FakeMaster which runs sync — but
    # since render is on a worker thread, master callbacks are scheduled
    # from the worker and we don't deadlock.
    q, _ = _make_queue(fake_render)
    q.start(_make_jobs(1))
    assert started.wait(timeout=2.0), "worker never entered render_fn"
    assert q.is_busy is True
    release.set()
    _join(q)
    assert q.is_busy is False


def test_double_start_ignored():
    """start() while a batch is in flight must be a no-op."""
    release = threading.Event()

    def fake_render(req, *, on_progress, cancel_check):
        release.wait(timeout=2.0)
        return _FakeResult(duration_sec=1.0)

    q, calls = _make_queue(fake_render)
    q.start(_make_jobs(1))
    q.start(_make_jobs(5))   # ignored
    release.set()
    _join(q)
    assert len(calls.succeeded) == 1


# ── empty input ─────────────────────────────────────────────────────────────

def test_empty_job_list_still_fires_all_done():
    """A batch of zero jobs must still call on_all_done(None)."""
    q, calls = _make_queue(lambda *_a, **_kw: None)
    q.start([])
    _join(q)
    assert calls.all_done == [(None,)]
    assert calls.succeeded == [] and calls.failed == []
