"""System / diagnostic RPC methods.

Transport-level smoke tests plus a tiny job demo that exercises the long-task
path (progress notifications + terminal event) without touching any heavy core
code — handy for verifying the channel end-to-end from the renderer.
"""

from __future__ import annotations

import time
from typing import Any

from ..registry import Context, rpc_method

# Kept in lockstep with the protocol version the renderer client expects.
SIDECAR_PROTOCOL = 1


@rpc_method("system.ping")
def ping(ctx: Context) -> dict[str, Any]:
    """Liveness + handshake. Returns the protocol version and whether a project
    is currently open (so the client can decide whether to prompt for one)."""
    return {
        "ok": True,
        "protocol": SIDECAR_PROTOCOL,
        "has_project": ctx.session.has_project(),
    }


@rpc_method("system.echo")
def echo(ctx: Context, **params: Any) -> dict[str, Any]:
    """Round-trips its params. Pure transport check (framing + encoding)."""
    return params


@rpc_method("system.get_locale")
def get_locale(ctx: Context) -> dict[str, str]:
    """The UI language the renderer should render in — read from the same
    user_data/settings.json the Tk app uses (i18n.get_current_lang), so both
    front-ends stay in lockstep. The renderer awaits this at boot before its
    first render and sets its tr() singleton accordingly."""
    from i18n import get_current_lang

    return {"lang": get_current_lang()}


@rpc_method("system.set_locale")
def set_locale(ctx: Context, lang: str) -> dict[str, str]:
    """Persist the UI language to the shared user_data/settings.json (the same
    knob the Tk app's Preferences writes). The renderer switches hot on its own;
    this just makes the choice survive restart and keeps both front-ends in sync.
    Rejects an unsupported code (→ HANDLER_ERROR)."""
    from i18n import get_current_lang, set_current_lang

    set_current_lang(lang)  # validates; raises ValueError on unsupported code
    return {"lang": get_current_lang()}


@rpc_method("system.list_languages")
def list_languages(ctx: Context) -> list[dict[str, str]]:
    """The known-language catalog for the ASR / translate / import pickers
    (core.lang_names.WHISPER_LANG_CHOICES): UN-6 first then alphabetical, with a
    locale-agnostic `iso — English (中文)` display. The renderer's combobox filters
    these so manual typing snaps to a preset code (display → iso)."""
    from core.lang_names import WHISPER_LANG_CHOICES

    return [{"iso": iso, "display": display} for iso, display in WHISPER_LANG_CHOICES]


@rpc_method("system.demo_job")
def demo_job(ctx: Context, steps: int = 5, delay_ms: int = 50) -> dict[str, Any]:
    """Start a fake long task that emits `progress.demo` then `event.job`.

    Returns {job_id} immediately. Used to verify the job/progress/cancel path
    independent of ASR/render. `delay_ms` is small by default so it's cheap.
    """
    n = max(1, int(steps))
    pause = max(0, int(delay_ms)) / 1000.0

    def work(job: Any) -> dict[str, Any]:
        for i in range(1, n + 1):
            if job.cancelled:
                break
            if pause:
                time.sleep(pause)
            job.progress(done=i, total=n, pct=round(i / n, 3))
        return {"steps": n}

    job_id = ctx.jobs.start("demo", work)
    return {"job_id": job_id}


@rpc_method("job.cancel")
def cancel_job(ctx: Context, job_id: str) -> dict[str, Any]:
    """Signal cancellation of a running job. {cancelled: false} if already gone."""
    return {"cancelled": ctx.jobs.cancel(job_id)}


@rpc_method("job.active")
def active_jobs(ctx: Context) -> dict[str, Any]:
    return {"job_ids": ctx.jobs.active_ids()}
