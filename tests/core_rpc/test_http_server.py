"""In-process unit tests for the FastAPI app built by server.build_app (ADR-0010).

The real-subprocess E2E (test_server_subprocess.py) covers uvicorn + the port
handshake + SSE. This drives build_app() directly with starlette's TestClient to
cover the request branches cheaply: sync result, error envelope, parse error, and
the notification (no-id → 204) and /shutdown paths.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from core_rpc.jobs import JobRegistry
from core_rpc.registry import Context
from core_rpc.server import NotificationHub, build_app
from core_rpc.session import Session

# Importing the methods package registers every handler (system.* used below).
import core_rpc.methods  # noqa: F401


def _make_app(on_shutdown=lambda: None):
    hub = NotificationHub()
    session = Session()
    jobs = JobRegistry(hub.emit)
    ctx = Context(session=session, emit=hub.emit, jobs=jobs)
    return build_app(ctx, hub, on_shutdown)


def _rpc(client, method, params=None, _id=1):
    return client.post(
        "/rpc",
        json={"jsonrpc": "2.0", "method": method, "params": params or {}, "id": _id},
    )


def test_rpc_sync_result():
    with TestClient(_make_app()) as client:
        r = _rpc(client, "system.ping")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == 1
        assert body["result"]["protocol"] == 1


def test_rpc_unknown_method_is_error_envelope():
    with TestClient(_make_app()) as client:
        body = _rpc(client, "does.not.exist").json()
        assert body["error"]["code"] == -32601


def test_rpc_malformed_body_is_parse_error():
    with TestClient(_make_app()) as client:
        r = client.post("/rpc", content=b"{not json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200  # JSON-RPC errors ride a 200, not an HTTP error
        assert r.json()["error"]["code"] == -32700


def test_notification_without_id_returns_204():
    with TestClient(_make_app()) as client:
        # No "id" ⇒ notification ⇒ dispatch returns None ⇒ 204 No Content.
        r = client.post("/rpc", json={"jsonrpc": "2.0", "method": "system.ping"})
        assert r.status_code == 204
        assert r.content == b""


def test_shutdown_invokes_callback():
    called = {"n": 0}
    app = _make_app(on_shutdown=lambda: called.__setitem__("n", called["n"] + 1))
    with TestClient(app) as client:
        r = client.post("/shutdown")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
    assert called["n"] == 1
