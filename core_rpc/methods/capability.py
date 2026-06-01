"""Capability gateway — plugin-agnostic, path-based jobs (ADR-0008 Phase B2).

The framework's generic capability surface: source acquisition, ASR, translation,
subtitle analysis, subtitle QC, chapter save, and generic structured-LLM
extraction. Unlike material.* (which resolves paths via a NewsVideoModel and knows
the news_video schema), these take ABSOLUTE paths the caller already resolved (TS
plugins via project.material_instance_dir + paths.ts) and carry ZERO plugin/domain
knowledge — no news_video import, no 15-field context schema. The news-context
prompt + schema live in the TS plugin and arrive through llm_extract's generic
{prompt, schema, task} (per the B2 design decision: capability stays generic).

Defense in depth: every path argument must resolve inside the open project (mirrors
the vc.fs main-process assertInProject) so a caller bug can't read/write outside it.

Long ops run as jobs (return {job_id}; emit progress.* + a terminal event.job) and
reuse the same cancel/progress bridges as material.*. They deliberately do NOT emit
domain change events (e.g. event.material.changed) — the capability layer doesn't
know it's serving a "material instance". The renderer refreshes on job completion.
"""

from __future__ import annotations

import os
from typing import Any

from ..protocol import RpcError
from ..registry import Context, rpc_method


# ── Path safety ───────────────────────────────────────────────────────────────

def _in_project(ctx: Context, *paths: str) -> list[str]:
    """Validate every path resolves inside the open project root and return the
    OS-normalized forms. Paths need not exist yet (outputs); only their location
    is checked. Normalizing matters on Windows: the TS layer sends mixed
    forward/back-slash paths (e.g. ``D:\\proj\\inst/source/video.mp4`` — instance
    dir from os.path.join + ``/source/...`` joined in JS), and handing those
    straight to ffmpeg / faster-whisper / yt-dlp can misbehave."""
    if not ctx.session.has_project():
        raise RpcError(-32002, "no project is open")
    root = os.path.abspath(ctx.session.project.folder)
    out: list[str] = []
    for p in paths:
        if not isinstance(p, str) or not p:
            raise RpcError(-32602, "path must be a non-empty string")
        ap = os.path.abspath(p)
        if ap != root and not ap.startswith(root + os.sep):
            raise RpcError(-32602, f"path escapes project: {p}")
        out.append(os.path.normpath(p))
    return out


def _check_to_dict(result: Any) -> dict[str, Any]:
    """Serialize a core.subtitle_check CheckResult (shared by check + quick_fix)."""
    return {
        "cue_count": result.cue_count,
        "hard": result.hard_count,
        "fixable": result.fixable_count,
        "advisory": result.advisory_count,
        "issues": [
            {
                "cue_index": i.cue_index,
                "category": i.category,
                "severity": i.severity,
                "severity_class": i.severity_class,
                "message": i.message,
                "auto_fixable": i.auto_fixable,
            }
            for i in result.issues
        ],
    }


# ── Source acquisition (long job) ─────────────────────────────────────────────

@rpc_method("capability.acquire_source")
def acquire_source(
    ctx: Context, source: dict[str, Any], video_path: str, meta_path: str | None = None
) -> dict[str, Any]:
    """Acquire a source video (local import OR yt-dlp download) into video_path,
    writing probe metadata to meta_path (long job). `source` = {origin:'link'|
    'local', url?, imported_from?, clip_range?{start,end}}. On failure the
    AcquireError category is prefixed so the caller can branch on it. Returns
    {title, duration_sec, width, height} (no project.meta stamping — the caller
    persists what it needs)."""
    if not isinstance(source, dict):
        raise RpcError(-32602, "source must be an object")
    if meta_path:
        video_path, meta_path = _in_project(ctx, video_path, meta_path)
    else:
        (video_path,) = _in_project(ctx, video_path)
    from core.project_schema import Source

    src = Source.from_dict(source)

    def work(job: Any) -> Any:
        from core import source_acquire
        from ._jobs_util import AcquireCancelBridge, acquire_progress_to_job

        try:
            result = source_acquire.acquire(
                src, video_path, meta_path,
                progress_cb=acquire_progress_to_job(job),
                cancel_token=AcquireCancelBridge(job),
            )
        except source_acquire.AcquireError as exc:
            if exc.category == source_acquire.ERR_CANCELLED or job.cancelled:
                return None
            raise RuntimeError(f"{exc.category}: {exc.message}") from exc
        return {
            "title": result.title,
            "duration_sec": result.duration_sec,
            "width": result.width,
            "height": result.height,
        }

    return {"job_id": ctx.jobs.start("capability.acquire_source", work)}


# ── ASR / translate (long jobs over the plugin-free pipeline) ─────────────────

@rpc_method("capability.asr")
def asr(
    ctx: Context, source_video_path: str, subtitles_dir: str, source_lang: str | None = None
) -> dict[str, Any]:
    """Transcribe source_video_path → subtitles_dir/<lang>.srt (long job).
    source_lang None = auto-detect. Returns {lang_iso, srt_path, segment_count};
    persisting the detected language to project meta is the caller's job."""
    source_video_path, subtitles_dir = _in_project(ctx, source_video_path, subtitles_dir)

    def work(job: Any) -> Any:
        from core import subtitle_pipeline
        from ._jobs_util import AiCancelBridge, pipeline_progress_to_job

        return subtitle_pipeline.run_asr_paths(
            source_video_path=source_video_path,
            subtitles_dir=subtitles_dir,
            source_lang_iso=source_lang,
            progress_cb=pipeline_progress_to_job(job),
            cancel_token=AiCancelBridge(job),
        )

    return {"job_id": ctx.jobs.start("capability.asr", work)}


@rpc_method("capability.translate")
def translate(
    ctx: Context, subtitles_dir: str, source_lang: str, target_lang: str
) -> dict[str, Any]:
    """Translate subtitles_dir/<source>.srt → <target>.srt (long job)."""
    if not source_lang or not target_lang:
        raise RpcError(-32602, "source_lang and target_lang are required")
    (subtitles_dir,) = _in_project(ctx, subtitles_dir)

    def work(job: Any) -> Any:
        from core import subtitle_pipeline
        from ._jobs_util import AiCancelBridge, pipeline_progress_to_job

        return subtitle_pipeline.run_translate_paths(
            subtitles_dir=subtitles_dir,
            source_lang_iso=source_lang,
            target_lang_iso=target_lang,
            progress_cb=pipeline_progress_to_job(job),
            cancel_token=AiCancelBridge(job),
        )

    return {"job_id": ctx.jobs.start("capability.translate", work)}


# ── Subtitle analysis (long job) ──────────────────────────────────────────────

@rpc_method("capability.analyze")
def analyze(
    ctx: Context, kind: str, srt_path: str, subtitles_dir: str, lang: str
) -> dict[str, Any]:
    """Run a registered analysis kind over a subtitle → subtitles_dir/<lang>.<suffix>
    (long job). `kind` is a core.subtitle_analysis kind (analysis / transcript /
    chapter_transcript / hotclips)."""
    srt_path, subtitles_dir = _in_project(ctx, srt_path, subtitles_dir)

    def work(job: Any) -> Any:
        from core import subtitle_analysis_runners
        from ._jobs_util import AiCancelBridge, pipeline_progress_to_job

        return subtitle_analysis_runners.run(
            kind, srt_path, subtitles_dir, lang,
            pipeline_progress_to_job(job), AiCancelBridge(job),
        )

    return {"job_id": ctx.jobs.start("capability.analyze", work)}


# ── Generic structured-LLM extraction (long job) ─────────────────────────────

@rpc_method("capability.llm_extract")
def llm_extract(
    ctx: Context, prompt: str, schema: dict[str, Any], task: str
) -> dict[str, Any]:
    """Generic JSON-schema-constrained LLM call (long job). The caller (a TS
    plugin) builds the full prompt + JSON schema + routing task — this stays
    plugin-agnostic and just runs ai.complete_json. Replaces the news-specific
    ai_fill: the 15-field news schema + prompt template live in the plugin, not
    here. Returns the raw extracted object (caller validates/persists)."""
    if not isinstance(prompt, str) or not prompt:
        raise RpcError(-32602, "prompt must be a non-empty string")
    if not isinstance(schema, dict):
        raise RpcError(-32602, "schema must be an object")
    if not task:
        raise RpcError(-32602, "task is required")

    def work(job: Any) -> Any:
        from core import ai
        from ._jobs_util import AiCancelBridge

        raw = ai.complete_json(prompt, schema=schema, task=task, cancel_token=AiCancelBridge(job))
        return raw if isinstance(raw, dict) else {}

    return {"job_id": ctx.jobs.start("capability.llm_extract", work)}


# ── Subtitle QC + chapter save (sync) ─────────────────────────────────────────

@rpc_method("capability.subtitle_check")
def subtitle_check(
    ctx: Context, srt_path: str, expected_lang: str | None = None, reference_srt_path: str | None = None
) -> dict[str, Any]:
    """Quality-check an SRT (structural + residue + language purity). Returns issue
    counts by class + the issue list. reference_srt_path enables cue-count parity."""
    if reference_srt_path:
        srt_path, reference_srt_path = _in_project(ctx, srt_path, reference_srt_path)
    else:
        (srt_path,) = _in_project(ctx, srt_path)
    from core.subtitle_check import check_srt

    result = check_srt(
        srt_path, expected_lang_iso=expected_lang,
        reference_srt_path=reference_srt_path if reference_srt_path else None,
    )
    return _check_to_dict(result)


@rpc_method("capability.subtitle_quick_fix")
def subtitle_quick_fix(ctx: Context, srt_path: str, expected_lang: str | None = None) -> dict[str, Any]:
    """Apply in-place auto-fixes (format-residue cleanup) to an SRT, then re-check
    and return the fresh counts/issues."""
    (srt_path,) = _in_project(ctx, srt_path)
    from core.subtitle_check import apply_auto_fixes, check_srt

    apply_auto_fixes(srt_path)
    return _check_to_dict(check_srt(srt_path, expected_lang_iso=expected_lang))


@rpc_method("capability.save_chapters")
def save_chapters(
    ctx: Context, analysis_path: str, chapters: list[Any], srt_path: str, lang: str
) -> dict[str, Any]:
    """Re-save an analysis.json after the user edited the chapter schedule. The
    server normalizes (sort / end=next.start / drop degenerate / synth 00:00) and
    preserves titles[]; returns the normalized envelope."""
    if not isinstance(chapters, list):
        raise RpcError(-32602, "chapters must be a list")
    analysis_path, srt_path = _in_project(ctx, analysis_path, srt_path)
    from core import chapters_io
    from core.subtitle_ops import srt_end_seconds

    try:
        return chapters_io.save_analysis_chapters_only(
            analysis_path, chapters,
            srt_end_sec=srt_end_seconds(srt_path), lang_iso=lang,
            source_subtitle=f"{lang}.srt",
        )
    except (OSError, ValueError) as exc:
        raise RpcError(-32602, f"cannot save chapters: {exc}") from exc
