"""SenseVoice local ASR provider (Alibaba FunASR).

Runs SenseVoiceSmall locally — strong on Chinese (Mandarin + Cantonese),
also handles English / Japanese / Korean. Designed as the Asian-language
counterpart to Parakeet (which is European-only).

Output normalized to the same lemonfox verbose_json shape as Parakeet /
faster-whisper:
    {language, duration, text, segments[], words[]}

SenseVoice is non-autoregressive and does not produce word-level
timestamps natively. We get segment-level timestamps via FunASR's VAD +
SenseVoice pipeline (fsmn-vad chunks audio first, SenseVoice transcribes
each chunk). `words[]` is intentionally returned empty — downstream SRT
generation only needs segment timestamps.

Models download to MODELSCOPE_CACHE / HF cache (set by core.paths
.apply_cache_env at process start). FunASR pulls weights from ModelScope
by default; the SDK respects MODELSCOPE_CACHE for the snapshot directory.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

from core.ai.errors import AIError, Kind


EventCallback = Callable[..., None]


# SenseVoice supports these language codes. "auto" means let the model
# detect. Used by the AI Console language-routing dropdown to advertise
# which Asian languages are routable here.
SUPPORTED_LANGUAGES = ("zh", "yue", "en", "ja", "ko", "auto")


# ── Model cache ──────────────────────────────────────────────────────────────
# The FunASR AutoModel object is multi-hundred-MB. Cache per-process so
# back-to-back transcriptions reuse weights.

_MODEL_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _get_model(model_name: str, emit: Callable):
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
    emit("model_loading", model=model_name, device="auto", compute_type="auto")
    try:
        from funasr import AutoModel
    except ImportError as e:
        raise AIError(
            Kind.NETWORK, "SenseVoice",
            "FunASR not installed. Run: pip install funasr",
            raw=e,
        ) from e
    # VAD chunking keeps SenseVoice's max segment under 30s (the model's
    # training horizon). merge_vad + merge_length_s=15 keeps subtitle-
    # friendly chunk lengths so the SRT doesn't end up with 1-word lines
    # or 60s monologues.
    model = AutoModel(
        model=model_name,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        trust_remote_code=False,
        disable_update=True,    # don't phone home for SDK updates
    )
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE[model_name] = model
    emit("model_loaded", model=model_name, device="auto", compute_type="auto")
    return model


# ── Audio preprocessing ──────────────────────────────────────────────────────
# Same convention as parakeet_local: 16 kHz mono PCM WAV via ffmpeg. FunASR
# does internal resampling but explicit preprocessing makes the pipeline
# format-agnostic (mp4 / m4a / flac all work).

def _ensure_16k_mono_wav(src_path: str, tmp_dir: str) -> str:
    if not shutil.which("ffmpeg"):
        raise AIError(
            Kind.MALFORMED, "SenseVoice",
            "ffmpeg not found on PATH — required for audio preprocessing",
        )
    out_path = os.path.join(tmp_dir, "audio_16k.wav")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", src_path,
        "-ac", "1", "-ar", "16000",
        "-f", "wav", out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AIError(
            Kind.MALFORMED, "SenseVoice",
            f"ffmpeg preprocessing failed: {proc.stderr.strip()[:300]}",
        )
    return out_path


def _audio_duration_sec(path: str) -> float:
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            text=True, timeout=10,
        ).strip()
        return float(out) if out else 0.0
    except (subprocess.SubprocessError, ValueError):
        return 0.0


# ── Output postprocessing ────────────────────────────────────────────────────

# SenseVoice embeds language / emotion / audio-event tokens inside the text
# stream. For SRT we want plain text. This regex strips ALL <|...|> markers;
# FunASR ships rich_transcription_postprocess() for the same job but its
# import path varies between versions, so we keep our own.
_RICH_TOKEN_RE = re.compile(r"<\|[^|]*\|>")


def _clean_text(text: str) -> str:
    if not text:
        return ""
    return _RICH_TOKEN_RE.sub("", text).strip()


def _normalize_language(language: str | None) -> str:
    """SenseVoice expects 'auto' / 'zh' / 'en' / 'yue' / 'ja' / 'ko' /
    'nospeech'. None or empty string → 'auto'."""
    if not language:
        return "auto"
    s = language.strip().lower()
    if s in ("", "auto", "auto detect"):
        return "auto"
    return s


# ── Public API ───────────────────────────────────────────────────────────────

def transcribe(
    audio_path: str,
    *,
    model_name: str = "iic/SenseVoiceSmall",
    language: str | None = None,
    translate: bool = False,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio locally via FunASR + SenseVoiceSmall.

    Args:
        audio_path:  Path to audio/video. Transcoded to 16 kHz mono WAV
                     internally via ffmpeg.
        model_name:  FunASR model id. Default `iic/SenseVoiceSmall`.
        language:    SenseVoice language hint: auto / zh / en / yue /
                     ja / ko. None = auto.
        translate:   Not supported — SenseVoice does ASR only. Raises if True.
        on_event:    Optional callback(event_type, **kwargs). Same event
                     vocabulary as parakeet_local for UI consistency.
        cancel_token: Cooperative cancel (coarse — checked before/after
                     the blocking generate() call).

    Returns:
        dict normalized to lemonfox verbose_json shape. words[] is empty
        because SenseVoice does not produce word-level timestamps.

    Raises:
        AIError: model load / preprocessing / inference failure.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "SenseVoice",
                      f"Audio file not found: {audio_path}")

    if translate:
        raise AIError(Kind.MALFORMED, "SenseVoice",
                      "SenseVoice does not support translation — disable the "
                      "translate flag or route to a Whisper provider")

    sv_lang = _normalize_language(language)

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device="auto",
        compute_type="auto",
        language=sv_lang,
        translate="false",
    )

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "SenseVoice", "Cancelled by user")

    try:
        model = _get_model(model_name, emit)
    except AIError:
        raise
    except Exception as e:
        raise AIError(Kind.NETWORK, "SenseVoice",
                      f"Failed to load model {model_name!r}: {e}", raw=e) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "SenseVoice", "Cancelled by user")

    started = time.time()
    tmp_dir = tempfile.mkdtemp(prefix="sensevoice_")
    try:
        wav_path = _ensure_16k_mono_wav(audio_path, tmp_dir)
        duration = _audio_duration_sec(wav_path)

        try:
            results = model.generate(
                input=wav_path,
                cache={},
                language=sv_lang,
                use_itn=True,        # inverse text norm: 数字/单位 normalize
                batch_size_s=60,     # batch by total seconds
                merge_vad=True,      # merge tiny VAD chunks
                merge_length_s=15,   # subtitle-friendly chunk size
            )
        except Exception as e:
            raise AIError(Kind.UNKNOWN, "SenseVoice",
                          f"Inference failed: {e}", raw=e) from e

        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "SenseVoice", "Cancelled by user")

        segments_out, full_text = _normalize_results(results)

        elapsed = int(time.time() - started)
        emit("state_done", segment_count=len(segments_out), elapsed=elapsed)

        return {
            "language": sv_lang if sv_lang != "auto" else "auto",
            "duration": duration,
            "text":     full_text,
            "segments": segments_out,
            "words":    [],   # not produced by SenseVoice
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _normalize_results(results) -> tuple[list, str]:
    """Convert FunASR's varied return shapes into our standard segments.

    FunASR's return for an AutoModel(VAD + SenseVoice) call is a list.
    Each item typically carries:
      - 'key':       input filename
      - 'text':      text with rich-transcription tokens
      - 'timestamp': list of [start_ms, end_ms] per char/token
      - 'sentence_info' (when VAD merging is on, newer versions):
            list of {'start','end','text'} dicts in milliseconds

    We prefer sentence_info (already segment-level). When absent, fall
    back to one segment per top-level result item using its overall
    text + first/last timestamp.
    """
    if not results:
        return [], ""

    segments_out = []
    text_parts = []
    seg_id = 0

    for item in results:
        if not isinstance(item, dict):
            continue

        sent_info = item.get("sentence_info")
        if sent_info and isinstance(sent_info, list):
            for sent in sent_info:
                seg_text = _clean_text(sent.get("text", ""))
                if not seg_text:
                    continue
                start_ms = float(sent.get("start", 0))
                end_ms = float(sent.get("end", start_ms))
                segments_out.append({
                    "id":    seg_id,
                    "start": start_ms / 1000.0,
                    "end":   end_ms / 1000.0,
                    "text":  seg_text,
                })
                text_parts.append(seg_text)
                seg_id += 1
            continue

        # Fallback: one segment per item, derive bounds from timestamp[]
        seg_text = _clean_text(item.get("text", ""))
        if not seg_text:
            continue
        ts = item.get("timestamp") or []
        if ts and isinstance(ts, list) and len(ts) > 0:
            try:
                start_ms = float(ts[0][0])
                end_ms = float(ts[-1][1])
            except (TypeError, IndexError, ValueError):
                start_ms = end_ms = 0.0
        else:
            start_ms = end_ms = 0.0
        segments_out.append({
            "id":    seg_id,
            "start": start_ms / 1000.0,
            "end":   end_ms / 1000.0,
            "text":  seg_text,
        })
        text_parts.append(seg_text)
        seg_id += 1

    full_text = " ".join(text_parts).strip()
    return segments_out, full_text
