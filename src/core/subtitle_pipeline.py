"""Project-level subtitle pipeline (P4.4).

Two operations that always read from / write to a project's canonical
locations (no manual file picking, no merged "bilingual.srt"):

  run_asr(project, source_lang=...) → subtitles/<src>.srt
      Calls core.asr.transcribe_audio on project.source_video_path,
      writes the result into project.subtitles_dir/<lang>.srt, and
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
    """Transcribe project.source_video_path → subtitles/<lang>.srt.

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

    if project.source_status() != "ready":
        raise FileNotFoundError(
            f"Source video missing at {project.source_video_path}"
        )

    os.makedirs(project.subtitles_dir, exist_ok=True)

    # Provisional output name; transcribe_audio may rewrite the suffix
    # when the detected language differs from what was requested.
    provisional_lang = source_lang_iso or "auto"
    output_srt_path = os.path.join(
        project.subtitles_dir, f"{provisional_lang}.srt"
    )

    _emit(progress_cb, ProgressInfo(
        phase="preparing", percent=None,
        status_text="正在准备 ASR...",
    ))

    def _on_event(event_type: str, **kwargs):
        # Translate provider event types into ProgressInfo updates. We
        # don't have a clean total-percent for ASR (transcription itself
        # is server-side), so we mostly show phase + status text.
        if event_type == "state_uploading":
            pct = float(kwargs.get("percent") or 0.0)
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=pct,
                status_text=f"正在上传音频 {pct:.0f}%",
            ))
        elif event_type == "state_waiting_start":
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text="服务器正在处理...",
            ))
        elif event_type == "state_waiting_tick":
            elapsed = kwargs.get("elapsed", 0)
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text=f"服务器处理中 {int(elapsed)}s...",
            ))
        elif event_type in ("retry_connect_timeout", "retry_read_timeout",
                            "retry_connection_error"):
            wait = kwargs.get("wait", 0)
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text=f"网络异常,{int(wait)}s 后重试...",
            ))

    result = core_asr.transcribe_audio(
        project.source_video_path,
        output_srt_path,
        expected_lang_iso=source_lang_iso,
        language=source_lang_iso,
        translate=False,            # never use Whisper translate-to-en mode
        provider=provider,
        on_event=_on_event,
        cancel_token=cancel_token,
    )

    # core.asr writes the SRT to whatever final path it picked (may have
    # rewritten the language suffix when auto-detect resolved).
    final_path = result["srt_path"]
    final_lang = result.get("detected_lang_iso") or source_lang_iso

    # If the file is sitting under a suffix like `auto.srt` (no detection
    # info), rename it to a more useful basename. transcribe_audio handles
    # most of this, but guard against the auto+no-detect edge case.
    if final_lang and os.path.basename(final_path).startswith("auto."):
        nicer = os.path.join(project.subtitles_dir, f"{final_lang}.srt")
        try:
            if os.path.exists(nicer) and nicer != final_path:
                os.remove(nicer)
            os.rename(final_path, nicer)
            final_path = nicer
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

    src_path = os.path.join(project.subtitles_dir, f"{src_lang}.srt")
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
    final_path = os.path.join(project.subtitles_dir, f"{target_lang_iso}.srt")
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
