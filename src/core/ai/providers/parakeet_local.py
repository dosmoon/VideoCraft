"""Parakeet TDT local ASR provider (NVIDIA NeMo).

Runs Parakeet TDT 0.6B v3 (multilingual, 25 European languages) locally
via the NeMo toolkit. Tuned for the ASR router's "language=en/es/fr/..."
slot — Chinese should route to SenseVoice (separate provider, planned).

Output normalized to the same shape as faster_whisper / lemonfox:
    {language, duration, text, segments[], words[]}

Models download to NEMO_CACHE_DIR (set by core.paths.apply_cache_env at
process start — points to <models_dir>/nemo). NeMo expects 16 kHz mono
audio, so we transcode via ffmpeg into a temp WAV before inference.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

from core.ai.errors import AIError, Kind


EventCallback = Callable[..., None]


# Parakeet TDT v3 supports these 25 languages (plus English) — used by the
# router's language_routing UI to know which langs are routable here.
SUPPORTED_LANGUAGES = (
    "en", "bg", "hr", "cs", "da", "nl", "et", "fi", "fr", "de",
    "el", "hu", "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk",
    "sl", "es", "sv", "ru", "uk",
)


# ── Model cache ──────────────────────────────────────────────────────────────
# NeMo's ASRModel.from_pretrained() does its own internal cache, but the
# Python object itself is multi-GB to instantiate. Cache per-process.

_MODEL_CACHE: dict[str, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _get_model(model_name: str, emit: Callable):
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
    emit("model_loading", model=model_name, device="auto", compute_type="auto")
    try:
        from nemo.collections.asr.models import ASRModel
    except ImportError as e:
        raise AIError(
            Kind.NETWORK, "Parakeet",
            "NeMo toolkit not installed. Run: pip install nemo_toolkit[asr]",
            raw=e,
        ) from e
    model = ASRModel.from_pretrained(model_name=model_name)
    # Keep on whatever device NeMo picked (cuda if available, else cpu).
    model.eval()
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE[model_name] = model
    device = _device_str(model)
    emit("model_loaded", model=model_name, device=device, compute_type="auto")
    return model


def _device_str(model) -> str:
    try:
        return str(next(model.parameters()).device)
    except Exception:
        return "unknown"


# ── Audio preprocessing ──────────────────────────────────────────────────────

def _ensure_16k_mono_wav(src_path: str, tmp_dir: str) -> str:
    """Transcode arbitrary audio/video into 16 kHz mono PCM WAV via ffmpeg.
    Returns the temp WAV path. Caller owns cleanup of tmp_dir."""
    if not shutil.which("ffmpeg"):
        raise AIError(
            Kind.MALFORMED, "Parakeet",
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
            Kind.MALFORMED, "Parakeet",
            f"ffmpeg preprocessing failed: {proc.stderr.strip()[:300]}",
        )
    return out_path


def _audio_duration_sec(path: str) -> float:
    """Best-effort WAV duration via ffprobe. Returns 0.0 if unavailable."""
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


# ── Public API ───────────────────────────────────────────────────────────────

def transcribe(
    audio_path: str,
    *,
    model_name: str = "nvidia/parakeet-tdt-0.6b-v3",
    language: str | None = None,
    translate: bool = False,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """Transcribe audio locally via NeMo Parakeet TDT.

    Args:
        audio_path:  Path to audio/video; transcoded to 16 kHz mono WAV
                     internally via ffmpeg.
        model_name:  HF model id. Default is the multilingual v3 checkpoint.
        language:    Hint kept in returned `language` field; Parakeet v3
                     itself auto-detects across its 25 supported languages.
                     None = auto.
        translate:   Not supported — Parakeet does ASR only. Raises if True.
        on_event:    Optional callback(event_type, **kwargs). Event types
                     mirror faster_whisper for UI consistency:
                       request_summary_local / model_loading / model_loaded
                       state_processing / state_done
        cancel_token: Cooperative cancel checked at coarse boundaries
                     (Parakeet's transcribe() is one blocking call — cannot
                     interrupt mid-inference).

    Returns:
        dict normalized to lemonfox verbose_json shape.

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
        raise AIError(Kind.MALFORMED, "Parakeet",
                      f"Audio file not found: {audio_path}")

    if translate:
        raise AIError(Kind.MALFORMED, "Parakeet",
                      "Parakeet does not support translation — disable the "
                      "translate flag or route to a Whisper provider")

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device="auto",
        compute_type="auto",
        language=language or "auto",
        translate="false",
    )

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "Parakeet", "Cancelled by user")

    try:
        model = _get_model(model_name, emit)
    except AIError:
        raise
    except Exception as e:
        raise AIError(Kind.NETWORK, "Parakeet",
                      f"Failed to load model {model_name!r}: {e}", raw=e) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "Parakeet", "Cancelled by user")

    started = time.time()
    tmp_dir = tempfile.mkdtemp(prefix="parakeet_")
    try:
        wav_path = _ensure_16k_mono_wav(audio_path, tmp_dir)
        duration = _audio_duration_sec(wav_path)

        try:
            # NeMo 2.x: transcribe() returns list of Hypothesis with .text
            # and .timestamp = {'word': [...], 'segment': [...], 'char': [...]}
            results = model.transcribe([wav_path], timestamps=True)
        except TypeError:
            # Older NeMo versions don't accept timestamps kwarg.
            results = model.transcribe([wav_path])
        except Exception as e:
            raise AIError(Kind.UNKNOWN, "Parakeet",
                          f"Inference failed: {e}", raw=e) from e

        if cancel_token is not None and cancel_token.cancelled:
            raise AIError(Kind.CANCELLED, "Parakeet", "Cancelled by user")

        hyp = results[0] if results else None
        text, segments_out, words_out = _normalize_hypothesis(hyp)

        elapsed = int(time.time() - started)
        emit("state_done", segment_count=len(segments_out), elapsed=elapsed)

        return {
            "language": language or "auto",
            "duration": duration,
            "text":     text,
            "segments": segments_out,
            "words":    words_out,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _normalize_hypothesis(hyp) -> tuple[str, list, list]:
    """Convert a NeMo Hypothesis (or plain string) into our standard shape.

    NeMo's transcribe() return shape varies by version:
      - 2.x with timestamps=True: Hypothesis(text=..., timestamp={'segment':
        [{'segment','start','end','start_offset','end_offset'}, ...], 'word':
        [{'word','start','end',...}, ...]})
      - older: list[str]
    """
    if hyp is None:
        return "", [], []

    if isinstance(hyp, str):
        return hyp.strip(), [], []

    text = (getattr(hyp, "text", "") or "").strip()
    ts = getattr(hyp, "timestamp", None) or {}
    seg_ts = ts.get("segment") or []
    word_ts = ts.get("word") or []

    segments_out = []
    for idx, s in enumerate(seg_ts):
        segments_out.append({
            "id":    idx,
            "start": float(s.get("start", 0.0)),
            "end":   float(s.get("end", 0.0)),
            "text":  (s.get("segment") or s.get("text") or "").strip(),
        })

    words_out = []
    for w in word_ts:
        words_out.append({
            "start": float(w.get("start", 0.0)),
            "end":   float(w.get("end", 0.0)),
            "word":  (w.get("word") or "").strip(),
        })

    # Fallback: if model returned text but no segment timestamps, emit one
    # whole-clip segment so SRT generation still works.
    if text and not segments_out:
        segments_out.append({"id": 0, "start": 0.0, "end": 0.0, "text": text})

    return text, segments_out, words_out
