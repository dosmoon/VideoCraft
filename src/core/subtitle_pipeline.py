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

# ADR-0005/0008 note: the path-based core below (run_asr_paths / run_translate_paths)
# is plugin-free — callers inject source_video_path / subtitles_dir and update
# project.meta themselves. The legacy (project) shims at the bottom still resolve
# paths via materials.news_video.paths (lazy import inside the shim, NOT at module
# scope) and stamp project.meta; they survive only until the Tk app + NewsVideoModel
# retire. Keeping the import shim-local is what removes the top-level cross-plugin
# dependency that the old TODO(ADR-0005) flagged.


@dataclass
class ProgressInfo:
    """One progress tick — unified across ASR and translate."""
    phase: str                       # "transcribing" | "translating" | "preparing"
    percent: float | None            # 0..100, or None if indeterminate
    status_text: str | None = None   # free-form status line


ProgressCb = Optional[Callable[[ProgressInfo], None]]


# ── ASR ──────────────────────────────────────────────────────────────────────

def run_asr_paths(
    *,
    source_video_path: str,
    subtitles_dir: str,
    source_lang_iso: str | None = None,
    provider: str | None = None,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict:
    """Transcribe `source_video_path` → `subtitles_dir`/<lang>.srt. Plugin-free:
    the caller injects the resolved paths and is responsible for updating
    project.meta.language.source from the returned `lang_iso`.

    Args:
        source_video_path: absolute path to the source video (must be a
            non-empty file).
        subtitles_dir: absolute directory the SRT is written into.
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

    if not (os.path.isfile(source_video_path) and os.path.getsize(source_video_path) > 0):
        raise FileNotFoundError(f"Source video missing at {source_video_path}")

    os.makedirs(subtitles_dir, exist_ok=True)

    # Provisional output name; transcribe_audio may rewrite the suffix
    # when the detected language differs from what was requested.
    provisional_lang = source_lang_iso or "auto"
    output_srt_path = os.path.join(subtitles_dir, f"{provisional_lang}.srt")

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
        # Local model loaded; the silent whole-file decode is about to start.
        if event_type == "model_loaded":
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text="模型已加载,正在解码音频...",
            ))
            return
        # First generator pull = whole-file decode + VAD (longest silent step on
        # big files). Tell the user so they don't think it stalled and cancel.
        if event_type == "state_decoding":
            _emit(progress_cb, ProgressInfo(
                phase="transcribing", percent=None,
                status_text="正在解码音频并转写(长视频首段较久,请耐心等待)...",
            ))
            return
        # Provider startup / request summary — show we're past "准备中". For the
        # local model this is the gateway to a single blocking model-load call
        # (cold CUDA init can take 30s–2min, no sub-progress), so say so — the bare
        # "calling ASR" made users think it stalled and cancel during load.
        if event_type in ("request_summary", "request_summary_local"):
            provider_hint = (
                kwargs.get("device")
                or kwargs.get("provider")
                or kwargs.get("backend")
                or ""
            )
            if event_type == "request_summary_local":
                txt = "正在加载本地模型(首次较慢,请耐心等待)"
            else:
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
        source_video_path,
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
        canonical_srt = os.path.join(subtitles_dir, f"{final_lang}.srt")
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
            canonical_json = os.path.join(subtitles_dir, f"{final_lang}.json")
            if os.path.abspath(raw_json) != os.path.abspath(canonical_json):
                try:
                    if os.path.exists(canonical_json):
                        os.remove(canonical_json)
                    os.rename(raw_json, canonical_json)
                except OSError:
                    pass

    _emit(progress_cb, ProgressInfo(
        phase="transcribing", percent=100.0,
        status_text=f"完成: {os.path.basename(final_path)}",
    ))

    return {
        "lang_iso": final_lang,
        "srt_path": final_path,
        "segment_count": result.get("segment_count", 0),
    }


def run_asr(
    project,
    *,
    source_lang_iso: str | None = None,
    provider: str | None = None,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict:
    """Legacy (project)-based shim over run_asr_paths (transitional — kept until
    the Tk app + NewsVideoModel retire). Resolves the news_video instance paths
    and stamps project.meta.language.source from the ASR result."""
    from materials.news_video import paths as _nv_paths

    result = run_asr_paths(
        source_video_path=_nv_paths.source_video_path(project),
        subtitles_dir=_nv_paths.subtitles_dir(project),
        source_lang_iso=source_lang_iso,
        provider=provider,
        progress_cb=progress_cb,
        cancel_token=cancel_token,
    )
    meta = project.meta
    if result["lang_iso"]:
        meta.language.source = result["lang_iso"]
    project.update_meta(meta)
    return result


# ── Translate ────────────────────────────────────────────────────────────────

def run_translate_paths(
    *,
    subtitles_dir: str,
    source_lang_iso: str,
    target_lang_iso: str,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict:
    """Translate `subtitles_dir`/<source>.srt → <target>.srt. Plugin-free: the
    caller injects the resolved subtitles dir + the source language, and is
    responsible for adding target_lang_iso to project.meta.language.translated_to.

    Args:
        subtitles_dir: absolute dir holding <source>.srt; output lands here too.
        source_lang_iso: ISO code of the existing source SRT (caller resolves it,
            e.g. from project.meta.language.source).
        target_lang_iso: ISO code of the desired output language.

    Returns:
        {"lang_iso": target_lang_iso, "srt_path": absolute path written}

    Raises:
        FileNotFoundError if the source SRT is absent.
        ValueError if source_lang_iso is empty or equals the target.
        AIError on provider failure (including CANCELLED).
    """
    from core import translate as core_translate

    src_lang = source_lang_iso
    if not src_lang:
        raise ValueError("source_lang_iso is unset; run ASR first")

    src_path = os.path.join(subtitles_dir, f"{src_lang}.srt")
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
    final_path = os.path.join(subtitles_dir, f"{target_lang_iso}.srt")
    if os.path.abspath(written_path) != os.path.abspath(final_path):
        try:
            if os.path.exists(final_path):
                os.remove(final_path)
            shutil.move(written_path, final_path)
        except OSError:
            # If rename fails, accept whatever core.translate wrote.
            final_path = written_path

    _emit(progress_cb, ProgressInfo(
        phase="translating", percent=100.0,
        status_text=f"完成: {os.path.basename(final_path)}",
    ))

    return {
        "lang_iso": target_lang_iso,
        "srt_path": final_path,
    }


def run_translate(
    project,
    *,
    target_lang_iso: str,
    progress_cb: ProgressCb = None,
    cancel_token: CancellationToken | None = None,
) -> dict:
    """Legacy (project)-based shim over run_translate_paths (transitional — kept
    until the Tk app + NewsVideoModel retire). Resolves the news_video instance
    paths + source language and stamps project.meta.language.translated_to."""
    from materials.news_video import paths as _nv_paths

    result = run_translate_paths(
        subtitles_dir=_nv_paths.subtitles_dir(project),
        source_lang_iso=project.meta.language.source,
        target_lang_iso=target_lang_iso,
        progress_cb=progress_cb,
        cancel_token=cancel_token,
    )
    meta = project.meta
    if target_lang_iso not in meta.language.translated_to:
        meta.language.translated_to = list(meta.language.translated_to) + [target_lang_iso]
    project.update_meta(meta)
    return result


# ── Helpers ──────────────────────────────────────────────────────────────────

def _emit(cb: ProgressCb, info: ProgressInfo) -> None:
    if cb is not None:
        try:
            cb(info)
        except Exception:
            pass  # UI callback errors must not derail the pipeline
