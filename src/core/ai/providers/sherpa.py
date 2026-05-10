"""sherpa-onnx provider — in-process Whisper ASR.

Part of VideoCraft's "embedded AI" tier (see
docs/draft/tech-selection-embedded-ai.md): runs Whisper-small int8 fully
in-process on CPU. No Docker, no network. Model files live under
`<repo>/user_data/models/sherpa/whisper-small/` via core.paths.

Returns the same verbose_json dict shape as the aistack and lemonfox
providers, so router.py / core.asr / translate_srt can consume it
unchanged:

    {language, duration, text, segments[], words[]}

`words[]` is ALWAYS empty for the standard int8 export — the
cross-attention outputs needed for word-level timestamps are not in the
published model. Sentence-level `segments[]` works. See
`feedback_asr_no_client_cue_sizing` memo for why this is acceptable.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Callable

import numpy as np

from core.ai.errors import AIError, Kind
from core.lang_names import WHISPER_LANGUAGES
from core.paths import cache_subdir


EventCallback = Callable[..., None]

DEFAULT_MODEL_NAME = "whisper-small"
_SAMPLE_RATE = 16000

# Lazy cache keyed by (model_dir, language). Loading int8 takes ~1.2s on
# a 4060 laptop; amortize across calls so the AI Console feels snappy.
_RECOGNIZER_CACHE: dict[tuple[str, str], object] = {}


def _model_dir(name: str = DEFAULT_MODEL_NAME) -> str:
    return os.path.join(cache_subdir("sherpa"), name)


def _normalize_language(lang: str | None) -> str:
    """Coerce a language hint to an ISO-639-1 code that sherpa-onnx accepts.

    Accepts either an ISO code ("en") or the WHISPER_LANGUAGES English
    display name ("English"). Unknown / None defaults to "en".
    """
    if not lang:
        return "en"
    s = lang.strip().lower()
    # Already an ISO code we know about
    if s in WHISPER_LANGUAGES:
        return s
    # Display name lookup
    for code, (eng, _chn) in WHISPER_LANGUAGES.items():
        if eng.lower() == s:
            return code
    # Unknown — fall back to "en". Surfacing an error here would block
    # users with non-ASCII display names that we just don't have a mapping
    # for; defaulting is friendlier and Whisper auto-handles minor mismatch.
    return "en"


def _model_files(model_dir: str, size: str = "small") -> tuple[str, str, str]:
    enc = os.path.join(model_dir, f"{size}-encoder.int8.onnx")
    dec = os.path.join(model_dir, f"{size}-decoder.int8.onnx")
    tok = os.path.join(model_dir, f"{size}-tokens.txt")
    return enc, dec, tok


def _load_recognizer(model_dir: str, language: str | None, *, num_threads: int):
    import sherpa_onnx as so

    key = (model_dir, language or "en")
    cached = _RECOGNIZER_CACHE.get(key)
    if cached is not None:
        return cached

    enc, dec, tok = _model_files(model_dir)
    missing = [p for p in (enc, dec, tok) if not os.path.exists(p)]
    if missing:
        raise AIError(
            Kind.MALFORMED, "sherpa",
            "Sherpa Whisper model files missing:\n  "
            + "\n  ".join(missing)
            + f"\nDownload from HuggingFace 'csukuangfj/sherpa-onnx-{DEFAULT_MODEL_NAME}' "
              f"into:\n  {model_dir}"
        )

    rec = so.OfflineRecognizer.from_whisper(
        encoder=enc,
        decoder=dec,
        tokens=tok,
        language=language or "en",
        task="transcribe",
        num_threads=num_threads,
        decoding_method="greedy_search",
        provider="cpu",
        # Stock int8 export lacks cross-attention; token timestamps cannot
        # be produced. Segment-level timestamps DO work.
        enable_token_timestamps=False,
        enable_segment_timestamps=True,
    )
    _RECOGNIZER_CACHE[key] = rec
    return rec


def _decode_audio_to_pcm16k(audio_path: str) -> np.ndarray:
    """Use ffmpeg to decode any audio/video file to 16kHz mono float32 PCM."""
    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", str(_SAMPLE_RATE),
        "-ac", "1",
        "-loglevel", "error",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
    except FileNotFoundError as e:
        raise AIError(
            Kind.MALFORMED, "sherpa",
            "ffmpeg not found on PATH. Install ffmpeg and ensure it's on PATH.",
            raw=e,
        ) from e
    except subprocess.CalledProcessError as e:
        msg = e.stderr.decode("utf-8", errors="replace")[:400] if e.stderr else "unknown"
        raise AIError(
            Kind.MALFORMED, "sherpa",
            f"ffmpeg decode failed for {os.path.basename(audio_path)}: {msg}",
            raw=e,
        ) from e

    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _segments_from_result(r) -> list[dict]:
    """Convert sherpa Result.segment_{texts,timestamps,durations} → segments[]."""
    texts = list(getattr(r, "segment_texts", []) or [])
    starts = list(getattr(r, "segment_timestamps", []) or [])
    durs = list(getattr(r, "segment_durations", []) or [])
    n = max(len(texts), len(starts), len(durs))
    out = []
    for i in range(n):
        text = texts[i] if i < len(texts) else ""
        start = float(starts[i]) if i < len(starts) else 0.0
        dur = float(durs[i]) if i < len(durs) else 0.0
        out.append({
            "id": i,
            "start": start,
            "end": start + dur,
            "text": text,
        })
    # Very short audio sometimes yields .text with empty segment_texts;
    # collapse to a single segment so downstream SRT writer has something.
    if not out and getattr(r, "text", None):
        out.append({"id": 0, "start": 0.0, "end": 0.0, "text": r.text})
    return out


def transcribe(
    audio_path: str,
    *,
    model_dir: str | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    language: str | None = None,
    translate: bool = False,
    num_threads: int = 4,
    on_event: EventCallback | None = None,
    cancel_token=None,
) -> dict:
    """In-process Whisper transcription via sherpa-onnx.

    Args:
        audio_path:   Local audio/video file. Decoded by ffmpeg to 16k mono.
        model_dir:    Override for model directory. None = default
                      `<models>/sherpa/<model_name>/`.
        model_name:   Subdir name under `<models>/sherpa/`. Default
                      "whisper-small" matches the first-launch tier.
        language:     ISO-639-1 hint (e.g. "en", "zh"). None defaults to
                      "en". Sherpa Whisper requires the language at
                      recognizer-load time; auto-detect is not supported
                      by this provider yet — use aistack for that.
        translate:    Not supported here. Raises MALFORMED if True.
        num_threads:  CPU threads for inference. 4 is a sane default.
        on_event:     Status callback. Emits request_summary_local on
                      entry, state_done at end with elapsed + segment count.
        cancel_token: Polled before / after decode. sherpa-onnx C++ runs
                      synchronously and cannot be interrupted mid-call;
                      cancel is coarse-grained.

    Returns:
        verbose_json dict (same shape as aistack/lemonfox):
            {language, duration, text, segments[], words[]}

        - segments[] is sentence-level (drives row-by-row SRT translation)
        - words[] is ALWAYS [] — stock int8 model has no cross-attention
          export. Acceptable per ASR cue-sizing contract.

    Raises:
        AIError(MALFORMED): file missing / ffmpeg failure / model files missing /
                            translate=True (unsupported).
        AIError(CANCELLED): user cancelled before or after decode.
        AIError(UNKNOWN):   sherpa-onnx internal error.
    """
    def emit(event_type: str, **kwargs):
        if on_event is None:
            return
        try:
            on_event(event_type, **kwargs)
        except Exception:
            pass

    if not os.path.exists(audio_path):
        raise AIError(Kind.MALFORMED, "sherpa", f"Audio file not found: {audio_path}")

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa", "Cancelled by user")

    if translate:
        raise AIError(
            Kind.MALFORMED, "sherpa",
            "translate=True not supported by sherpa-onnx Whisper provider yet. "
            "Use aistack or lemonfox for to-English translation."
        )

    md = model_dir or _model_dir(model_name)
    iso_lang = _normalize_language(language)

    emit(
        "request_summary_local",
        filename=os.path.basename(audio_path),
        model=model_name,
        device="sherpa-cpu",
        compute_type="int8",
        language=iso_lang,
        translate="false",
    )

    samples = _decode_audio_to_pcm16k(audio_path)
    duration = len(samples) / float(_SAMPLE_RATE)

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa", "Cancelled by user")

    rec = _load_recognizer(md, iso_lang, num_threads=num_threads)

    started = time.monotonic()
    try:
        stream = rec.create_stream()
        stream.accept_waveform(_SAMPLE_RATE, samples)
        rec.decode_stream(stream)
    except Exception as e:
        raise AIError(Kind.UNKNOWN, "sherpa",
                      f"sherpa-onnx decode failed: {e}", raw=e) from e

    if cancel_token is not None and cancel_token.cancelled:
        raise AIError(Kind.CANCELLED, "sherpa", "Cancelled by user")

    elapsed = time.monotonic() - started
    r = stream.result
    segments = _segments_from_result(r)

    emit("state_done",
         segment_count=len(segments),
         elapsed=int(elapsed))

    return {
        "language": getattr(r, "lang", None) or iso_lang,
        "duration": duration,
        "text": getattr(r, "text", "") or "",
        "segments": segments,
        "words": [],
    }
