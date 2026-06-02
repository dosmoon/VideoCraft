"""Warm native C-extension imports on the MAIN thread (sidecar startup).

Confirmed deadlock: importing a native CUDA C-extension (ctranslate2, pulled in by
faster-whisper) for the FIRST time on a job *daemon thread* — while the sidecar's
main thread is blocked in `sys.stdin.buffer.read()` (its request loop) — hangs the
extension's initialization indefinitely. The model never loads, the ASR job never
finishes, and the UI sits forever on "loading model".

Reproduced minimally: daemon-thread `import faster_whisper` + main-thread
`stdin.read()` → hang; doing the import on the main thread first → 0.6s, no hang.

So the sidecar calls warm_native_extensions() on the main thread BEFORE entering
its stdin loop. Later jobs then hit already-initialized (cached) imports on their
daemon threads, so no first-time C-ext init races with the blocked main thread.

Only the import is warmed (not a model load) — that alone resolves the deadlock and
keeps startup cheap. Best-effort: optional deps absent on some setups are skipped.
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
