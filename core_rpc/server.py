"""Sidecar HTTP server (FastAPI + uvicorn).

Transport (ADR-0010 — the stdin-deadlock cure):
  - POST /rpc      one JSON-RPC request object → dispatch_message → response object
  - GET  /events   Server-Sent Events stream of server→client notifications
                   (progress.*, event.job, event.project.*, event.materials.changed,
                    event.creations.changed, event.models)
  - POST /shutdown graceful stop

Why HTTP and not the old newline-JSON-over-stdio loop: the stdio loop parked the
main thread forever in a blocking ``sys.stdin.buffer`` read between requests. When
a job daemon thread then imported a native C-extension (ctranslate2 via
faster-whisper, llama_cpp) for the FIRST time, that import deadlocked against the
blocked stdin read — the ASR "loading model" hang, papered over by a startup warm-up
checklist that did not cover runtime-installed extras. An ASGI server has no blocking
stdin read anywhere, so that whole class is gone. aistack already runs the same
ctranslate2 under uvicorn worker threads without the hang — this aligns the embedded
path with that proven model.

The dispatch core is transport-free: ``dispatch_message(ctx, obj)`` and every
``@rpc_method`` handler are unchanged — only this shell swapped. stdout carries
exactly ONE line: the ``VC_RPC_PORT <n>`` handshake the Electron host reads to learn
where to connect. Everything else (logs, tracebacks) goes to stderr.
"""

from __future__ import annotations

import os
import sys

# ── sys.path bootstrap (must precede importing .methods, which pulls src/) ────
# Dev: repo root is two levels up from this file (core_rpc/server.py → repo).
# Packaged (PyInstaller onedir): there is no repo — the bundled src/ tree sits
# under sys._MEIPASS, so anchor there instead (packaging-design.md §5.1).
if getattr(sys, "frozen", False):
    _REPO = sys._MEIPASS  # type: ignore[attr-defined]
else:
    _REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Make opt-in heavy extras importable: user_data/runtimes/py-extra is where the
# CUDA wheels and embedded-AI runtimes (faster-whisper / llama-cpp) get installed
# at runtime, because the frozen sidecar's own site-packages are sealed
# (packaging-design.md §5.3). Must precede load_plugins() / native warm-up below,
# both of which may import those extras. No-op in a fresh dev checkout (empty dir).
from core.runtime_extras import ensure_on_sys_path  # noqa: E402

ensure_on_sys_path()

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from typing import Any, Callable, Optional  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse, Response, StreamingResponse  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from . import protocol  # noqa: E402
from .dispatch import dispatch_message  # noqa: E402
from .jobs import JobRegistry  # noqa: E402
from .registry import Context  # noqa: E402
from .session import Session  # noqa: E402

# FastAPI route handlers are defined inside build_app() as closures, but their
# parameter annotations (e.g. `request: Request`) must resolve against MODULE
# globals — `from __future__ import annotations` stringifies them and FastAPI's
# get_type_hints() does not see a nested function's local imports. Hence these
# names live at module scope, not inside build_app.


def _log(*args: Any) -> None:
    """Diagnostics to stderr only — stdout is the port-handshake channel."""
    print("[core_rpc]", *args, file=sys.stderr, flush=True)


class NotificationHub:
    """Bridges synchronous ``emit(method, params)`` calls — made from handlers
    and job daemon threads — to the async SSE subscribers running on the event
    loop. ``emit`` is thread-safe; delivery hops onto the loop via
    ``call_soon_threadsafe``. This replaces the old outbound queue + writer
    thread, keeping all output funnelled through one place.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subs: "set[asyncio.Queue[dict[str, Any]]]" = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, method: str, params: Optional[dict[str, Any]]) -> None:
        """Push a notification to every SSE subscriber. Safe from any thread."""
        msg = protocol.make_notification(method, params)
        loop = self._loop
        if loop is None:
            # No event loop yet (before serving). Handlers/jobs only run after a
            # request arrives, i.e. after startup, so this should not happen —
            # drop rather than crash if it ever does.
            return
        loop.call_soon_threadsafe(self._fanout, msg)

    def _fanout(self, msg: dict[str, Any]) -> None:
        # Runs on the loop thread, so touching the subscriber set is race-free.
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:  # unbounded queues → never raised; defensive
                pass

    def subscribe(self) -> "asyncio.Queue[dict[str, Any]]":
        q: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue()
        self._subs.add(q)
        return q

    def unsubscribe(self, q: "asyncio.Queue[dict[str, Any]]") -> None:
        self._subs.discard(q)


def build_app(ctx: Context, hub: NotificationHub, on_shutdown: Callable[[], None]):
    """Construct the FastAPI app. Pure (no I/O / no server start) so tests can
    drive it with starlette's TestClient."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: "FastAPI"):
        hub.bind_loop(asyncio.get_running_loop())
        yield

    app = FastAPI(lifespan=lifespan)

    # Serialize request handling to preserve the OLD single-threaded stdio loop's
    # guarantee: one request processed at a time, in arrival order. The 63 handlers
    # were written assuming sequential access to the shared Session; HTTP would
    # otherwise let them run concurrently in threadpool threads. Jobs are untouched
    # by this lock — they run on their own daemon threads (JobRegistry), exactly as
    # before, so long work never blocks the channel.
    dispatch_lock = asyncio.Lock()

    @app.post("/rpc")
    async def rpc(request: Request):  # noqa: ANN202
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — malformed body → JSON-RPC parse error
            return JSONResponse(
                protocol.make_error(None, protocol.PARSE_ERROR, "parse error: invalid JSON body")
            )
        async with dispatch_lock:
            # dispatch_message is sync and may do blocking disk I/O; offload it so
            # the event loop (and the SSE stream) stays responsive.
            resp = await run_in_threadpool(dispatch_message, ctx, body)
        if resp is None:
            return Response(status_code=204)  # notification — no reply
        return JSONResponse(resp)

    @app.get("/events")
    async def events():  # noqa: ANN202
        async def gen():
            q = hub.subscribe()
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"  # keep the connection live / flush
                        continue
                    data = json.dumps(msg, ensure_ascii=False, separators=(",", ":"))
                    yield f"data: {data}\n\n"
            finally:
                # Cancelled on client disconnect → drop the subscriber.
                hub.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/shutdown")
    async def shutdown():  # noqa: ANN202
        on_shutdown()
        return {"ok": True}

    return app


def main() -> int:
    # Import + register all handlers, then self-register plugins. A plugin
    # import failure should be loud (the sidecar is useless without them).
    from .methods import load_plugins

    try:
        load_plugins()
    except Exception as exc:  # noqa: BLE001
        _log("plugin load failed:", exc)
        # Continue anyway: system.*/project.* still work; material.* will error
        # cleanly per request rather than killing the process.

    hub = NotificationHub()
    session = Session()
    jobs = JobRegistry(hub.emit)
    ctx = Context(session=session, emit=hub.emit, jobs=jobs)

    # Warm native C-extension imports on a background thread. This is now only a
    # first-ASR latency optimization, NOT a deadlock fix: with no blocking stdin
    # read anywhere, importing ctranslate2/llama_cpp first on a job thread no longer
    # hangs (ADR-0010). Best-effort; absent extras (packaged base tier) are skipped.
    def _warm() -> None:
        try:
            from core.ai.warmup import warm_native_extensions

            warm_native_extensions(_log)
        except Exception as exc:  # noqa: BLE001 — never let warm-up affect startup
            _log("native warm-up error (non-fatal):", exc)

    threading.Thread(target=_warm, name="native-warmup", daemon=True).start()

    # uvicorn/our logs → stderr; stdout is reserved for the ONE handshake line.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    import uvicorn

    # Bind an ephemeral loopback port ourselves so we know it BEFORE serving and
    # can announce it on stdout (avoids port-conflict guesswork). uvicorn then
    # serves this pre-bound socket.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

    server_box: dict[str, Any] = {}

    def _request_stop() -> None:
        srv = server_box.get("server")
        if srv is not None:
            # force_exit so an open /events SSE stream doesn't stall the graceful
            # shutdown wait — this is a teardown signal, drop in-flight connections.
            srv.should_exit = True
            srv.force_exit = True

    app = build_app(ctx, hub, _request_stop)
    config = uvicorn.Config(app, log_level="warning", access_log=False, loop="asyncio")
    server = uvicorn.Server(config)
    server_box["server"] = server

    # Handshake: announce the port on stdout ONLY ONCE uvicorn is actually
    # accepting connections (server.started flips True after it listens on our
    # pre-bound socket). Printing before that races the client to a not-yet-
    # listening socket → ECONNREFUSED. Anything else on stdout would corrupt it.
    def _announce() -> None:
        while not getattr(server, "started", False):
            time.sleep(0.005)
        print(f"VC_RPC_PORT {port}", flush=True)
        _log(f"ready (pid={os.getpid()}, port={port}, repo={_REPO})")

    threading.Thread(target=_announce, name="rpc-announce", daemon=True).start()

    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        _log("shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
