"""Environment dashboard RPC (P1-d) — external dependency detection + install.

Wraps core.env (ffmpeg / ffprobe / Node / yt-dlp / SDKs …). Detection runs
version subprocesses and install shells out to pip / a Node download, so both go
through the job path (off the dispatch thread). `env.components` is the only sync
call — it's just the static registry metadata (the renderer's own i18n labels the
ids, so the Tk label_key is not forwarded).
"""

from __future__ import annotations

from typing import Any

from ..registry import Context, rpc_method


def _detect(component_id: str) -> dict[str, Any]:
    from core.env import detect_one

    r = detect_one(component_id)
    return {
        "id": component_id,
        "available": r.available,
        "version": r.version,
        "source": r.source,
        "path": r.path,
    }


@rpc_method("env.components")
def components(ctx: Context) -> list[dict[str, Any]]:
    """The visible component registry (metadata only — no detection)."""
    from core.env import list_components

    return [
        {
            "id": c.id,
            "category": c.category,
            "installable": c.install is not None,
            "info_url": c.info_url,
        }
        for c in list_components()
    ]


@rpc_method("env.detect_all")
def detect_all(ctx: Context) -> dict[str, Any]:
    """Detect every visible component (job — runs version subprocesses). Terminal
    event carries {results: [{id, available, version, source, path}, ...]}."""

    def work(job: Any) -> dict[str, Any]:
        from core.env import list_components

        out = []
        for c in list_components():
            out.append(_detect(c.id))
            job.progress(id=c.id)
        return {"results": out}

    return {"job_id": ctx.jobs.start("env.detect_all", work)}


@rpc_method("env.detect")
def detect(ctx: Context, component_id: str) -> dict[str, Any]:
    """Re-detect a single component (job). Used after an install completes."""

    def work(_job: Any) -> dict[str, Any]:
        return _detect(component_id)

    return {"job_id": ctx.jobs.start("env.detect", work)}


@rpc_method("env.install")
def install(ctx: Context, component_id: str) -> dict[str, Any]:
    """Install / upgrade a component (job — pip or Node download). Log lines stream
    as `progress.env.install` (field `line`); the terminal event carries the fresh
    detect result."""

    def work(job: Any) -> dict[str, Any]:
        from core.env import install_one

        install_one(component_id, lambda line: job.progress(line=line))
        return _detect(component_id)

    return {"job_id": ctx.jobs.start("env.install", work)}
