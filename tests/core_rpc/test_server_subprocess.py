"""End-to-end test of the real server.py over its HTTP transport (ADR-0010).

The dispatch tests cover handler logic in-process; this spawns the actual
`python -m core_rpc.server` subprocess, reads its `VC_RPC_PORT` handshake, and
drives it over HTTP (POST /rpc) + SSE (GET /events) — the only thing exercising
the real uvicorn server, the port handshake, and the emit→SSE notification bridge.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _SidecarProc:
    """Spawns the real sidecar and speaks HTTP/SSE to it."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "core_rpc.server"],
            cwd=_REPO,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        self.base = self._await_handshake()
        self.notifications: list[tuple[str, dict]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        # Set once the SSE stream's first frame (": connected") arrives — which
        # proves the server registered our subscriber. The hub does NOT buffer, so
        # a job fired before this would drop its notifications (a test-only race;
        # in the app the renderer's SSE is open long before any job starts).
        self._connected = threading.Event()
        threading.Thread(target=self._read_events, daemon=True).start()

    def _await_handshake(self, timeout: float = 30.0) -> str:
        assert self.proc.stdout is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith("VC_RPC_PORT "):
                return f"http://127.0.0.1:{int(line.split()[1])}"
        raise TimeoutError("sidecar never printed VC_RPC_PORT handshake")

    def _read_events(self) -> None:
        # One data: line per notification (server yields `data: <json>\n\n`).
        try:
            with urllib.request.urlopen(self.base + "/events", timeout=30) as r:
                for raw in r:
                    if self._stop.is_set():
                        return
                    self._connected.set()  # first byte received ⇒ subscribed
                    s = raw.decode("utf-8").strip()
                    if not s.startswith("data:"):
                        continue  # ": connected" / ": keepalive" comments
                    msg = json.loads(s[5:].strip())
                    if msg.get("method"):
                        with self._lock:
                            self.notifications.append((msg["method"], msg.get("params")))
        except Exception:  # noqa: BLE001 — stream closed on shutdown
            pass

    def rpc(self, method: str, params: dict | None = None, _id: int = 1) -> dict:
        body = json.dumps(
            {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": _id}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/rpc", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def notifs(self, method: str) -> list[dict]:
        with self._lock:
            return [p for m, p in self.notifications if m == method]

    def close(self) -> None:
        self._stop.set()
        try:
            urllib.request.urlopen(
                urllib.request.Request(self.base + "/shutdown", data=b"{}",
                                       headers={"Content-Type": "application/json"}),
                timeout=5,
            ).read()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def sidecar():
    proc = _SidecarProc()
    assert proc._connected.wait(timeout=10), "SSE stream never connected"
    yield proc
    proc.close()


def test_ping_over_real_http(sidecar):
    r = sidecar.rpc("system.ping")
    assert r["result"]["protocol"] == 1
    assert r["result"]["has_project"] is False


def test_cjk_emoji_roundtrips_utf8_clean(sidecar):
    # Non-ASCII must survive the HTTP JSON round-trip intact.
    payload = {"msg": "你好 世界 🎬", "n": 7}
    r = sidecar.rpc("system.echo", payload)
    assert r["result"] == payload


def test_unknown_method_over_http(sidecar):
    r = sidecar.rpc("does.not.exist")
    assert r["error"]["code"] == -32601


def test_job_progress_and_terminal_over_sse(sidecar):
    r = sidecar.rpc("system.demo_job", {"steps": 3, "delay_ms": 20})
    job_id = r["result"]["job_id"]
    # Progress + terminal arrive as SSE notifications.
    deadline = time.time() + 5.0
    while time.time() < deadline and not sidecar.notifs("event.job"):
        time.sleep(0.02)
    progress = sidecar.notifs("progress.demo")
    terminal = sidecar.notifs("event.job")
    assert len(progress) == 3
    assert all(p["job_id"] == job_id for p in progress)
    assert terminal and terminal[-1]["status"] == "succeeded"
