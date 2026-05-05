"""Faster-Whisper local ASR provider.

Runs Whisper inference fully on the user's machine via the
`faster-whisper` package (CTranslate2 backend, auto CUDA when available).

Output is normalized to the same shape Lemonfox returns so feature/UI
code can consume both providers without branching:
    {language, duration, text, segments[], words[]}

Models are downloaded on first use to the HuggingFace cache. Loaded
models are cached per (model, device, compute_type) tuple so repeat
transcriptions in the same session don't re-load weights.
"""

import os
import threading
import time
from typing import Callable

from core.ai.errors import AIError, Kind


# Map English / Chinese display names back to ISO codes. faster-whisper
# only accepts ISO codes (en, zh, …); upstream UI happily passes "English"
# / "Chinese" because LemonFox tolerates both. Built lazily to avoid a
# hard import-time dep on core.translate when this module is imported by
# tooling/tests.
_LANG_NAME_TO_ISO: dict[str, str] | None = None


def _resolve_language(language: str | None) -> str | None:
    """Normalize a language hint to a Whisper ISO code (or None for auto).

    Accepts:
      - None or "" / "auto"      -> None (auto-detect)
      - already-ISO codes        -> as-is when 2-3 chars
      - English display names    -> mapped via core.translate
      - Chinese display names    -> mapped via core.translate
    """
    if not language or language.strip().lower() in ("auto", "auto detect"):
        return None
    s = language.strip()
    # Shortcut: already looks like an ISO code (2-3 lowercase letters).
    if 2 <= len(s) <= 3 and s.isalpha() and s.islower():
        return s

    global _LANG_NAME_TO_ISO
    if _LANG_NAME_TO_ISO is None:
        try:
            from core.translate import SUPPORTED_LANGUAGES
            _LANG_NAME_TO_ISO = {}
            for iso, (english, chinese) in SUPPORTED_LANGUAGES.items():
                if iso == "auto":
                    continue
                _LANG_NAME_TO_ISO[english.lower()] = iso
                _LANG_NAME_TO_ISO[chinese] = iso
        except Exception:
            _LANG_NAME_TO_ISO = {}

    iso = _LANG_NAME_TO_ISO.get(s.lower()) or _LANG_NAME_TO_ISO.get(s)
    return iso  # may be None if name unknown — let caller decide


EventCallback = Callable[..., None]


# ── Model cache ──────────────────────────────────────────────────────────────
# Loading a Whisper model is expensive (download on cold start, plus a few
# seconds to map weights even when cached). We keep a process-wide cache so
# back-to-back transcriptions reuse the same instance.

_MODEL_CACHE: dict[tuple, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _resolve_device(device: str) -> str:
    # "auto" intentionally defaults to CPU. Even when ctranslate2 reports
    # CUDA devices, faster-whisper's encode() requires cublas64_12.dll +
    # cuDNN at runtime — not bundled with the wheel. Users who actually
    # have CUDA 12 + cuDNN installed must opt in explicitly with
    # device="cuda" so we don't surprise the typical user with a missing
    # DLL error mid-transcription.
    if device == "auto":
        return "cpu"
    return device


def _resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    # faster-whisper recommended defaults: float16 on CUDA, int8 on CPU.
    return "float16" if device == "cuda" else "int8"


def _get_model(model_name: str, device: str, compute_type: str,
               emit: Callable):
    key = (model_name, device, compute_type)
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            return cached
    emit("model_loading", model=model_name, device=device,
         compute_type=compute_type)
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE[key] = model
    emit("model_loaded", model=model_name, device=device,
         compute_type=compute_type)
    return model


# ── Public API ───────────────────────────────────────────────────────────────

def transcribe(
    audio_path: str,
    *,
    model_name: str = "small",
    device: str = "auto",
    compute_type: str = "auto",
    beam_size: int = 5,
    language: str | None = None,
    translate: bool = False,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio locally via faster-whisper.

    Args:
        audio_path:   Audio/video file readable by ffmpeg (handled by the
                      underlying CTranslate2 model).
        model_name:   Whisper size: tiny / base / small / medium /
                      large-v3 / large-v3-turbo. First use of a size
                      triggers a download to the HuggingFace cache.
        device:       "auto" (cuda if available, else cpu) / "cpu" / "cuda".
        compute_type: "auto" (float16 on cuda, int8 on cpu) /
                      int8 / int8_float16 / float16 / float32.
        beam_size:    Beam search width — 5 is faster-whisper's default.
        language:     ISO 639-1 code (e.g. "zh", "en"). None = auto-detect.
        translate:    If True, translate to English instead of transcribing
                      in the source language.
        on_event:     Optional callback(event_type, **kwargs). Event types:
                      "request_summary", "model_loading", "model_loaded",
                      "state_processing" (segment_count, elapsed),
                      "state_done" (segment_count, elapsed).
        cancel_token: Cooperatively checked between segments.

    Returns:
        dict normalized to Lemonfox's verbose_json shape:
            {language, duration, text, segments[], words[]}

    Raises:
        AIError: model load / inference failure.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass  # UI errors in callbacks must not derail transcription

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "Faster-Whisper",
                      f"Audio file not found: {audio_path}")

    resolved_device = _resolve_device(device)
    resolved_compute = _resolve_compute_type(compute_type, resolved_device)
    resolved_language = _resolve_language(language)

    # Use a dedicated event type so the UI can render a local-mode log
    # line without LemonFox's url/mime/timeout fields (avoids the
    # "n/as" cosmetic glitch that came from re-using the cloud
    # i18n template).
    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device=resolved_device,
        compute_type=resolved_compute,
        language=resolved_language or "auto",
        translate=str(translate).lower(),
    )

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "Faster-Whisper", "Cancelled by user")

    try:
        model = _get_model(model_name, resolved_device, resolved_compute, emit)
    except Exception as e:
        raise AIError(Kind.NETWORK, "Faster-Whisper",
                      f"Failed to load model {model_name!r}: {e}", raw=e) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "Faster-Whisper", "Cancelled by user")

    started = time.time()
    try:
        segments_iter, info = model.transcribe(
            audio_path,
            language=resolved_language,
            task="translate" if translate else "transcribe",
            beam_size=beam_size,
            word_timestamps=True,
            vad_filter=True,
        )
    except Exception as e:
        raise AIError(Kind.UNKNOWN, "Faster-Whisper",
                      f"Inference failed: {e}", raw=e) from e

    segments_out = []
    words_out = []
    text_parts = []

    for idx, seg in enumerate(segments_iter):
        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "Faster-Whisper",
                          "Cancelled by user")

        seg_text = (seg.text or "").strip()
        seg_dict = {
            "id":    idx,
            "start": float(seg.start),
            "end":   float(seg.end),
            "text":  seg_text,
        }
        # Optional fields some downstream consumers expect (avg_logprob,
        # no_speech_prob etc.) — fill when present.
        for attr in ("avg_logprob", "no_speech_prob",
                     "compression_ratio", "temperature"):
            v = getattr(seg, attr, None)
            if v is not None:
                seg_dict[attr] = float(v)
        segments_out.append(seg_dict)
        if seg_text:
            text_parts.append(seg_text)

        if seg.words:
            for w in seg.words:
                words_out.append({
                    "start": float(w.start),
                    "end":   float(w.end),
                    "word":  (w.word or "").strip(),
                })

        if (idx + 1) % 5 == 0:
            emit("state_processing",
                 segment_count=idx + 1,
                 elapsed=int(time.time() - started))

    elapsed = int(time.time() - started)
    emit("state_done", segment_count=len(segments_out), elapsed=elapsed)

    return {
        "language": info.language,
        "duration": float(info.duration),
        "text":     " ".join(text_parts),
        "segments": segments_out,
        "words":    words_out,
    }
