"""Warm native C-extension imports at sidecar startup — now a latency hint, not a
deadlock fix.

History: under the old stdio transport, the sidecar's main thread blocked forever in
`sys.stdin.buffer.read()` between requests. Importing a native CUDA C-extension
(ctranslate2 via faster-whisper, or llama_cpp) for the FIRST time on a job *daemon
thread* while that blocking read was parked hung the extension's init indefinitely —
the ASR "loading model" hang. The fix then was to import these on the main thread
before the stdin loop. But that only covered extras present at startup, so a runtime
install into py-extra (packaged base tier) reopened the hole.

ADR-0010 removed the root cause: the transport is now FastAPI/uvicorn (HTTP + SSE),
which has NO blocking stdin read anywhere, so a first-time native import on a worker
thread no longer deadlocks (aistack already runs ctranslate2 under uvicorn worker
threads fine). This warm-up is therefore no longer load-bearing — it is kept only as
a best-effort first-ASR latency optimization, run on a background thread at startup.
Absent extras (packaged base tier) are skipped; no checklist obligation remains.
"""

from __future__ import annotations

from typing import Callable, Optional

# Native C-extension modules that capability jobs import lazily on daemon threads.
# faster_whisper → ctranslate2 (the confirmed offender). llama_cpp is the other
# native CUDA backend (local LLM) and carries the same first-import risk.
_NATIVE_MODULES = ("faster_whisper", "llama_cpp")


def warm_native_extensions(log: Optional[Callable[[str], None]] = None) -> None:
    """Import the native C-extensions on the calling (main) thread, best-effort."""
    for mod in _NATIVE_MODULES:
        try:
            __import__(mod)
            if log:
                log(f"warmed native import: {mod}")
        except Exception as exc:  # noqa: BLE001 — optional dep / not installed: skip
            if log:
                log(f"native warm-up skipped for {mod}: {exc}")
