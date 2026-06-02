"""Sidecar stdio main loop.

Run as a module from the repo root so package-relative imports resolve and
src/ is importable:

    python -m core_rpc.server

Framing: newline-delimited JSON, read/written on the *binary* stdio buffers.
On Windows, text-mode stdout translates '\\n' → '\\r\\n', which would corrupt
the framing — so we never touch sys.stdout/stdin directly, only their .buffer.

Threading (migration doc §2.1 — the stdin-deadlock lesson):
  - main thread     : read one request line → dispatch (sync handlers) → enqueue
  - writer thread   : drain the outbound queue → write+flush (the ONLY writer)
  - job threads     : long tasks emit progress/terminal notifications via the
                      same queue, so all output is serialized through one writer
stdout is reserved exclusively for JSON-RPC; every log/traceback goes to stderr.
"""

from __future__ import annotations

import os
import sys

# ── sys.path bootstrap (must precede importing .methods, which pulls src/) ────
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import json  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402
from typing import Any, Optional  # noqa: E402

from .dispatch import dispatch_message  # noqa: E402
from .jobs import JobRegistry  # noqa: E402
from .registry import Context  # noqa: E402
from .session import Session  # noqa: E402

# Sentinel pushed onto the outbound queue to stop the writer thread.
_STOP = object()


def _log(*args: Any) -> None:
    """Diagnostics to stderr only — stdout is the JSON-RPC channel."""
    print("[core_rpc]", *args, file=sys.stderr, flush=True)


def _encode(msg: dict[str, Any]) -> bytes:
    """One compact JSON message + newline, UTF-8. Compact (no spaces/newlines
    inside) keeps each message on exactly one line for the reader."""
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


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

    outbound: "queue.Queue[Any]" = queue.Queue()
    out_buf = sys.stdout.buffer

    def writer() -> None:
        while True:
            item = outbound.get()
            if item is _STOP:
                return
            try:
                out_buf.write(_encode(item))
                out_buf.flush()
            except Exception as exc:  # noqa: BLE001 — a broken pipe ends the app
                _log("write failed:", exc)
                return

    writer_thread = threading.Thread(target=writer, name="rpc-writer", daemon=True)
    writer_thread.start()

    def emit(method: str, params: Optional[dict[str, Any]]) -> None:
        from . import protocol

        outbound.put(protocol.make_notification(method, params))

    session = Session()
    jobs = JobRegistry(emit)
    ctx = Context(session=session, emit=emit, jobs=jobs)

    # Warm native C-extension imports (ctranslate2/faster-whisper, llama_cpp) on
    # THIS main thread before the stdin loop below. Importing them first on a job
    # daemon thread while the main thread is blocked in sys.stdin.read() deadlocks
    # the C-ext init (confirmed minimal repro) — the ASR "loading model" hang.
    try:
        from core.ai.warmup import warm_native_extensions

        warm_native_extensions(_log)
    except Exception as exc:  # noqa: BLE001 — never let warm-up block startup
        _log("native warm-up error (non-fatal):", exc)

    _log(f"ready (pid={os.getpid()}, repo={_REPO})")

    # NB: the main thread blocks here in the stdin read between requests. That is
    # FINE only because warm_native_extensions() above already imported the native
    # CUDA C-extensions (ctranslate2/faster-whisper, llama_cpp) on this thread at
    # startup. If a job daemon thread is the FIRST to import one of those while ANY
    # thread is parked in a sys.stdin.buffer blocking read, the C-ext init deadlocks
    # (confirmed: the ASR "loading model" hang). Moving the stdin read to a worker
    # thread does NOT help — the trigger is the blocked stdin read itself, on any
    # thread, not the main thread specifically. So the warm-up above is the fix; any
    # new native-backed local engine must be added to warmup._NATIVE_MODULES.
    in_buf = sys.stdin.buffer
    try:
        for raw in in_buf:  # iterates line-by-line (split on b'\n')
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                # Can't recover an id from unparseable bytes → emit a generic
                # parse error with null id (JSON-RPC allows this).
                from . import protocol

                outbound.put(
                    protocol.make_error(None, protocol.PARSE_ERROR, f"parse error: {exc}")
                )
                continue
            response = dispatch_message(ctx, obj)
            if response is not None:
                outbound.put(response)
    except KeyboardInterrupt:
        pass
    finally:
        outbound.put(_STOP)
        writer_thread.join(timeout=2.0)
        _log("shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
