"""embedded_ai.* RPC — opt-in faster-whisper / llama-cpp install (P3 §5.3).

All jobs; the installer is monkeypatched so no real pip runs. Mirrors test_gpu.
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


def test_status_reports_installed(ctx, emit, monkeypatch):
    from core import embedded_ai_install

    monkeypatch.setattr(embedded_ai_install, "is_installed", lambda: True)
    call(ctx, "embedded_ai.status")
    assert _wait(lambda: emit.of("event.job"))
    assert emit.of("event.job")[-1]["result"]["installed"] is True


def test_install_streams_log_then_status(ctx, emit, monkeypatch):
    from core import embedded_ai_install

    def fake_install(on_line=None, cancel_token=None):
        on_line("Collecting faster-whisper")
        on_line("Successfully installed")
        return 0

    monkeypatch.setattr(embedded_ai_install, "install", fake_install)
    monkeypatch.setattr(embedded_ai_install, "is_installed", lambda: True)
    call(ctx, "embedded_ai.install")
    assert _wait(lambda: emit.of("event.job"))
    logs = [p.get("line") for p in emit.of("progress.embedded_ai.install")]
    assert logs == ["Collecting faster-whisper", "Successfully installed"]
    assert emit.of("event.job")[-1]["result"]["installed"] is True


def test_install_nonzero_exit_fails(ctx, emit, monkeypatch):
    from core import embedded_ai_install

    monkeypatch.setattr(embedded_ai_install, "install",
                        lambda on_line=None, cancel_token=None: 1)
    call(ctx, "embedded_ai.install")
    assert _wait(lambda: emit.of("event.job"))
    assert emit.of("event.job")[-1]["status"] == "failed"
