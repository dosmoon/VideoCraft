"""Material-domain RPC methods (migration doc §2.2, Material domain).

Read-only bindings over the MaterialInstanceModel protocol, resolved through
the material registry's instance_factory (Session caches the model so its
subscribe() callbacks survive across calls). Base layer never hard-codes a
plugin name — the type string drives the factory lookup (ADR-0004).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from ..protocol import RpcError
from ..registry import Context, rpc_method


def _jsonable(value: Any) -> Any:
    """Best-effort serialize a model return value for the wire.

    Dataclasses (e.g. SlotState) → dict; Paths/anything-with-__fspath__ → str;
    dicts/lists recurse. Keeps the binding decoupled from each model's exact
    field set (no per-plugin serializer here)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__fspath__"):  # Path-like
        return str(value)
    return str(value)


@rpc_method("material.slot_readiness")
def slot_readiness(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """Per-slot readiness for one material instance (drives sidebar tree)."""
    model = ctx.session.material_model(type, instance)
    return _jsonable(model.slot_readiness())


@rpc_method("material.get_artifact")
def get_artifact(ctx: Context, type: str, instance: str, key: str) -> str | None:
    """Resolve an artifact key to an absolute file path, or null if absent.

    The renderer reads the file directly (e.g. via vc-media://); the path
    namespace is the model's stable contract (source / context / subtitle:<lang>
    / analysis:<lang>:<kind>)."""
    model = ctx.session.material_model(type, instance)
    path = model.get_artifact(key)
    return str(path) if path is not None else None


# ── News context (15-field SourceContext) + basic_info seed (5 fields) ────────
# The model owns the dataclass conversion (write_*_dict); this layer stays free
# of plugin-specific imports (ADR-0004) and just shuttles dicts.

def _changed(ctx: Context, type: str, instance: str) -> None:
    ctx.notify("event.material.changed", {"type": type, "instance": instance})


@rpc_method("material.read_context")
def read_context(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """The 15-field news context as a dict (all fields present, empty if unfilled)."""
    return ctx.session.material_model(type, instance).read_context().to_dict()


@rpc_method("material.write_context")
def write_context(ctx: Context, type: str, instance: str, context: dict[str, Any]) -> dict[str, Any]:
    """Persist the whole 15-field context.json; broadcast. Unknown keys ignored."""
    if not isinstance(context, dict):
        raise RpcError(-32602, "context must be an object")
    stored = ctx.session.material_model(type, instance).write_context_dict(context)
    _changed(ctx, type, instance)
    return stored


@rpc_method("material.read_basic_info")
def read_basic_info(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """The 5-field basic_info hint seed (input-only for AI fill)."""
    return ctx.session.material_model(type, instance).read_basic_info().to_dict()


@rpc_method("material.write_basic_info")
def write_basic_info(ctx: Context, type: str, instance: str, basic_info: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(basic_info, dict):
        raise RpcError(-32602, "basic_info must be an object")
    stored = ctx.session.material_model(type, instance).write_basic_info_dict(basic_info)
    _changed(ctx, type, instance)
    return stored


@rpc_method("material.context_completion")
def context_completion(ctx: Context, type: str, instance: str) -> dict[str, int]:
    """(filled, total) field counts — drives the context-tab progress badge."""
    filled, total = ctx.session.material_model(type, instance).context_completion()
    return {"filled": filled, "total": total}


@rpc_method("material.source_meta")
def source_meta(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """The Source descriptor + probe values (origin/url/title/duration/w/h) for
    the Source tab. Survives independent of the file's presence."""
    return _jsonable(ctx.session.material_model(type, instance).get_source_meta())


# ── Subtitles + analyses (read) ──────────────────────────────────────────────

@rpc_method("material.list_subtitle_languages")
def list_subtitle_languages(ctx: Context, type: str, instance: str) -> list[str]:
    return ctx.session.material_model(type, instance).list_subtitle_languages()


@rpc_method("material.list_analyses")
def list_analyses(ctx: Context, type: str, instance: str) -> list[str]:
    """Filenames of `<lang>.analysis.json` artifacts on disk for this instance."""
    return ctx.session.material_model(type, instance).list_analyses()


@rpc_method("material.analysis_summary")
def analysis_summary(ctx: Context, type: str, instance: str, filename: str) -> dict[str, Any]:
    """Pre-read summary of one analysis.json (chapter/title counts, time range)."""
    return _jsonable(ctx.session.material_model(type, instance).analysis_summary(filename))


@rpc_method("material.read_analysis")
def read_analysis(ctx: Context, type: str, instance: str, filename: str) -> dict[str, Any]:
    """The raw analysis.json envelope (the chapter editor's source of truth)."""
    try:
        return ctx.session.material_model(type, instance).read_analysis(filename)
    except (OSError, ValueError) as exc:
        raise RpcError(-32602, f"cannot read analysis {filename!r}: {exc}") from exc


@rpc_method("material.read_subtitle")
def read_subtitle(ctx: Context, type: str, instance: str, lang: str) -> dict[str, Any]:
    """The raw SRT text of subtitles/<lang>.srt (for the in-tab viewer)."""
    import os

    model = ctx.session.material_model(type, instance)
    path = model.subtitle_path(lang)
    if not os.path.isfile(path):
        raise RpcError(-32602, f"no subtitle for language {lang!r}")
    with open(path, encoding="utf-8") as f:
        return {"text": f.read()}


@rpc_method("material.check_subtitle")
def check_subtitle(ctx: Context, type: str, instance: str, lang: str) -> dict[str, Any]:
    """Run the quality check on a subtitle (structural + residue + language
    purity). Returns issue counts by class + the issue list. The reference is the
    project source language (cue-count parity check)."""
    model = ctx.session.material_model(type, instance)
    result = model.check_subtitle(lang, reference_lang_iso=model.source_language())
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


@rpc_method("material.quick_fix_subtitle")
def quick_fix_subtitle(ctx: Context, type: str, instance: str, lang: str) -> dict[str, Any]:
    """Apply the in-place auto-fixes (format-residue cleanup) to a subtitle, then
    re-check and return the fresh counts/issues."""
    model = ctx.session.material_model(type, instance)
    model.quick_fix_subtitle(lang)
    _changed(ctx, type, instance)
    return check_subtitle(ctx, type, instance, lang)


@rpc_method("material.import_subtitle")
def import_subtitle(ctx: Context, type: str, instance: str, path: str, lang: str) -> dict[str, Any]:
    """Copy an external SRT into subtitles/<lang>.srt (first import sets the
    project source language). `path` is an absolute disk path the user picked."""
    if not lang:
        raise RpcError(-32602, "lang is required")
    model = ctx.session.material_model(type, instance)
    try:
        model.import_subtitle(path, lang)
    except OSError as exc:
        raise RpcError(-32602, f"cannot import subtitle: {exc}") from exc
    _changed(ctx, type, instance)
    return {"lang": lang}


@rpc_method("material.list_analysis_artifacts")
def list_analysis_artifacts(ctx: Context, type: str, instance: str, lang: str) -> list[dict[str, Any]]:
    """Existing analysis artifacts for one language across all kinds (analysis /
    transcript / chapter_transcript / hotclips), in registry order."""
    model = ctx.session.material_model(type, instance)
    out: list[dict[str, Any]] = []
    for a in model.list_analysis_artifacts(lang):
        out.append({
            "kind": a.type.kind,
            "format": a.type.format,
            "icon": a.type.icon,
            "display_zh": a.type.display_zh,
            "size_bytes": a.size_bytes,
        })
    return out


@rpc_method("material.read_analysis_text")
def read_analysis_text(ctx: Context, type: str, instance: str, lang: str, kind: str) -> dict[str, Any]:
    """Raw text of one analysis artifact (markdown / JSON) for the viewer. The
    `analysis` (chapters) kind is edited via read_analysis/save_chapters instead."""
    import os

    model = ctx.session.material_model(type, instance)
    try:
        path = model.analysis_path(lang, kind)
    except ValueError as exc:
        raise RpcError(-32602, str(exc)) from exc
    if not os.path.isfile(path):
        raise RpcError(-32602, f"analysis artifact missing: {lang}.{kind}")
    with open(path, encoding="utf-8") as f:
        return {"text": f.read()}


@rpc_method("material.save_chapters")
def save_chapters(
    ctx: Context, type: str, instance: str, filename: str, chapters: list[Any], lang: str
) -> dict[str, Any]:
    """Re-save an analysis.json after the user edited the chapter schedule.
    Server normalizes (sort / end=next.start / drop degenerate / synth 00:00) via
    chapters_io and preserves titles[]; returns the normalized envelope."""
    if not isinstance(chapters, list):
        raise RpcError(-32602, "chapters must be a list")
    import os

    from core import chapters_io
    from core.subtitle_ops import srt_end_seconds

    model = ctx.session.material_model(type, instance)
    path = os.path.join(model.subtitles_dir, filename)
    srt_end = srt_end_seconds(model.subtitle_path(lang))
    try:
        env = chapters_io.save_analysis_chapters_only(
            path, chapters, srt_end_sec=srt_end, lang_iso=lang,
            source_subtitle=f"{lang}.srt",
        )
    except (OSError, ValueError) as exc:
        raise RpcError(-32602, f"cannot save chapters: {exc}") from exc
    _changed(ctx, type, instance)
    return env


# ── Long-running jobs (sidecar threads) ──────────────────────────────────────
# Each returns {job_id} immediately; the worker emits progress.<kind> ticks and a
# terminal event.job. Successful workers also emit event.material.changed so the
# sidebar + sibling tabs re-read. The model is the single owner — it mutates the
# instance on disk (and project.meta for source).


@rpc_method("material.set_source")
def set_source(ctx: Context, type: str, instance: str, source: dict[str, Any]) -> dict[str, Any]:
    """Acquire the source video (local import OR yt-dlp download) as a long job.
    `source` = {origin:'link'|'local', url?, imported_from?, clip_range?{start,end}}
    with HH:MM:SS time strings. On success, commit_source stamps the descriptor +
    probe values. AcquireError is surfaced with its category prefixed so the tab
    can show a recovery hint."""
    if not isinstance(source, dict):
        raise RpcError(-32602, "source must be an object")
    from core.project_schema import Source

    model = ctx.session.material_model(type, instance)
    src = Source.from_dict(source)

    def work(job: Any) -> Any:
        from core import source_acquire

        from ._jobs_util import AcquireCancelBridge, acquire_progress_to_job

        try:
            result = source_acquire.acquire(
                src, model.source_video_path, model.source_meta_path,
                progress_cb=acquire_progress_to_job(job),
                cancel_token=AcquireCancelBridge(job),
            )
        except source_acquire.AcquireError as exc:
            if exc.category == source_acquire.ERR_CANCELLED or job.cancelled:
                return None  # runner marks the job cancelled
            # Prefix the category so the renderer can branch on it.
            raise RuntimeError(f"{exc.category}: {exc.message}") from exc
        model.commit_source(
            src, title=result.title, duration_sec=result.duration_sec,
            width=result.width, height=result.height,
        )
        ctx.notify("event.material.changed", {"type": type, "instance": instance})
        return {
            "title": result.title,
            "duration_sec": result.duration_sec,
            "width": result.width,
            "height": result.height,
        }

    return {"job_id": ctx.jobs.start("material.source", work)}


@rpc_method("material.run_asr")
def run_asr(ctx: Context, type: str, instance: str, source_lang: str | None = None) -> dict[str, Any]:
    """Transcribe the source video → subtitles/<lang>.srt (long job). source_lang
    None = auto-detect. NB: project-level pipeline (one source per project)."""
    model = ctx.session.material_model(type, instance)

    def work(job: Any) -> Any:
        from ._jobs_util import AiCancelBridge, pipeline_progress_to_job

        result = model.run_asr(
            source_lang_iso=source_lang,
            progress_cb=pipeline_progress_to_job(job),
            cancel_token=AiCancelBridge(job),
        )
        ctx.notify("event.material.changed", {"type": type, "instance": instance})
        return result

    return {"job_id": ctx.jobs.start("material.asr", work)}


@rpc_method("material.run_translate")
def run_translate(ctx: Context, type: str, instance: str, target_lang: str) -> dict[str, Any]:
    """Translate the source SRT → subtitles/<target_lang>.srt (long job)."""
    if not target_lang:
        raise RpcError(-32602, "target_lang is required")
    model = ctx.session.material_model(type, instance)

    def work(job: Any) -> Any:
        from ._jobs_util import AiCancelBridge, pipeline_progress_to_job

        result = model.run_translate(
            target_lang_iso=target_lang,
            progress_cb=pipeline_progress_to_job(job),
            cancel_token=AiCancelBridge(job),
        )
        ctx.notify("event.material.changed", {"type": type, "instance": instance})
        return result

    return {"job_id": ctx.jobs.start("material.translate", work)}


@rpc_method("material.run_analysis")
def run_analysis(
    ctx: Context, type: str, instance: str, lang: str, analysis_kind: str
) -> dict[str, Any]:
    """Run an AI analysis over a subtitle → subtitles/<lang>.<suffix> (long job).
    `analysis_kind` is one of core.subtitle_analysis kinds (analysis / transcript
    / chapter_transcript / hotclips); chapters live in the `analysis` kind."""
    model = ctx.session.material_model(type, instance)

    def work(job: Any) -> Any:
        from ._jobs_util import AiCancelBridge, pipeline_progress_to_job

        result = model.run_analysis(
            analysis_kind, lang,
            progress_cb=pipeline_progress_to_job(job),
            cancel_token=AiCancelBridge(job),
        )
        ctx.notify("event.material.changed", {"type": type, "instance": instance})
        return result

    return {"job_id": ctx.jobs.start("material.analysis", work)}


@rpc_method("material.ai_fill_context")
def ai_fill_context(ctx: Context, type: str, instance: str) -> dict[str, Any]:
    """Run AI extraction to fill the 15-field context (long job, replacement
    semantics). No progress_cb — ai_fill.extract is a single AI call (and does not
    accept one); progress is indeterminate. Returns the new context dict."""
    model = ctx.session.material_model(type, instance)

    def work(job: Any) -> Any:
        from ._jobs_util import AiCancelBridge

        new_ctx = model.ai_fill_context(cancel_token=AiCancelBridge(job))
        ctx.notify("event.material.changed", {"type": type, "instance": instance})
        return new_ctx.to_dict()

    return {"job_id": ctx.jobs.start("material.ai_fill", work)}
