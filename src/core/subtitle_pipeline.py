"""Project-level subtitle pipeline (P4.4).

Two operations that always read from / write to a project's canonical
locations (no manual file picking, no merged "bilingual.srt"):

  run_asr(project, source_lang=...) → subtitles/<src>.srt
      Calls core.asr.transcribe_audio on _nv_paths.source_video_path(project),
      writes the result into _nv_paths.subtitles_dir(project)/<lang>.srt, and
      updates project.meta.language.source.

  run_translate(project, target_lang=...) → subtitles/<target>.srt
      Translates from the source SRT (named after meta.language.source)
      into <target>.srt, and adds target_lang to
      project.meta.language.translated_to.

Both honor a CancellationToken (core.ai) and report progress through a
unified ProgressInfo callback. Per the design discussion: each language
is an independent file; no merged bilingual format.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Callable, Optional

from core.ai.cancellation import CancellationToken
from materials.news_video import paths as _nv_paths


@dataclass
class ProgressInfo:
    """One progress tick — unified across ASR and translate."""
    phase: str                       # "transcribing" | "translating" | "preparing"
    percent: float | None            # 0..100, or None if indeterminate
    status_text: str | None = None   # free-form status line


ProgressCb = Optional[Callable[[ProgressInfo], None]]


# ── ASR ──────────────────────────────────────────────────────────────────────

def run_asr(
    project,
    *,
    source_lang_iso: str | None = None,
    provider: str | None = None,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict:
    """Transcribe _nv_paths.source_video_path(project) → subtitles/<lang>.srt.

    Args:
        project: a Project instance (must have source_status() == "ready").
        source_lang_iso: ISO code ("en", "zh", ...) or None for auto-detect.
        provider: optional ASR provider override. None = AI Console routing.

    Returns:
        {
          "lang_iso": detected/expected ISO code,
          "srt_path": absolute path of the written SRT,
          "segment_count": int,
        }

    Raises:
        FileNotFoundError if source video missing.
        AIError on provider failure (including CANCELLED).
    """
    from core import asr as core_asr

    if _nv_paths.source_status(project) != "ready":
        raise FileNotFoundError(
            f"Source video missing at {_nv_paths.source_video_path(project)}"
        )

    os.makedirs(_nv_paths.subtitles_dir(project), exist_ok=True)

    # Provisional output name; transcribe_audio may rewrite the suffix
    # when the detected language differs from what was requested.
    provisional_lang = source_lang_iso or "auto"
    output_srt_path = os.path.join(
        _nv_paths.subtitles_dir(project), f"{provisional_lang}.srt"
    )

    _emit(progress_cb, ProgressInfo(
        phase="preparing", percent=None,
        status_text="正在准备 ASR...",
    ))

    def _on_event(event_type: str, **kwargs):
        """Translate any provider event into a ProgressInfo update.

        Different ASR providers emit different event names:
          Lemonfox/OpenAI Whisper:  state_uploading, state_waiting_*
          faster-whisper (local):   request_summary_local, state_processing,
                                    state_perf_breakdown, state_done
          aistack:                  request_summary, state_processing,
                                    state_done, retry_slot_busy, stream_warning

        We map the well-known ones to specific status text and fall back
        to a generic "正在转写..." for everything else so the modal
        always shows progress instead of getting stuck at "准备中".
        """
        # Cloud upload phase (Lemonfox / Whisper API)
        if event_type == "state_uploading":
            pct = float(kwargs.get("percent") or 0.0)
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=pct,
                status_text=f"正在上传音频 {pct:.0f}%",
            ))
            return
        # Cloud waiting on remote inference
        if event_type == "state_waiting_start":
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text="服务器正在处理...",
            ))
            return
        if event_type == "state_waiting_tick":
            elapsed = kwargs.get("elapsed", 0)
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text=f"服务器处理中 {int(elapsed)}s...",
            ))
            return
        # Local / aistack streaming progress
        if event_type == "state_processing":
            seg = kwargs.get("segment_count", 0)
            elapsed = kwargs.get("elapsed", 0)
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text=f"已转写 {seg} 段 · {int(elapsed)}s",
            ))
            return
        # Provider startup / request summary — show we're past "准备中"
        if event_type in ("request_summary", "request_summary_local"):
            provider_hint = (
                kwargs.get("device")
                or kwargs.get("provider")
                or kwargs.get("backend")
                or ""
            )
            txt = "正在调用 ASR"
            if provider_hint:
                txt += f" · {provider_hint}"
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text=txt,
            ))
            return
        # Final tick
        if event_type == "state_done":
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=100.0,
                status_text="转写完成,正在写出 SRT...",
            ))
            return
        # Retries (network or busy-server)
        if event_type.startswith("retry_"):
            wait = kwargs.get("wait", 0)
            reason = event_type.removeprefix("retry_").replace("_", " ")
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text=f"重试中 ({reason}),{int(wait)}s 后再试...",
            ))
            return
        # Fallback: anything we don't recognize still bumps the status
        # so the user knows work is happening.
        _emit(progress_cb, ProgressInfo(
            phase="transcribing", percent=None,
            status_text=f"ASR 进行中 ({event_type})...",
        ))

    result = core_asr.transcribe_audio(
        _nv_paths.source_video_path(project),
        output_srt_path,
        expected_lang_iso=source_lang_iso,
        language=source_lang_iso,
        translate=False,            # never use Whisper translate-to-en mode
        provider=provider,
        on_event=_on_event,
        cancel_token=cancel_token,
    )

    # core.asr writes the SRT via _apply_lang_suffix, which appends `_<iso>.srt`
    # rather than replacing the basename. We always rename to canonical
    # `<iso>.srt` form (single file per language, simpler sidebar matching).
    raw_srt = result["srt_path"]
    raw_json = result.get("json_path")
    final_lang = result.get("detected_lang_iso") or source_lang_iso

    final_path = raw_srt
    if final_lang:
        canonical_srt = os.path.join(_nv_paths.subtitles_dir(project), f"{final_lang}.srt")
        if os.path.abspath(raw_srt) != os.path.abspath(canonical_srt):
            try:
                if os.path.exists(canonical_srt):
                    os.remove(canonical_srt)
                os.rename(raw_srt, canonical_srt)
                final_path = canonical_srt
            except OSError:
                # Keep the ugly name on rename failure — file still works
                # for downstream consumers that read by suffix scan.
                pass
        # Same rename for the sibling JSON.
        if raw_json and os.path.isfile(raw_json):
            canonical_json = os.path.join(
                _nv_paths.subtitles_dir(project), f"{final_lang}.json")
            if os.path.abspath(raw_json) != os.path.abspath(canonical_json):
                try:
                    if os.path.exists(canonical_json):
                        os.remove(canonical_json)
                    os.rename(raw_json, canonical_json)
                except OSError:
                    pass

    # Update project meta language.source.
    meta = project.meta
    if final_lang:
        meta.language.source = final_lang
    project.update_meta(meta)

    _emit(progress_cb, ProgressInfo(
        phase="transcribing", percent=100.0,
        status_text=f"完成: {os.path.basename(final_path)}",
    ))

    return {
        "lang_iso": final_lang,
        "srt_path": final_path,
        "segment_count": result.get("segment_count", 0),
    }


# ── Translate ────────────────────────────────────────────────────────────────

def run_translate(
    project,
    *,
    target_lang_iso: str,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict:
    """Translate the project's source-language SRT into <target>.srt.

    Args:
        project: Project with project.meta.language.source set and an
                 existing <source>.srt in subtitles/.
        target_lang_iso: ISO code of the desired output language.

    Returns:
        {
          "lang_iso": target_lang_iso,
          "srt_path": absolute path to the written SRT,
        }

    Raises:
        FileNotFoundError if the source SRT is absent.
        ValueError if project.meta.language.source is unset.
        AIError on provider failure (including CANCELLED).
    """
    from core import translate as core_translate

    src_lang = project.meta.language.source
    if not src_lang:
        raise ValueError("project.meta.language.source is unset; run ASR first")

    src_path = os.path.join(_nv_paths.subtitles_dir(project), f"{src_lang}.srt")
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"Source SRT missing: {src_path}")

    if target_lang_iso == src_lang:
        raise ValueError(
            f"目标语言 {target_lang_iso} 与源语言相同,无需翻译"
        )

    # core.translate writes alongside the source SRT using a name derived
    # from target_lang's English name. We capture its return path and
    # rename to our canonical `<iso>.srt` form.
    _emit(progress_cb, ProgressInfo(
        phase="preparing", percent=None,
        status_text=f"正在准备翻译 ({src_lang} → {target_lang_iso})...",
    ))

    def _on_progress(done: int, total: int, msg: str):
        pct = (100.0 * done / total) if total else None
        _emit(progress_cb, ProgressInfo(
            phase="translating", percent=pct,
            status_text=msg,
        ))

    written_path = core_translate.translate_srt_file(
        src_path,
        source_lang=src_lang,
        target_lang=target_lang_iso,
        progress_cb=_on_progress,
        cancel_token=cancel_token,
    )

    # Normalize the output name to <iso>.srt next to the source. core.translate
    # names it after target language's English name; we want ISO consistency.
    final_path = os.path.join(_nv_paths.subtitles_dir(project), f"{target_lang_iso}.srt")
    if os.path.abspath(written_path) != os.path.abspath(final_path):
        try:
            if os.path.exists(final_path):
                os.remove(final_path)
            shutil.move(written_path, final_path)
        except OSError:
            # If rename fails, accept whatever core.translate wrote.
            final_path = written_path

    # Update project meta.language.translated_to.
    meta = project.meta
    if target_lang_iso not in meta.language.translated_to:
        meta.language.translated_to = list(meta.language.translated_to) + [target_lang_iso]
    project.update_meta(meta)

    _emit(progress_cb, ProgressInfo(
        phase="translating", percent=100.0,
        status_text=f"完成: {os.path.basename(final_path)}",
    ))

    return {
        "lang_iso": target_lang_iso,
        "srt_path": final_path,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _emit(cb: ProgressCb, info: ProgressInfo) -> None:
    if cb is not None:
        try:
            cb(info)
        except Exception:
            pass  # UI callback errors must not derail the pipeline
