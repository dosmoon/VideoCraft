"""End-to-end test of the real server.py stdio loop.

The dispatch tests cover handler logic in-process; this spawns the actual
`python -m core_rpc.server` subprocess and exchanges JSON-RPC over its pipes,
so it's the only thing exercising the binary framing + reader/writer threads
(the Windows '\\n'→'\\r\\n' framing hazard in particular).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _SidecarProc:
    """Minimal client: spawns the sidecar and frames JSON-RPC over its stdio."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "core_rpc.server"],
            cwd=_REPO,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.responses: dict[int, dict] = {}
        self.notifications: list[tuple[str, dict]] = []
        self._id = 0
        self._lock = threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            msg = json.loads(line)
            with self._lock:
                if msg.get("id") is None and msg.get("method"):
                    self.notifications.append((msg["method"], msg.get("params")))
                else:
                    self.responses[msg["id"]] = msg

    def send(self, method: str, params: dict | None = None) -> int:
        self._id += 1
        rid = self._id
        msg = {"jsonrpc": "2.0", "method": method, "id": rid}
        if params is not None:
            msg["params"] = params
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        return rid

    def wait(self, rid: int, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rid in self.responses:
                    return self.responses[rid]
            time.sleep(0.01)
        raise TimeoutError(f"no response for id {rid}")

    def notifs(self, method: str) -> list[dict]:
        with self._lock:
            return [p for m, p in self.notifications if m == method]

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


@pytest.fixture
def sidecar():
    proc = _SidecarProc()
    time.sleep(0.5)  # let the plugin import + handler registration finish
    yield proc
    proc.close()


def test_ping_over_real_stdio(sidecar):
    r = sidecar.wait(sidecar.send("system.ping"))
    assert r["result"]["protocol"] == 1
    assert r["result"]["has_project"] is False


def test_cjk_emoji_roundtrips_byte_clean(sidecar):
    # The whole point of binary framing: non-ASCII survives the pipe intact.
    payload = {"msg": "你好 世界 🎬", "n": 7}
    r = sidecar.wait(sidecar.send("system.echo", payload))
    assert r["result"] == payload


def test_unknown_method_over_stdio(sidecar):
    r = sidecar.wait(sidecar.send("does.not.exist"))
    assert r["error"]["code"] == -32601


def test_job_progress_and_terminal_over_stdio(sidecar):
    r = sidecar.wait(sidecar.send("system.demo_job", {"steps": 3, "delay_ms": 20}))
    job_id = r["result"]["job_id"]
    # Progress + terminal arrive as notifications on the same pipe.
    deadline = time.time() + 5.0
    while time.time() < deadline and not sidecar.notifs("event.job"):
        time.sleep(0.02)
    progress = sidecar.notifs("progress.demo")
    terminal = sidecar.notifs("event.job")
    assert len(progress) == 3
    assert all(p["job_id"] == job_id for p in progress)
    assert terminal and terminal[-1]["status"] == "succeeded"
