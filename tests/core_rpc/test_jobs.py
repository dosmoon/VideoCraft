"""Tests for the long-task path: job_id response + progress/terminal events.

Drives system.demo_job (a synthetic long task) so the job registry, progress
notifications, and terminal event are exercised without ASR/render.
"""

from __future__ import annotations

import time

from core_rpc.dispatch import dispatch_message


def call(ctx, method, params=None, id=1):
    msg = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


def _wait_for(predicate, timeout=2.0):
    """Spin until predicate() or timeout (job runs on a daemon thread)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_demo_job_returns_id_then_progress_then_terminal(ctx, emit):
    resp = call(ctx, "system.demo_job", {"steps": 3, "delay_ms": 0})
    job_id = resp["result"]["job_id"]
    assert job_id.startswith("job-")

    # Terminal event arrives asynchronously (job runs on a daemon thread).
    assert _wait_for(lambda: emit.of("event.job"))

    progress = emit.of("progress.demo")
    assert len(progress) == 3
    assert progress[0]["job_id"] == job_id
    assert progress[-1] == {"job_id": job_id, "done": 3, "total": 3, "pct": 1.0}

    terminal = emit.of("event.job")[-1]
    assert terminal["status"] == "succeeded"
    assert terminal["result"] == {"steps": 3}
    assert terminal["kind"] == "demo"


def test_job_cancel(ctx, emit):
    # Enough steps + delay that we can cancel mid-flight.
    resp = call(ctx, "system.demo_job", {"steps": 50, "delay_ms": 10})
    job_id = resp["result"]["job_id"]

    assert _wait_for(lambda: ctx.jobs.active_ids())  # worker started
    assert call(ctx, "job.cancel", {"job_id": job_id})["result"] == {"cancelled": True}

    assert _wait_for(lambda: emit.of("event.job"))
    terminal = emit.of("event.job")[-1]
    assert terminal["status"] == "cancelled"
    # Cancelled before all 50 steps emitted.
    assert len(emit.of("progress.demo")) < 50


def test_cancel_unknown_job_is_false(ctx):
    assert call(ctx, "job.cancel", {"job_id": "job-999"})["result"] == {
        "cancelled": False
    }
