"""gpu.* RPC — CUDA runtime detect + install/uninstall (P1-d).

All jobs; nvidia-smi / pip are monkeypatched so nothing real runs.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import core_rpc.methods  # noqa: F401  (registers handlers)
from core_rpc.dispatch import dispatch_message

_FAKE_STATUS = {
    "available": True,
    "device_name": "RTX 4060 Laptop",
    "driver": "560.00",
    "vram_mb": 8188,
    "wheel": "1.0.0",
    "reason": "ok",
}


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


def test_gpu_status_job(ctx, emit, monkeypatch):
    from core import gpu, gpu_install

    monkeypatch.setattr(gpu, "cuda_status", lambda: dict(_FAKE_STATUS))
    monkeypatch.setattr(gpu_install, "is_installed", lambda: True)
    call(ctx, "gpu.status")
    assert _wait(lambda: emit.of("event.job"))
    res = emit.of("event.job")[-1]["result"]
    assert res["installed"] is True
    assert res["device_name"] == "RTX 4060 Laptop" and res["available"] is True


def test_gpu_install_streams_log_then_status(ctx, emit, monkeypatch):
    from core import gpu, gpu_install

    def fake_install(on_line=None, cancel_token=None):
        on_line("Collecting nvidia-cublas-cu12")
        on_line("Successfully installed")
        return 0

    monkeypatch.setattr(gpu_install, "install", fake_install)
    monkeypatch.setattr(gpu_install, "is_installed", lambda: True)
    monkeypatch.setattr(gpu, "cuda_status", lambda: dict(_FAKE_STATUS))
    call(ctx, "gpu.install")
    assert _wait(lambda: emit.of("event.job"))
    logs = [p.get("line") for p in emit.of("progress.gpu.install")]
    assert logs == ["Collecting nvidia-cublas-cu12", "Successfully installed"]
    assert emit.of("event.job")[-1]["result"]["installed"] is True


def test_gpu_install_nonzero_exit_fails(ctx, emit, monkeypatch):
    from core import gpu_install

    monkeypatch.setattr(gpu_install, "install", lambda on_line=None, cancel_token=None: 1)
    call(ctx, "gpu.install")
    assert _wait(lambda: emit.of("event.job"))
    assert emit.of("event.job")[-1]["status"] == "failed"
