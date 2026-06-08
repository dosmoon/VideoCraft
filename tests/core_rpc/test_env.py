"""env.* RPC — environment dashboard (P1-d).

components metadata + the detect/install job plumbing (detection + install
monkeypatched so no real subprocesses / pip runs).
"""

from __future__ import annotations

import time
from typing import Any, Optional

import core_rpc.methods  # noqa: F401  (registers handlers)
from core_rpc.dispatch import dispatch_message


def call(ctx, method: str, params: Optional[dict[str, Any]] = None, id: Any = 1):
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": id}
    if params is not None:
        msg["params"] = params
    return dispatch_message(ctx, msg)


def _wait(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_env_components_shape(ctx):
    rows = call(ctx, "env.components")["result"]
    ids = {r["id"] for r in rows}
    assert {"ffmpeg", "node", "yt-dlp"} <= ids
    assert "google-genai" not in ids  # hidden
    for r in rows:
        assert r["category"] in ("binary", "python")
        assert isinstance(r["installable"], bool)
    # Node is auto-installable (managed), ffmpeg is not.
    by = {r["id"]: r for r in rows}
    assert by["node"]["installable"] is True
    assert by["ffmpeg"]["installable"] is False


def test_env_detect_all_job(ctx, emit, monkeypatch):
    import core_rpc.methods.env as envmod

    monkeypatch.setattr(
        envmod, "_detect", lambda cid: {"id": cid, "available": True, "version": "1.0", "source": "system", "path": "/x"}
    )
    call(ctx, "env.detect_all")
    assert _wait(lambda: emit.of("event.job"))
    res = emit.of("event.job")[-1]["result"]["results"]
    assert all(r["available"] for r in res) and len(res) >= 3
    # Each component streams its result incrementally (UI fills rows as they
    # arrive instead of waiting for the whole batch).
    prog = emit.of("progress.env.detect_all")
    assert prog and {p["result"]["id"] for p in prog} == {r["id"] for r in res}
    assert all(p["result"]["available"] for p in prog)


def test_env_install_streams_log_then_detects(ctx, emit, monkeypatch):
    import core.env as env

    def fake_install(cid, on_log):
        on_log("line-1")
        on_log("line-2")

    monkeypatch.setattr(env, "install_one", fake_install)
    import core_rpc.methods.env as envmod

    monkeypatch.setattr(
        envmod, "_detect", lambda cid: {"id": cid, "available": True, "version": "9", "source": "managed", "path": "/n"}
    )
    call(ctx, "env.install", {"component_id": "node"})
    assert _wait(lambda: emit.of("event.job"))
    logs = [p.get("line") for p in emit.of("progress.env.install")]
    assert logs == ["line-1", "line-2"]
    assert emit.of("event.job")[-1]["result"]["source"] == "managed"
