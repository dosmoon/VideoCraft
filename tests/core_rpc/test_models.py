"""models.* RPC — local model manager (P1-d).

Catalog shape + disk-only installed state, and the download/cancel/remove
plumbing (download manager monkeypatched so no real network/disk I/O runs).
"""

from __future__ import annotations

from typing import Any, Optional

import core_rpc.methods  # noqa: F401  (registers handlers)
from core_rpc.dispatch import dispatch_message


def call(ctx, method: str, params: Optional[dict[str, Any]] = None, id: Any = 1):
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


def test_models_catalog_shape(ctx):
    rows = call(ctx, "models.catalog")["result"]
    assert len(rows) >= 4  # faster-whisper x2 + qwen3 x2
    ids = {r["id"] for r in rows}
    assert "faster-whisper-small" in ids
    for r in rows:
        assert r["capability"] in ("asr", "llm", "tts", "vad")
        assert isinstance(r["installed"], bool)
        assert r["total"] >= 1 and 0 <= r["present"] <= r["total"]
        assert r["dir"]  # resolved target dir


def test_models_jobs_empty(ctx):
    assert isinstance(call(ctx, "models.jobs")["result"], list)


def test_models_download_enqueues(ctx, monkeypatch):
    # core.models re-exports the DownloadManager singleton as `manager`.
    from core.models import manager as dm

    monkeypatch.setattr(dm, "enqueue", lambda model_id: "job-zz")
    monkeypatch.setattr(dm, "on_event", lambda cb: (lambda: None))
    out = call(ctx, "models.download", {"model_id": "faster-whisper-small"})["result"]
    assert out == {"job_id": "job-zz"}


def test_models_remove(ctx, monkeypatch):
    from core.models import registry

    monkeypatch.setattr(registry, "remove", lambda model_id: 12345)
    assert call(ctx, "models.remove", {"model_id": "faster-whisper-small"})["result"] == {
        "freed": 12345
    }


def test_models_cancel(ctx, monkeypatch):
    from core.models import manager as dm

    called = {}
    monkeypatch.setattr(dm, "cancel", lambda job_id: called.setdefault("id", job_id))
    assert call(ctx, "models.cancel", {"job_id": "job-1"})["result"] == {"ok": True}
    assert called["id"] == "job-1"


def test_models_root_dir(ctx):
    out = call(ctx, "models.root_dir")["result"]
    assert isinstance(out["dir"], str) and out["dir"]


def test_models_set_root_dir(ctx, monkeypatch):
    from core.ai.router import router

    seen = {}
    monkeypatch.setattr(router, "set_models_dir", lambda p: seen.setdefault("p", p))
    out = call(ctx, "models.set_root_dir", {"path": "/tmp/models-x"})["result"]
    assert seen["p"] == "/tmp/models-x"
    assert "dir" in out
